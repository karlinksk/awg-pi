#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src" / "awg-mihomo-pool.py"


spec = importlib.util.spec_from_file_location("awg_mihomo_pool", CLI)
assert spec is not None and spec.loader is not None
poolmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poolmod)

source_text = CLI.read_text(encoding="utf-8")
for marker in (
    'MIHOMO_POOL_READY=',
    'MIHOMO_POOL_HEALTH_PROGRESS=',
    'MIHOMO_POOL_GEO_PROGRESS=',
):
    lines = [line for line in source_text.splitlines() if marker in line and "print(" in line]
    assert lines, f"missing progress marker print: {marker}"
    assert all("flush=True" in line for line in lines), f"progress marker must flush immediately: {marker}"


class FakeProc:
    stdout = None

    @staticmethod
    def poll():
        return None


print("=== probe waits for complete Mihomo controller inventory ===")
inventory_calls = {"count": 0}


def fake_controller_request(_port, path, **_kwargs):
    assert path == "/proxies"
    inventory_calls["count"] += 1
    if inventory_calls["count"] == 1:
        return {"proxies": {"AWG-PROBE-000001": {}}}
    return {
        "proxies": {
            "AWG-PROBE-000001": {},
            "AWG-PROBE-000002": {},
        }
    }


real_controller_request = poolmod.controller_request
poolmod.controller_request = fake_controller_request
try:
    loaded = poolmod.wait_probe_inventory(
        FakeProc(),
        9090,
        ["AWG-PROBE-000001", "AWG-PROBE-000002"],
        timeout=0.5,
    )
finally:
    poolmod.controller_request = real_controller_request

assert loaded == {"AWG-PROBE-000001", "AWG-PROBE-000002"}
assert inventory_calls["count"] >= 2

print("=== protocol filter scopes provider nodes before probing ===")
sample_nodes = [
    {"name": "A", "type": "vless"},
    {"name": "B", "type": "trojan"},
    {"name": "C", "type": "ss"},
    {"name": "D", "type": "VMESS"},
]
assert [n["name"] for n in poolmod.filter_provider_nodes(sample_nodes, "vless")] == ["A"]
assert [n["name"] for n in poolmod.filter_provider_nodes(sample_nodes, "trojan")] == ["B"]
assert [n["name"] for n in poolmod.filter_provider_nodes(sample_nodes, "ss")] == ["C"]
assert [n["name"] for n in poolmod.filter_provider_nodes(sample_nodes, "vmess")] == ["D"]
assert len(poolmod.filter_provider_nodes(sample_nodes, "all")) == 4

print("=== all-dead scan result preserves previous pool state ===")
with tempfile.TemporaryDirectory() as td:
    preserved = Path(td) / "live.json"
    preserved.write_text('{"known_good":true}\n', encoding="utf-8")
    try:
        poolmod.persist_healthy_pool(preserved, {"healthy": 0})
    except SystemExit as exc:
        assert exc.code == 3
    else:
        raise AssertionError("zero-healthy pool result must return reserved exit code 3")
    assert preserved.read_text(encoding="utf-8") == '{"known_good":true}\n'

    missing = Path(td) / "candidate.json"
    try:
        poolmod.persist_healthy_pool(missing, {"healthy": 0})
    except SystemExit as exc:
        assert exc.code == 3
    else:
        raise AssertionError("zero-healthy initial result must return reserved exit code 3")
    assert not missing.exists()

refresh_unit = (ROOT / "units" / "awg-mihomo-pool-refresh.service").read_text(encoding="utf-8")
assert "SuccessExitStatus=3" in refresh_unit


