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
SCAN = os.environ.get('AWG_HOT_POOL_SCANNER', '/usr/local/sbin/awg-mihomo-hot-service-scan')
GATE = os.environ.get('AWG_HOT_POOL_GATE', '/usr/local/sbin/awg-mihomo-network-eligibility.py')
POLICY = Path(os.environ.get('MIHOMO_POOL_POLICY_FILE', '/etc/awg-pbr/transports/mihomo/pool-policy.env'))
PASS_MIN_INTERVAL = 600
READY_MAX_AGE = 3600
READY_REFRESH_LEAD = 1500  # refresh before the oldest of two proofs expires
POOL_MAX_AGE = 7200
RETRY_FAILED = 1200
RETRY_SUSPECT = 600  # not before 10 min after a transient unknown
QUARANTINE_SECS = 7200
MAX_PROBES = 2
TARGET_READY = 4
# Next timer event: 12 min after completion, 1 min timer slack, plus
# bounded sequential diagnostic probes. Be conservative about expiry.
NEXT_PROBE_SAFETY = 1260
CURRENT_FILE = Path('/etc/awg-pbr/transports/mihomo/node-name')
PROBE_TIMEOUT = 125  # 10s controller + <=22s readiness + service video + cleanup


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
        if record.get('last_result') not in ('PASS', 'FAIL', 'SUSPECT'):
            continue
        clean[key] = {'passes': stamps[-2:], 'last_result': record['last_result'],
                      'last_checked': last_checked}
        if record['last_result'] == 'SUSPECT' and not stamps:
            clean[key]['last_result'] = 'FAIL'
        samples = record.get('connect_samples_ms', [])
        if isinstance(samples, list):
            clean[key]['connect_samples_ms'] = [
                v for v in samples[-12:] if type(v) is int and 0 <= v <= 120000]
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


def proof_rank(node: dict, state: dict, now: int) -> int:
    # Only live, policy-conforming nodes supplied by load_nodes are considered.
    # A formerly READY but expired node is NEVER treated as READY.
    if is_ready(node, state, now):
        return 0
    check = state['checks'].get(identity(node), {})
    passes = check.get('passes', [])
    if (check.get('last_result') in ('PASS', 'SUSPECT') and isinstance(passes, list)
            and passes and type(passes[-1]) is int
            and 0 <= now - passes[-1] <= READY_MAX_AGE):
        return 1
    return 2


def shortlist(nodes: list[dict], state: dict, current: str,
              max_endpoints=12, *, now: int | None = None) -> list[dict]:
    """Retain fresh READY/one-pass nodes, then best-latency candidates.

    One *endpoint* per shortlist even when names/credentials differ; preserve
    the existing 4-per-protocol and total size limits. An alias of the active
    endpoint cannot become its own reserve.
    """
    if now is None:
        now = int(time.time())
    active_endpoints = {endpoint(n) for n in nodes if n['name'] == current}
    candidates = [n for n in nodes if n['name'] != current
                  and endpoint(n) not in active_endpoints
                  and endpoint(n) not in state['quarantine']]
    # Sorting before dedupe means a proven alias wins over an unproven,
    # lower-latency alias sharing the same actual host:port.
    candidates.sort(key=lambda n: (proof_rank(n, state, now),
                                   n['delay_ms'], n.get('index', 999999)))
    selected, seen, count = [], set(), {}
    for node in candidates:
        ep = endpoint(node)
        proto = str(node['type']).lower()
        if ep in seen or count.get(proto, 0) >= 4:
            continue
        selected.append(node)
        seen.add(ep)
        count[proto] = count.get(proto, 0) + 1
        if len(selected) >= max_endpoints:
            break
    return selected


def needs_ready_refresh(node: dict, state: dict, now: int) -> bool:
    """Revalidate a proven READY early enough to preserve two fresh passes."""
    if not is_ready(node, state, now):
        return False
    passes = state['checks'][identity(node)]['passes']
    return (now - passes[0] >= READY_MAX_AGE - READY_REFRESH_LEAD
            and now - passes[-1] >= PASS_MIN_INTERVAL)


def eligible_for_probe(node: dict, state: dict, now: int) -> bool:
    record = state['checks'].get(identity(node), {})
    raw_last = record.get('last_checked', 0)
    last = raw_last if type(raw_last) is int else 0
    if record.get('last_result') == 'FAIL' and now - last < RETRY_FAILED:
        return False
    if record.get('last_result') == 'SUSPECT' and now - last < RETRY_SUSPECT:
        return False
    if record.get('last_result') == 'PASS':
        if is_ready(node, state, now):
            return needs_ready_refresh(node, state, now)
        passes = record.get('passes', [])
        if passes and type(passes[-1]) is int and 0 <= now - passes[-1] < PASS_MIN_INTERVAL:
            return False
    return True


