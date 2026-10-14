#!/usr/bin/env python3
"""Service-qualified warm reserve for AWG Pi Gateway (SHADOW-ONLY by default).

Uses the existing isolated service-scan for fresh network-level ChatGPT/YouTube
verification. Never touches the live selector, TUN, routing, or MikroTik.
No secrets, URLs, video bytes or raw provider profiles are persisted.
"""
from __future__ import annotations
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

POOL = Path(os.environ.get('AWG_HOT_POOL_SOURCE', '/run/awg-pbr/mihomo-pool/live.json'))
PROVIDER = Path(os.environ.get('AWG_HOT_POOL_PROVIDER', '/var/lib/awg-pbr/mihomo/providers/subscription.yaml'))
STATE = Path(os.environ.get('AWG_HOT_POOL_STATE', '/run/awg-pbr/hot-pool/shadow.json'))
SCAN = os.environ.get('AWG_HOT_POOL_SCANNER', '/usr/local/sbin/awg-mihomo-smart')
GATE = os.environ.get('AWG_HOT_POOL_GATE', '/usr/local/sbin/awg-mihomo-network-eligibility.py')
POLICY = Path(os.environ.get('MIHOMO_POOL_POLICY_FILE', '/etc/awg-pbr/transports/mihomo/pool-policy.env'))
PASS_MIN_INTERVAL = 600
READY_MAX_AGE = 3600
POOL_MAX_AGE = 7200
RETRY_FAILED = 1200
QUARANTINE_SECS = 7200
MAX_PROBES = 2
CURRENT_FILE = Path('/etc/awg-pbr/transports/mihomo/node-name')
PROBE_TIMEOUT = 110


