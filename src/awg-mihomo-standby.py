#!/usr/bin/env python3
"""Read-only rolling Mihomo Hot Standby scanner for AWG Pi Gateway.

One isolated loopback Mihomo (no TUN) per scan. ONLY publishes a RAM state
file: it never selects a live node, starts/stops production services or edits
VPN routing. The production selector must verify cache freshness AND recheck
the actual data plane before committing to a warm candidate.
"""
from __future__ import annotations

import argparse
import collections
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

SMART_PY = Path(__file__).with_name("awg-mihomo-smart")
SERVICE_PY = Path(__file__).with_name("awg-mihomo-service-check.py")
STATE_DIR = Path("/run/awg-pbr/mihomo-standby")
STATE_FILE = STATE_DIR / "state.json"
POOL_JSON = Path("/run/awg-pbr/mihomo-pool/live.json")
PROVIDER = Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
MIHOMO = "/usr/local/bin/mihomo"
SCRATCH_DIR = "/dev/shm"
CACHE_TTL = 180
MAX_RUN_SECONDS = 120
MAX_POOL_AGE = 3600


def load_module(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


LIMITS = load_module(Path(__file__).with_name("awg-mihomo-limits.py"),
                     "awg_standby_shared_limits")


def fingerprint(node: dict) -> str:
    """Cache key changes with node identity, endpoint and protocol."""
    parts = (node["name"], node["type"], node["server"], str(node["port"]),
             str(node.get("egress_ip") or ""), str(node.get("country_code") or ""))
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def fresh_entry(entry: dict, node: dict, now: int, ttl: int = CACHE_TTL) -> bool:
    if not isinstance(entry, dict) or not isinstance(entry.get("checked_at"), int):
        return False
    age = now - entry["checked_at"]
    return (0 <= age <= ttl
            and entry.get("fingerprint") == fingerprint(node)
            and entry.get("status") in ("PASS", "FAIL", "UNKNOWN"))


def adaptive_interval(healthy_spares: int, error_streak: int,
                      *, stable: int = 120, degraded: int = 30,
                      max_backoff: int = 600) -> int:
    """Lightweight scan interval; failure storm increases backoff, not load."""
    if error_streak:
        return min(max_backoff, degraded * (2 ** min(error_streak - 1, 5)))
    return stable if healthy_spares >= 2 else degraded


def choose_window(nodes: list[dict], cursor: int, limit: int,
                  pinned: list[str] | None = None) -> tuple[list[dict], int]:
    """Scan rolling candidate windows; retain validated warm spares in front."""
    if limit < 1:
        raise ValueError("invalid candidate cap")
    if not nodes:
        return [], 0
    by_name = collections.Counter(node["name"] for node in nodes)
    unique = [node for node in nodes if by_name[node["name"]] == 1]
    if not unique:
        return [], 0
    selected = []
    seen = set()
    for name in (pinned or []):
        for node in unique:
            if node["name"] == name and len(selected) < limit:
                selected.append(node)
                seen.add(name)
                break
    # Cursor walks across eligible nodes, not merely the first ten.
    offset = cursor % len(unique)
    for node in unique[offset:] + unique[:offset]:
        if len(selected) >= limit:
            break
        if node["name"] not in seen:
            selected.append(node)
            seen.add(node["name"])
    # Always advance by at least the number of freshly surveyed slots.
    increment = max(1, limit - min(len(pinned or []), limit))
    return selected, (offset + increment) % len(unique)


def qualified_spares(entries: dict, nodes: list[dict], now: int,
                     ttl: int = CACHE_TTL, limit: int = 2) -> list[str]:
    """Only recent independently PASS-qualified unique endpoints are warm."""
    by_name = collections.Counter(n["name"] for n in nodes)
    eligible = [n for n in nodes if by_name[n["name"]] == 1
                and n["name"] in entries
                and fresh_entry(entries[n["name"]], n, now, ttl)
                and entries[n["name"]]["status"] == "PASS"]
    eligible.sort(key=lambda n: (n["delay_ms"], n["name"]))
    selected, endpoints = [], set()
    for node in eligible:
        endpoint = (node["server"], node["port"])
        if endpoint in endpoints:
            continue
        selected.append(node["name"])
        endpoints.add(endpoint)
        if len(selected) >= limit:
            break
    return selected


def read_state(path: Path, source_sha: str, region: str,
               protocol: str) -> dict:
    try:
        result = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if (not isinstance(result, dict)
            or result.get("version") != 1
            or result.get("provider_sha256") != source_sha
            or result.get("region") != region
            or result.get("protocol") != protocol):
        return {}
    return result


def atomic_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".standby-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"), ensure_ascii=False)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def next_interval(entries: dict, warm: list[str], now: int,
                  ttl: int, error_streak: int) -> int:
    """Recheck warm nodes before they expire, even after a long full scan."""
    base = adaptive_interval(len(warm), error_streak)
    if not warm:
        return base
    remaining = []
    for name in warm:
        row = entries.get(name, {})
        if isinstance(row.get("checked_at"), int):
            remaining.append(ttl - max(0, now - row["checked_at"]))
    if not remaining:
        return 5
    return max(5, min(base, min(remaining) - 15))