def record_scan(state: dict, node: dict, passed: bool, now: int,
                connect_ms: int | None = None) -> None:
    """Preserve evidence on one transient unknown but never select SUSPECT.

    A second consecutive failed qualification discards proofs. Two fresh,
    spaced PASSes are always required for READY, including after recovery.
    """
    key = identity(node)
    old = state['checks'].get(key, {})
    previous = old.get('last_result')
    passes = old.get('passes', []) if previous in ('PASS', 'SUSPECT') else []
    passes = [x for x in passes if type(x) is int and 0 <= now - x <= READY_MAX_AGE]
    if passed:
        if not passes or now - passes[-1] >= PASS_MIN_INTERVAL:
            passes = (passes + [now])[-2:]
        result = 'PASS'
    elif passes and previous == 'PASS':
        result = 'SUSPECT'
        # Do not allow a bad or inconclusive check to authorize a live failover.
    else:
        result = 'FAIL'
        passes = []
    raw_samples = old.get('connect_samples_ms', [])
    samples = [v for v in raw_samples[-12:] if type(v) is int and 0 <= v <= 120000] if isinstance(raw_samples, list) else []
    if type(connect_ms) is int and 0 <= connect_ms <= 120000:
        samples = (samples + [connect_ms])[-12:]
    state['checks'][key] = {
        'passes': passes, 'last_result': result,
        'last_checked': now, 'connect_samples_ms': samples,
    }


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
        outcome = subprocess.run([SCAN, '--node', name],
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
                   'SERVICE_CHECK_YOUTUBE_VIDEO', 'SERVICE_REASON_CHATGPT_WEB',
                   'SERVICE_REASON_YOUTUBE_VIDEO', 'SERVICE_CONNECT_STATE',
                   'SERVICE_COLD_READY_MS', 'SERVICE_CONTROLLER_READY_MS',
                   'SERVICE_CONNECT_WAIT_MS', 'SERVICE_CONNECT_ATTEMPTS',
                   'SERVICE_CONNECT_FAMILY'}
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
                   ' VIDEO_REASON=' + status('SERVICE_REASON_YOUTUBE_VIDEO') +
                   ' CONNECT=' + status('SERVICE_CONNECT_STATE') +
                   ' COLD_MS=' + status('SERVICE_COLD_READY_MS') +
                   ' CONTROLLER_MS=' + status('SERVICE_CONTROLLER_READY_MS') +
                   ' WAIT_MS=' + status('SERVICE_CONNECT_WAIT_MS') +
                   ' ATTEMPTS=' + status('SERVICE_CONNECT_ATTEMPTS') +
                   ' CONNECT_FAMILY=' + status('SERVICE_CONNECT_FAMILY') +
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
        if is_ready(node, state, now):
            return (-1, 0, node['delay_ms'])  # due for proactive READY renewal
        if not record:
            return (1, 0, node['delay_ms'])
        passes = record.get('passes', [])
        if record.get('last_result') == 'PASS' and passes:
            return (0, int(record.get('last_checked', 0)), node['delay_ms'])
        # Failed candidates are still eligible after retry cooldown, but last.
        return (2, int(record.get('last_checked', 0)), node['delay_ms'])
    return sorted(nodes, key=priority)


def discovery_priority(node: dict, state: dict, now: int,
                       ready_protocols: dict[str, int]) -> tuple[int, int, int, int]:
    """Prefer missing transports while giving previous PASS a fast second test.

    Soft diversity target: 2 VLESS, 1 Shadowsocks and 1 Trojan/Hysteria2.
    This never excludes another available protocol or a healthy node.
    """
    protocol = str(node['type']).lower()
    vless = ready_protocols.get('vless', 0)
    ss = ready_protocols.get('ss', 0)
    alternate = ready_protocols.get('trojan', 0) + ready_protocols.get('hysteria2', 0)
    if protocol == 'vless':
        diversity = 0 if vless < 2 else 2
    elif protocol == 'ss':
        diversity = 0 if ss == 0 else 2
    elif protocol in ('trojan', 'hysteria2'):
        diversity = 0 if alternate == 0 else 2
    else:
        diversity = 1 if ready_protocols.get(protocol, 0) == 0 else 2
    record = state['checks'].get(identity(node), {})
    passes = record.get('passes', [])
    phase = 0 if record.get('last_result') in ('PASS', 'SUSPECT') and passes else (
        1 if not record else 2)
    return (diversity, phase, int(record.get('last_checked', 0)), node['delay_ms'])


