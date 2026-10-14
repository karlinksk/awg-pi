#!/usr/bin/env python3
"""Service-qualified warm reserve for AWG Pi Gateway (SHADOW-ONLY by default).

Uses the existing isolated service-scan for fresh network-level ChatGPT/YouTube
verification. Never touches the live selector, TUN, routing, or MikroTik.
No secrets, URLs, video bytes or raw provider profiles are persisted.
"""
from __future__ import annotations
import argparse
import hashlib
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


def scan_one(name: str) -> bool:
    try:
        outcome = subprocess.run([SCAN, 'service-scan', '--node', name],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, timeout=PROBE_TIMEOUT, check=False)
        if len(outcome.stdout) > 8192 or not outcome.stdout:
            return False
        result = subprocess.run([GATE], input=outcome.stdout, text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=8, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


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
            # Prefer confirmation of one-pass nodes so they become hot sooner.
            choices.sort(key=lambda n: (not bool(state['checks'].get(identity(n), {}).get('passes')),
                                        n['delay_ms']))
            for n in choices[:MAX_PROBES]:
                ok = scan_one(n['name'])
                record_scan(state, n, ok, int(time.time()) if not args.now else now)
                print(f'HOT_POOL_PROBE={n["name"]} RESULT={"PASS" if ok else "NOT_CONFIRMED"}')
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