def sha256(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def identity(node: dict) -> str:
    stable = [node[k] for k in ('name', 'type', 'server', 'port')]
    return hashlib.sha256(json.dumps(stable, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def endpoint(node: dict) -> str:
    # Names and credentials never affect shared endpoint quarantine.
    stable = [str(node['server']).strip().casefold(), int(node['port'])]
    return hashlib.sha256(json.dumps(stable, separators=(',', ':')).encode()).hexdigest()


def empty(digest: str) -> dict:
    return {'version': 1, 'provider_sha256': digest, 'checks': {}, 'quarantine': {}}


def load_state(path: Path, digest: str, now: int) -> dict:
    try:
        obj = json.loads(path.read_text())
        if obj.get('version') != 1 or not isinstance(obj.get('quarantine'), dict):
            raise ValueError('invalid state')
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return empty(digest)
    quarantine = {k: v for k, v in obj['quarantine'].items()
                  if isinstance(k, str) and isinstance(v, dict)
                  and type(v.get('until')) is int and v['until'] > now
                  and v.get('reason') in ('activation-failed', 'active-health-failed')}
    if obj.get('provider_sha256') != digest:
        return {**empty(digest), 'quarantine': quarantine}
    checks = obj.get('checks') if isinstance(obj.get('checks'), dict) else {}
    # Treat malformed/stale records as unqualified rather than crashing warm().
    clean = {}
    for key, record in checks.items():
        if not isinstance(key, str) or not isinstance(record, dict):
            continue
        stamps = record.get('passes', [])
        if not isinstance(stamps, list):
            continue
        stamps = [t for t in stamps if type(t) is int and 0 <= now - t <= READY_MAX_AGE]
        last_checked = record.get('last_checked')
        if type(last_checked) is not int or last_checked > now + 60:
            continue
        if record.get('last_result') not in ('PASS', 'FAIL'):
            continue
        clean[key] = {'passes': stamps[-2:], 'last_result': record['last_result'],
                      'last_checked': last_checked}
    return {'version': 1, 'provider_sha256': digest, 'checks': clean,
            'quarantine': quarantine}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    import tempfile
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                     prefix='.hot-', delete=False) as f:
        tmp = f.name
        os.fchmod(f.fileno(), 0o600)
        json.dump(state, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')
    os.replace(tmp, path)


def pool_policy() -> tuple[str, str]:
    try:
        s = POLICY.read_text()
        m = re.search(r'^MIHOMO_POOL_REGION=(all|europe)$', s, re.M)
        q = re.search(r'^MIHOMO_POOL_PROTOCOL=(all|vless|trojan|hysteria2|ss|vmess)$', s, re.M)
        return (m.group(1) if m else 'all', q.group(1) if q else 'all')
    except OSError:
        return ('all', 'all')


def literal_public_ipv4(server: object) -> bool:
    # Current isolated service-scan enforces a globally routable literal IPv4
    # and verified DIRECT route. Avoid wasting scan slots on DNS hostnames or
    # non-public addresses. Never rewrite provider endpoints.
    try:
        ip = ipaddress.ip_address(server)
        return ip.version == 4 and ip.is_global
    except (ValueError, TypeError):
        return False


def load_nodes(pool: Path, provider: Path, now: int, region='all', protocol='all') -> tuple[str, list[dict]]:
    digest = sha256(provider)
    obj = json.loads(pool.read_text())
    if obj.get('provider_sha256') != digest:
        raise ValueError('Provider digest mismatch (stale pool)')
    age = now - int(obj.get('scanned_at', 0))
    if age < -60 or age > POOL_MAX_AGE:
        raise ValueError('Health pool is stale')
    if region == 'europe' and not obj.get('geo_enriched'):
        raise ValueError('Europe-only pool without verified geo')
    raw = [n for n in obj.get('nodes', []) if isinstance(n, dict) and n.get('healthy')
           and isinstance(n.get('delay_ms'), int) and n['delay_ms'] > 0
           and all(n.get(k) for k in ('name', 'type', 'server', 'port'))
           and literal_public_ipv4(n.get('server'))
           and not n.get('duplicate_name') and (region != 'europe' or n.get('europe'))
           and (protocol == 'all' or n.get('type') == protocol)]
    names = {}
    for n in raw:
        names[n['name']] = names.get(n['name'], 0) + 1
    nodes = [n for n in raw if names[n['name']] == 1]
    nodes.sort(key=lambda n: (n['delay_ms'], n.get('index', 999999)))
    return digest, nodes


def is_ready(node: dict, state: dict, now: int) -> bool:
    if endpoint(node) in state['quarantine']:
        return False
    obj = state['checks'].get(identity(node), {})
    passes = obj.get('passes', [])
    return (obj.get('last_result') == 'PASS' and isinstance(passes, list)
            and len(passes) >= 2 and isinstance(passes[-1], int)
            and isinstance(passes[-2], int)
            and passes[-1] - passes[-2] >= PASS_MIN_INTERVAL
            and 0 <= now - passes[-1] <= READY_MAX_AGE
            and 0 <= now - passes[-2] <= READY_MAX_AGE)


def shortlist(nodes: list[dict], state: dict, current: str, max_endpoints=12) -> list[dict]:
    """Best-latency candidates, distinct endpoint, bounded per protocol."""
    selected, seen, count = [], set(), {}
    for node in nodes:
        ep = endpoint(node)
        proto = str(node['type']).lower()
        if node['name'] == current or ep in seen or ep in state['quarantine']:
            continue
        if count.get(proto, 0) >= 4:
            continue
        selected.append(node)
        seen.add(ep)
        count[proto] = count.get(proto, 0) + 1
        if len(selected) >= max_endpoints:
            break
    return selected


def eligible_for_probe(node: dict, state: dict, now: int) -> bool:
    record = state['checks'].get(identity(node), {})
    raw_last = record.get('last_checked', 0)
    last = raw_last if type(raw_last) is int else 0
    if record.get('last_result') == 'FAIL' and now - last < RETRY_FAILED:
        return False
    if record.get('last_result') == 'PASS':
        if is_ready(node, state, now):
            return False
        passes = record.get('passes', [])
        if passes and type(passes[-1]) is int and 0 <= now - passes[-1] < PASS_MIN_INTERVAL:
            return False
    return True


def record_scan(state: dict, node: dict, passed: bool, now: int) -> None:
    key = identity(node)
    old = state['checks'].get(key, {})
    passes = old.get('passes', []) if old.get('last_result') == 'PASS' else []
    passes = [x for x in passes if type(x) is int and 0 <= now - x <= READY_MAX_AGE]
    if passed:
        if not passes or now - passes[-1] >= PASS_MIN_INTERVAL:
            passes = (passes + [now])[-2:]
    else:
        passes = []
    state['checks'][key] = {'passes': passes, 'last_result': 'PASS' if passed else 'FAIL',
                            'last_checked': now}


def failure(state: dict, nodes: list[dict], name: str, now: int, reason: str) -> int:
    match = [n for n in nodes if n['name'] == name]
    if len(match) != 1:
        raise ValueError('Failed node not uniquely present in live health pool')
    ep = endpoint(match[0])
    before = state['quarantine'].get(ep, {})
    old_count = before.get('count', 0)
    count = min(4, (old_count if type(old_count) is int and old_count >= 0 else 0) + 1)
    state['quarantine'][ep] = {'until': now + QUARANTINE_SECS * min(count, 3),
                               'count': count, 'reason': reason}
    for n in nodes:
        if endpoint(n) == ep:
            state['checks'].pop(identity(n), None)
    return sum(endpoint(n) == ep for n in nodes)


def scanner_error_family(stderr: str) -> str:
    # Categorize Python traceback text without ever logging its raw content:
    # provider configs and service URL query strings may be embedded in it.
    data = (stderr or '').lower()[-16000:]
    if 'read-only file system' in data:
        return 'SANDBOX_READ_ONLY'
    if 'permission denied' in data:
        return 'SANDBOX_PERMISSION_DENIED'
    if 'operation not permitted' in data:
        return 'SANDBOX_OPERATION_DENIED'
    if 'blockingioerror' in data or 'resource temporarily unavailable' in data:
        return 'SCANNER_LOCK_CONFLICT'
    if 'service candidate endpoint not direct' in data:
        return 'CANDIDATE_NOT_DIRECT'
    if 'service candidate lacks verified literal endpoint' in data:
        return 'CANDIDATE_NOT_LITERAL'
    if 'service candidate missing or ambiguous' in data:
        return 'CANDIDATE_NOT_UNIQUE'
    if 'invalid service candidate' in data:
        return 'INVALID_CANDIDATE'
    if 'isolated service candidate exited' in data:
        return 'ISOLATED_START_FAILED'
    if 'isolated service candidate unavailable' in data:
        return 'ISOLATED_CONTROLLER_TIMEOUT'
    if 'no such file or directory' in data:
        return 'MISSING_PATH_OR_BINARY'
    if 'modulenotfounderror' in data or 'importerror' in data:
        return 'SCANNER_IMPORT_FAILURE'
    return 'SCANNER_EXCEPTION'


def sanitized_trace_point(stderr: str) -> str:
    # Diagnostic metadata only. Never echo trace lines, URLs or exception text.
    lines = (stderr or '').splitlines()
    frames = []
    pattern = r'^[ ]*File "([^"]+)", line ([0-9]{1,5}), in ([A-Za-z_][A-Za-z_0-9]{0,70})$'
    for line in lines:
        match = re.match(pattern, line)
        if match:
            filename, lineno, func = match.groups()
            basename = filename.rsplit('/', 1)[-1]
            if basename in ('awg-mihomo-smart', 'awg-mihomo-pool',
                            'socket.py', 'urllib.py', 'request.py', 'tempfile.py',
                            'subprocess.py', 'pathlib.py', 'os.py', 'fcntl.py'):
                frames.append(f'{basename}:{lineno}:{func}')
    last = lines[-1].strip() if lines else ''
    cls = last.split(':', 1)[0]
    error_class = cls if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,60}', cls) else 'UNKNOWN'
    return ('ERROR_CLASS=' + error_class + ' STACK=' +
            (frames[-1] if frames else 'UNKNOWN'))


def scan_one(name: str) -> tuple[bool, str]:
    # Only known bounded status tokens are emitted. Never log URLs, raw
    # scanner stderr, subscription profiles, tokens or media identifiers.
    try:
        outcome = subprocess.run([SCAN, 'service-scan', '--node', name],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=PROBE_TIMEOUT, check=False)
        if len(outcome.stdout) > 8192:
            return False, 'REASON=SCANNER_OVERSIZE'
        if not outcome.stdout:
            return False, ('REASON=SCANNER_EMPTY SCAN_RC=' + str(outcome.returncode)
                           + ' SCAN_FAMILY=' + scanner_error_family(outcome.stderr)
                           + ' ' + sanitized_trace_point(outcome.stderr))
        fields = {}
        allowed = {'SERVICE_CHECK_OPENAI_API', 'SERVICE_CHECK_CHATGPT_WEB',
                   'SERVICE_CHECK_YOUTUBE_VIDEO', 'SERVICE_REASON_CHATGPT_WEB'}
        for line in outcome.stdout.splitlines():
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            if key in allowed and re.fullmatch(r'[a-zA-Z0-9_]{1,64}', value):
                fields[key] = value
        gate = subprocess.run([GATE], input=outcome.stdout, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=8, check=False)
        reason = 'GATE_NO_REASON'
        for line in gate.stdout.splitlines():
            if line.startswith('NETWORK_REASON='):
                candidate = line.split('=', 1)[1]
                if re.fullmatch(r'[A-Z0-9_]{1,64}', candidate):
                    reason = candidate
        status = lambda key: fields.get(key, 'MISSING')
        summary = ('SCAN_RC=' + str(outcome.returncode) +
                   ' OPENAI=' + status('SERVICE_CHECK_OPENAI_API') +
                   ' CHATGPT=' + status('SERVICE_CHECK_CHATGPT_WEB') +
                   ' YOUTUBE24=' + status('SERVICE_CHECK_YOUTUBE_VIDEO') +
                   ' WEB_REASON=' + status('SERVICE_REASON_CHATGPT_WEB') +
                   ' GATE_REASON=' + reason)
        return gate.returncode == 0, summary
    except subprocess.TimeoutExpired:
        return False, 'REASON=SCANNER_OR_GATE_TIMEOUT'
    except OSError:
        return False, 'REASON=SCANNER_OR_GATE_EXEC_ERROR'


def probe_order(nodes: list[dict], state: dict, now: int) -> list[dict]:
    # Fair, bounded selection: finish one-pass confirmations first, explore
    # never-tested unique endpoints next, retry failures only after fresh nodes.
    # Prevent two low-latency but consistently ineligible nodes monopolizing
    # each scheduled two-probe cycle.
    def priority(node: dict) -> tuple[int, int, int]:
        record = state['checks'].get(identity(node))
        if not record:
            return (1, 0, node['delay_ms'])
        passes = record.get('passes', [])
        if record.get('last_result') == 'PASS' and passes and not is_ready(node, state, now):
            return (0, int(record.get('last_checked', 0)), node['delay_ms'])
        # Failed candidates are still eligible after retry cooldown, but last.
        return (2, int(record.get('last_checked', 0)), node['delay_ms'])
    return sorted(nodes, key=priority)


def report(nodes: list[dict], state: dict, now: int, current: str) -> str:
    selected = shortlist(nodes, state, current)
    ready = [n for n in selected if is_ready(n, state, now)]
    return '\n'.join((
        f'HOT_POOL_MODE=SHADOW_ONLY',
        f'HOT_POOL_HEALTHY={len(nodes)}',
        f'HOT_POOL_SHORTLIST={len(selected)}',
        f'HOT_POOL_READY={len(ready)}',
        f'HOT_POOL_QUARANTINED_ENDPOINTS={len(state["quarantine"])}',
        f'HOT_POOL_NEXT={ready[0]["name"] if ready else "NONE"}',
        f'HOT_POOL_CURRENT={current or "UNKNOWN"}',
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool', type=Path, default=POOL)
    parser.add_argument('--provider', type=Path, default=PROVIDER)
    parser.add_argument('--state', type=Path, default=STATE)
    parser.add_argument('--current', default='')
    parser.add_argument('--now', type=int, default=0, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    sub.add_parser('warm', help='Two isolated service-scans max; never switches live node')
    p = sub.add_parser('best')
    p.add_argument('--exclude', action='append', default=[])
    p = sub.add_parser('quarantine')
    p.add_argument('name')
    p.add_argument('--reason', choices=('activation-failed', 'active-health-failed'), required=True)
    args = parser.parse_args()
    now = args.now or int(time.time())
    try:
        if not args.current:
            try:
                args.current = CURRENT_FILE.read_text().strip()
            except OSError:
                pass
        region, protocol = pool_policy()
        digest, nodes = load_nodes(args.pool, args.provider, now, region, protocol)
        state = load_state(args.state, digest, now)
        if args.action == 'quarantine':
            affected = failure(state, nodes, args.name, now, args.reason)
            save_state(args.state, state)
            print(f'HOT_POOL_QUARANTINE_MATCHES={affected}')
        elif args.action == 'warm':
            choices = [n for n in shortlist(nodes, state, args.current)
                       if eligible_for_probe(n, state, now)]
            choices = probe_order(choices, state, now)
            for n in choices[:MAX_PROBES]:
                ok, details = scan_one(n['name'])
                record_scan(state, n, ok, int(time.time()) if not args.now else now)
                print(f'HOT_POOL_PROBE={n["name"]} RESULT={"PASS" if ok else "NOT_CONFIRMED"} {details}', flush=True)
                save_state(args.state, state)
            print(report(nodes, state, int(time.time()) if not args.now else now, args.current))
        elif args.action == 'best':
            excluded = set(args.exclude)
            ready = [n for n in shortlist(nodes, state, args.current)
                     if n['name'] not in excluded and is_ready(n, state, now)]
            if not ready:
                return 3
            print(ready[0]['name'])
        else:
            print(report(nodes, state, now, args.current))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print('HOT_POOL_ERROR=' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())