def select_probes(nodes: list[dict], state: dict, now: int) -> list[tuple[str, dict]]:
    """Maintenance and discovery lanes; always <=2 isolated checks per cycle.

    Prioritize due-to-expire READY proofs so growth cannot invalidate the
    reserve. Otherwise devote at least one slot to finding a new independent
    endpoint until the four-READY target has been reached.
    """
    ready = [n for n in nodes if is_ready(n, state, now)]
    ready.sort(key=lambda n: (state['checks'][identity(n)]['passes'][0],
                              n['delay_ms'], n.get('index', 999999)))
    # Do not spend the tiny scan budget maintaining more than our target.
    maintained = ready[:TARGET_READY]
    due = [n for n in maintained if eligible_for_probe(n, state, now)]
    due.sort(key=lambda n: state['checks'][identity(n)]['passes'][0])

    ready_counts: dict[str, int] = {}
    for n in maintained:
        protocol = str(n['type']).lower()
        ready_counts[protocol] = ready_counts.get(protocol, 0) + 1
    discovering = len(ready) < TARGET_READY
    recover = [n for n in nodes if
               state['checks'].get(identity(n), {}).get('last_result') == 'SUSPECT'
               and eligible_for_probe(n, state, now)] if discovering else []
    recover.sort(key=lambda n: (state['checks'][identity(n)]['last_checked'],
                                n['delay_ms']))
    explore = [n for n in nodes if not is_ready(n, state, now)
               and state['checks'].get(identity(n), {}).get('last_result') != 'SUSPECT'
               and eligible_for_probe(n, state, now)] if discovering else []
    explore.sort(key=lambda n: discovery_priority(n, state, now, ready_counts))

    plan: list[tuple[str, dict]] = []
    # Deadline-protect any READY whose oldest proof might expire before our
    # next scheduled scan (including timer jitter and bounded scan duration).
    urgent = [n for n in due if
              state['checks'][identity(n)]['passes'][0] + READY_MAX_AGE - now
              <= NEXT_PROBE_SAFETY]
    for n in urgent[:MAX_PROBES]:
        plan.append(('RENEW', n))
    due = [n for n in due if n not in urgent]

    # A suspect is never selectable but deserves an early retry before proofs
    # expire. Reserve one slot for recovery; allow growth in remaining slots.
    if recover and len(plan) < MAX_PROBES:
        plan.append(('RECOVER', recover.pop(0)))
    # A non-urgent renewal has a safe cycle of slack. Discover instead.
    while discovering and explore and len(plan) < MAX_PROBES:
        plan.append(('DISCOVER', explore.pop(0)))
    while due and len(plan) < MAX_PROBES:
        plan.append(('RENEW', due.pop(0)))
    return plan


def report(nodes: list[dict], state: dict, now: int, current: str) -> str:
    selected = shortlist(nodes, state, current, now=now)
    ready = [n for n in selected if is_ready(n, state, now)]
    return '\n'.join((
        f'HOT_POOL_MODE=SHADOW_ONLY',
        f'HOT_POOL_HEALTHY={len(nodes)}',
        f'HOT_POOL_SHORTLIST={len(selected)}',
        f'HOT_POOL_READY={len(ready)}',
        f'HOT_POOL_SUSPECT={sum(state["checks"].get(identity(n), {}).get("last_result") == "SUSPECT" for n in selected)}',
        f'HOT_POOL_TARGET_READY={TARGET_READY}',
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
            selected = shortlist(nodes, state, args.current, now=now)
            plan = select_probes(selected, state, now)
            print(f'HOT_POOL_PLAN_RENEW={sum(mode == "RENEW" for mode, _ in plan)}',
                  flush=True)
            print(f'HOT_POOL_PLAN_DISCOVER={sum(mode == "DISCOVER" for mode, _ in plan)}',
                  flush=True)
            print(f'HOT_POOL_PLAN_RECOVER={sum(mode == "RECOVER" for mode, _ in plan)}',
                  flush=True)
            for mode, n in plan:
                ok, details = scan_one(n['name'])
                metric = re.search(r'(?:^| )COLD_MS=([0-9]{1,6})(?: |$)', details)
                elapsed = int(metric.group(1)) if metric else None
                record_scan(state, n, ok, int(time.time()) if not args.now else now,
                            connect_ms=elapsed)
                verdict = 'PASS' if ok else 'NOT_CONFIRMED'
                status = state['checks'][identity(n)]['last_result']
                print(f'HOT_POOL_PROBE={n["name"]} RESULT={verdict} STATE={status} PROTOCOL={n["type"]} {details}', flush=True)
                save_state(args.state, state)
            print(report(nodes, state, int(time.time()) if not args.now else now, args.current))
        elif args.action == 'best':
            excluded = set(args.exclude)
            ready = [n for n in shortlist(nodes, state, args.current, now=now)
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