def run(env, *args, check=True):
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    live_provider = tmp / "live.yaml"
    candidate_provider = tmp / "candidate.yaml"
    pool_dir = tmp / "run"
    policy = tmp / "etc" / "pool-policy.env"
    cooldown = pool_dir / "cooldown.json"
    live_pool = pool_dir / "live.json"
    candidate_pool = pool_dir / "candidate.json"

    provider_text = """proxies:
  - name: Finland VLESS
    type: vless
    server: 198.51.100.10
    port: 443
  - name: Japan Trojan
    type: trojan
    server: 198.51.100.20
    port: 443
  - name: Dead Node
    type: vless
    server: 198.51.100.30
    port: 443
"""
    live_provider.write_text(provider_text, encoding="utf-8")
    candidate_provider.write_text(provider_text, encoding="utf-8")
    digest = hashlib.sha256(provider_text.encode()).hexdigest()
    now = int(time.time())
    payload = {
        "version": 1,
        "target": "live",
        "provider_sha256": digest,
        "scanned_at": now,
        "geo_enriched": True,
        "protocol_filter": "all",
        "source_total": 3,
        "total": 3,
        "healthy": 2,
        "europe": 1,
        "nodes": [
            {
                "index": 1,
                "name": "Finland VLESS",
                "type": "vless",
                "server": "198.51.100.10",
                "port": 443,
                "healthy": True,
                "delay_ms": 54,
                "egress_ip": "203.0.113.10",
                "country_code": "FI",
                "europe": True,
                "geo_checked": True,
                "error": "",
            },
            {
                "index": 2,
                "name": "Japan Trojan",
                "type": "trojan",
                "server": "198.51.100.20",
                "port": 443,
                "healthy": True,
                "delay_ms": 31,
                "egress_ip": "203.0.113.20",
                "country_code": "JP",
                "europe": False,
                "geo_checked": True,
                "error": "",
            },
            {
                "index": 3,
                "name": "Dead Node",
                "type": "vless",
                "server": "198.51.100.30",
                "port": 443,
                "healthy": False,
                "delay_ms": None,
                "egress_ip": "",
                "country_code": "",
                "europe": False,
                "geo_checked": False,
                "error": "TimeoutError",
            },
        ],
    }
    pool_dir.mkdir(parents=True)
    live_pool.write_text(json.dumps(payload), encoding="utf-8")
    candidate_payload = dict(payload)
    candidate_payload["target"] = "candidate"
    candidate_pool.write_text(json.dumps(candidate_payload), encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "MIHOMO_PROVIDER_FILE": str(live_provider),
            "MIHOMO_CANDIDATE_FILE": str(candidate_provider),
            "MIHOMO_POOL_DIR": str(pool_dir),
            "MIHOMO_LIVE_POOL_FILE": str(live_pool),
            "MIHOMO_CANDIDATE_POOL_FILE": str(candidate_pool),
            "MIHOMO_POOL_POLICY_FILE": str(policy),
            "MIHOMO_POOL_COOLDOWN_FILE": str(cooldown),
        }
    )

    print("=== protocol policy defaults to all and survives region changes ===")
    assert run(env, "protocol", "get").stdout.strip() == "all"
    run(env, "protocol", "set", "vless")
    assert run(env, "protocol", "get").stdout.strip() == "vless"
    run(env, "policy", "set", "europe")
    assert run(env, "protocol", "get").stdout.strip() == "vless"
    status = run(env, "policy", "status").stdout
    assert "MIHOMO_POOL_PROTOCOL=vless" in status

    print("=== protocol changes invalidate a pool scanned for another protocol ===")
    stale = run(env, "list", "live", check=False)
    assert stale.returncode != 0
    assert "missing or stale" in stale.stderr

    run(env, "protocol", "set", "all")
    run(env, "policy", "set", "all")

    print("=== default list: healthy nodes from any country ===")
    out = run(env, "list", "live").stdout
    assert "Finland VLESS" in out
    assert "Japan Trojan" in out
    assert "Dead Node" not in out

    print("=== Europe policy filters by actual egress country ===")
    run(env, "policy", "set", "europe")
    assert run(env, "policy", "get").stdout.strip() == "europe"
    out = run(env, "list", "live").stdout
    assert "Finland VLESS" in out
    assert "Japan Trojan" not in out

    print("=== a protocol-scoped pool exposes only that protocol ===")
    run(env, "policy", "set", "all")
    run(env, "protocol", "set", "trojan")
    trojan_payload = dict(payload)
    trojan_payload["protocol_filter"] = "trojan"
    trojan_payload["total"] = 1
    trojan_payload["healthy"] = 1
    trojan_payload["europe"] = 0
    trojan_payload["nodes"] = [payload["nodes"][1]]
    live_pool.write_text(json.dumps(trojan_payload), encoding="utf-8")
    out = run(env, "list", "live").stdout
    assert "Japan Trojan" in out
    assert "Finland VLESS" not in out
    assert run(env, "best", "live").stdout.strip() == "Japan Trojan"

    run(env, "protocol", "set", "all")
    live_pool.write_text(json.dumps(payload), encoding="utf-8")

    print("=== search is case-insensitive across metadata ===")
    run(env, "policy", "set", "all")
    out = run(env, "list", "live", "--query", "troJAN").stdout
    assert "Japan Trojan" in out
    assert "Finland VLESS" not in out
    out = run(env, "list", "live", "--query", "198.51.100.10").stdout
    assert "Finland VLESS" in out

    print("=== all-results mode includes dead nodes ===")
    out = run(env, "list", "live", "--all", "--ignore-policy").stdout
    assert "Dead Node" in out
    assert "DEAD" in out

    print("=== best chooses lowest-latency healthy node ===")
    assert run(env, "best", "live").stdout.strip() == "Japan Trojan"

    print("=== cooldown excludes failed nodes ===")
    run(env, "cooldown", "add", "Japan Trojan", "--seconds", "300")
    assert run(env, "best", "live").stdout.strip() == "Finland VLESS"

    print("=== Europe policy plus cooldown can exhaust the pool ===")
    run(env, "policy", "set", "europe")
    run(env, "cooldown", "add", "Finland VLESS", "--seconds", "300")
    exhausted = run(env, "best", "live", check=False)
    assert exhausted.returncode != 0
    assert "No healthy Mihomo node" in exhausted.stderr

    print("=== candidate pool can be promoted without rewriting provider state ===")
    run(env, "cooldown", "clear")
    run(env, "promote")
    promoted = json.loads(live_pool.read_text(encoding="utf-8"))
    assert promoted["target"] == "live"
    assert not candidate_pool.exists()

    print("mihomo health-pool policy/list tests: OK")