def build_plan(smart, pool: dict, raw_provider: list[dict], *,
               previous: dict, region: str, protocol: str, cooldown: dict,
               count: int, now: int) -> tuple[list[dict], list[dict], int, list[str]]:
    nodes = smart.eligible(pool, region=region, protocol=protocol, cooldown=cooldown)
    # A pool can contain duplicate names; the production selector cannot use them.
    counts = collections.Counter(n["name"] for n in raw_provider
                                 if isinstance(n, dict) and isinstance(n.get("name"), str))
    nodes = [n for n in nodes if counts[n["name"]] == 1]
    entries = previous.get("entries", {}) if isinstance(previous.get("entries"), dict) else {}
    warm = qualified_spares(entries, nodes, now)
    chosen, cursor = choose_window(nodes, int(previous.get("cursor", 0)), count, warm)
    return chosen, nodes, cursor, warm


def probe_candidates(chosen: list[dict], raw_provider: list[dict],
                     pool_helper, service, *, timeout: float,
                     deadline: float) -> dict:
    """Isolated Mihomo with a single loopback proxy, strictly sequential selection."""
    import yaml
    by_name = {n["name"]: n for n in raw_provider if isinstance(n, dict)
               and isinstance(n.get("name"), str)}
    mixed_port = pool_helper.choose_free_port()
    controller_port = pool_helper.choose_free_port()
    while controller_port == mixed_port:
        controller_port = pool_helper.choose_free_port()
    with tempfile.TemporaryDirectory(prefix="awg-hot-standby-", dir=SCRATCH_DIR) as directory:
        conf, prepared = pool_helper.make_probe_config(
            [by_name[n["name"]] for n in chosen], mixed_port, controller_port)
        path = Path(directory) / "config.yaml"
        path.write_text(yaml.safe_dump(conf, allow_unicode=True, sort_keys=False), "utf-8")
        path.chmod(0o600)
        proc = subprocess.Popen([MIHOMO, "-d", directory, "-f", str(path)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            pool_helper.wait_controller(proc, controller_port, timeout=8)
            inventory = pool_helper.wait_probe_inventory(
                proc, controller_port, [n["probe_name"] for n in prepared], timeout=8)
            lookup = dict(zip((n["name"] for n in chosen), prepared))
            outcomes = {}
            for candidate in chosen:
                if time.monotonic() >= deadline:
                    break
                name = candidate["name"]
                try:
                    if lookup[name]["probe_name"] not in inventory:
                        outcomes[name] = {"status": "UNKNOWN", "reason": "probe_not_loaded"}
                        continue
                    pool_helper.select_probe(controller_port, lookup[name]["probe_name"])
                    result = service.assess(lambda url, **kwargs: service.fetch(
                        mixed_port, url, timeout=timeout, **kwargs))
                    # Never publish raw video URLs, provider credentials or HTTP body.
                    outcomes[name] = {
                        "status": result["status"],
                        "transport": "mihomo",
                        "identity": name,
                        "sample_id": uuid.uuid4().hex,
                        "checks": {key: {"state": item["state"], "reason": item["reason"]}
                                   for key, item in result["checks"].items()}
                    }
                except Exception as exc:
                    outcomes[name] = {"status": "UNKNOWN",
                                      "reason": "probe_" + type(exc).__name__}
            return outcomes
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)


def scan(*, pool_file: Path = POOL_JSON, provider_file: Path = PROVIDER,
         state_file: Path = STATE_FILE, count: int = LIMITS.CANDIDATES,
         confirm_limit: int = LIMITS.CONFIRMED, ttl: int = CACHE_TTL,
         max_seconds: int = MAX_RUN_SECONDS, timeout: float = 4.0,
         perform_probe=probe_candidates) -> dict:
    if os.geteuid() != 0:
        raise RuntimeError("root needed for protected provider credentials")
    if not Path(SCRATCH_DIR).is_dir():
        raise RuntimeError("RAM scratch directory missing")
    smart = load_module(SMART_PY, "awg_hot_smart")
    helper = smart.load_pool_code()
    service = smart.load_service_code()
    state_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state_file.parent / "lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pool = json.loads(pool_file.read_text("utf-8"))
        if not smart.fresh_pool(pool, provider_file, MAX_POOL_AGE):
            raise RuntimeError("stale or mismatched Mihomo health pool")
        region, protocol = helper.read_policy_values()
        if region == "europe" and not pool.get("geo_enriched"):
            raise RuntimeError("Europe-only pool lacks verified geography")
        source_sha = pool["provider_sha256"]
        now = int(time.time())
        previous = read_state(state_file, source_sha, region, protocol)
        raw = helper.read_provider(provider_file)
        chosen, eligible, cursor, warm = build_plan(
            smart, pool, raw, previous=previous,
            region=region, protocol=protocol, cooldown=helper.load_cooldown(),
            count=count, now=now)
        by_name = {n["name"]: n for n in eligible}
        # Bound the cache size, age and provider endpoint identity in RAM.
        entries = {name: row for name, row in previous.get("entries", {}).items()
                   if name in by_name and fresh_entry(row, by_name[name], now, ttl)}
        deadline = time.monotonic() + max_seconds
        outcomes = (perform_probe(chosen, raw, helper, service, timeout=timeout,
                                  deadline=deadline) if chosen else {})
        for node in chosen:
            name = node["name"]
            if name not in outcomes:
                continue
            outcome = outcomes[name]
            entries[name] = {
                "status": outcome["status"],
                "reason_codes": outcome.get("reasons", {"probe": outcome.get("reason", "unknown")}),
                "fingerprint": fingerprint(node),
                "checked_at": int(time.time()),
                "delay_ms": node["delay_ms"],
                "transport": outcome.get("transport"),
                "identity": outcome.get("identity"),
                "sample_id": outcome.get("sample_id"),
                "checks": outcome.get("checks", {}),
            }
        now = int(time.time())
        warm = qualified_spares(entries, eligible, now, ttl, confirm_limit)
        # No provider URLs, endpoints or credentials go in the summary.
        previous_streak = int(previous.get("error_streak", 0))
        streak = 0 if warm else min(8, previous_streak + 1)
        result = {"version": 1, "mode": "SHADOW_ONLY",
                  "provider_sha256": source_sha, "region": region, "protocol": protocol,
                  "generated_at": now, "ttl_seconds": ttl,
                  "pool_scanned_at": pool["scanned_at"],
                  "cursor": cursor, "candidate_cap": count,
                  "tested": len(outcomes), "considered": len(chosen),
                  "warm": warm, "entries": entries,
                  "error_streak": streak,
                  "suggested_interval_seconds": next_interval(entries, warm, now, ttl, streak)}
        atomic_state(state_file, result)
        return result


def report(state: dict) -> dict:
    """Status without secrets; expired results never advertised as usable."""
    summary = {key: state.get(key) for key in
               ("mode", "generated_at", "candidate_cap", "considered", "tested",
                "suggested_interval_seconds", "error_streak")}
    now = int(time.time())
    ttl = int(state.get("ttl_seconds", CACHE_TTL))
    entries = state.get("entries", {}) if isinstance(state.get("entries"), dict) else {}
    warm = []
    for name in state.get("warm", []):
        value = entries.get(name)
        if (isinstance(value, dict) and value.get("status") == "PASS"
                and isinstance(value.get("checked_at"), int)
                and 0 <= now - value["checked_at"] <= ttl):
            warm.append(name)
    if not isinstance(state.get("generated_at"), int) or now - state["generated_at"] > ttl:
        warm = []
        summary["status"] = "STALE"
    else:
        summary["status"] = "READY" if len(warm) >= 2 else ("DEGRADED" if warm else "EMPTY")
    summary["warm"] = warm
    return summary


def watch(*, scanner=scan, sleeper=time.sleep, max_cycles: int | None = None,
          **scan_args) -> None:
    """Continuous low-duty-cycle worker, independent of the production Mihomo."""
    error_streak = 0
    completed = 0
    while max_cycles is None or completed < max_cycles:
        try:
            state = scanner(**scan_args)
            delay = int(state["suggested_interval_seconds"])
            error_streak = 0
            print(json.dumps(report(state), ensure_ascii=False), flush=True)
        except (OSError, RuntimeError, ValueError, BlockingIOError) as exc:
            # A missing/stale pool or temporary probe failure must not restart
            # production services, trigger a failover or hammer upstream.
            error_streak = min(error_streak + 1, 8)
            delay = adaptive_interval(0, error_streak)
            print("HOT_STANDBY_SCAN_ERROR=" + type(exc).__name__, file=sys.stderr,
                  flush=True)
        completed += 1
        if max_cycles is not None and completed >= max_cycles:
            break
        sleeper(delay)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scan", "show", "watch"))
    parser.add_argument("--count", type=int, default=LIMITS.CANDIDATES)
    parser.add_argument("--ttl", type=int, default=CACHE_TTL)
    parser.add_argument("--max-seconds", type=int, default=MAX_RUN_SECONDS)
    parser.add_argument("--timeout", type=float, default=4.0)
    args = parser.parse_args()
    if not (1 <= args.count <= LIMITS.CANDIDATES and 30 <= args.ttl <= 600
            and 10 <= args.max_seconds <= 180 and 1 <= args.timeout <= 10):
        parser.error("limits exceeded")
    if args.command == "show":
        try:
            state = json.loads(STATE_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            print('{"status":"NO_STANDBY_STATE"}')
            return 1
        print(json.dumps(report(state), ensure_ascii=False))
        return 0
    options = dict(count=args.count, ttl=args.ttl,
                   max_seconds=args.max_seconds, timeout=args.timeout)
    if args.command == "watch":
        watch(**options)
        return 0
    state = scan(**options)
    print(json.dumps(report(state), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, BlockingIOError) as exc:
        print("HOT_STANDBY_ERROR=" + type(exc).__name__ + ":" + str(exc)[:90],
              file=sys.stderr)
        raise SystemExit(2)
