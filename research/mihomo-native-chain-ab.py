#!/usr/bin/env python3
"""Isolated Mihomo proxy health A/B: direct vs foreign SOCKS dialer-proxy.

No TUN, no routing/firewall/service changes. Root-only temp config on /run.
Samples 20 existing TCP endpoints, keeping protocol configs identical except
one copy has dialer-proxy pointing to existing local Mihomo SOCKS5 listener.
Never print secrets, endpoints, names or raw error bodies.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import yaml

SOURCE = Path(__file__).with_name("mihomo-endpoint-reprobe.py")
sp = importlib.util.spec_from_file_location("mihomo_reprobe_base", SOURCE)
base = importlib.util.module_from_spec(sp)
sp.loader.exec_module(base)

TARGET = "https://www.gstatic.com/generate_204"
CONTROL = "https://www.cloudflare.com/cdn-cgi/trace"
TIMEOUT = 10000
WORKERS = 5


def health(port: int, name: str, url: str = TARGET):
    encoded = urllib.parse.quote(name, safe="")
    query = urllib.parse.urlencode({"url": url, "timeout": TIMEOUT})
    try:
        payload = base.controller_request(port, f"/proxies/{encoded}/delay?{query}", timeout=13)
        delay = payload.get("delay")
        return "ok" if isinstance(delay, int) and delay > 0 else "no_delay"
    except urllib.error.HTTPError as exc:
        return f"api_{exc.code}"
    except Exception:
        return "api_exception"


def run_one(port: int, entry: dict):
    direct = health(port, entry["direct"])
    relay = health(port, entry["relay"])
    # Only follow up recovery/controls, not unsuccessful profiles.
    confirm_direct = health(port, entry["direct"], CONTROL) if direct == "ok" else "not_tested"
    confirm_relay = health(port, entry["relay"], CONTROL) if relay == "ok" else "not_tested"
    return {"kind": entry["kind"], "baseline": entry["baseline"],
            "direct": direct, "relay": relay,
            "direct_confirm": confirm_direct, "relay_confirm": confirm_relay}


def main():
    if base.os.geteuid() != 0:
        base.fail("root_required")
    source, nodes, pool = base.load_matching()
    selected = [x for x in base.choose(source, nodes) if x["kind"] != "hysteria2"]
    if len(selected) != 20:
        base.fail("unexpected_sample")
    if subprocess.run(["systemctl", "is-active", "--quiet", "awg-mihomo.service"]).returncode:
        base.fail("production_mihomo_not_active")
    # External egress check already done by preceding two-vantage test.
    # Explicitly ensure local SOCKS proxy is still listening.
    try:
        with socket.create_connection(("127.0.0.1", 7890), timeout=2):
            pass
    except OSError:
        base.fail("local_mihomo_socks_unavailable")
    pf = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        fs = {ex.submit(base.endpoint_preflight, item): index for index, item in enumerate(selected)}
        for f in as_completed(fs):
            pf[fs[f]] = f.result()[0]
    if any(value != "pi_direct_only" for value in pf.values()):
        base.fail("direct_route_preflight_failed")
    test_entries = []
    proxies = [{
        "name": "AWG-AUDIT-UPSTREAM",
        "type": "socks5",
        "server": "127.0.0.1",
        "port": 7890,
        "udp": False,
    }]
    for i, item in enumerate(selected):
        a, b = f"AWG-AUDIT-D{i:03}", f"AWG-AUDIT-F{i:03}"
        direct = copy.deepcopy(item["raw"])
        direct["name"] = a
        relay = copy.deepcopy(item["raw"])
        relay["name"] = b
        if relay.get("dialer-proxy"):
            base.fail("existing_dialer_proxy_in_sample")
        relay["dialer-proxy"] = "AWG-AUDIT-UPSTREAM"
        proxies += [direct, relay]
        test_entries.append({"direct": a, "relay": b,
                             "kind": item["kind"], "baseline": item["baseline"]})
    ctrl_port = base.free_port()
    with tempfile.TemporaryDirectory(prefix="awg-dpi-ab-", dir="/run") as temporary:
        directory = Path(temporary)
        cfg = {
            "mixed-port": 0, "allow-lan": False, "ipv6": False,
            "mode": "rule", "log-level": "silent",
            "external-controller": f"127.0.0.1:{ctrl_port}",
            "profile": {"store-selected": False, "store-fake-ip": False},
            "proxies": proxies,
            "proxy-groups": [
                {"name": "AWG-AUDIT-SELECT", "type": "select",
                 "proxies": [x["direct"] for x in test_entries] +
                            [x["relay"] for x in test_entries]}
            ],
            "rules": ["MATCH,AWG-AUDIT-SELECT"]
        }
        cfg_file = directory / "config.yaml"
        cfg_file.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
        cfg_file.chmod(0o600)
        proc = subprocess.Popen(
            [base.MIHOMO, "-d", str(directory), "-f", str(cfg_file)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
        )
        try:
            expected = [x["direct"] for x in test_entries] + [x["relay"] for x in test_entries]
            base.wait_ready(ctrl_port, expected, proc)
            results = []
            print("MIHOMO_NATIVE_CHAIN_AB", flush=True)
            print("selected_tcp_profiles=20", flush=True)
            print("mechanism=isolated_Mihomo_dialer-proxy_to_existing_SOCKS5", flush=True)
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                futures = [ex.submit(run_one, ctrl_port, entry) for entry in test_entries]
                for i, fut in enumerate(as_completed(futures), 1):
                    results.append(fut.result())
                    if i % 5 == 0 or i == len(futures):
                        print("PROGRESS=", i, "/", len(futures), flush=True)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
    outcome = Counter()
    outcome_by_baseline = defaultdict(Counter)
    outcome_by_protocol = defaultdict(Counter)
    for r in results:
        a = r["direct"] == "ok"
        b = r["relay"] == "ok"
        label = ("direct_ok" if a else "direct_failed") + "_" + \
                ("relay_ok" if b else "relay_failed")
        outcome[label] += 1
        outcome_by_baseline[r["baseline"]][label] += 1
        outcome_by_protocol[r["kind"]][label] += 1
    print("paired_native_https=", dict(sorted(outcome.items())))
    print("by_baseline=", {k: dict(sorted(v.items())) for k, v in sorted(outcome_by_baseline.items())})
    print("by_protocol=", {k: dict(sorted(v.items())) for k, v in sorted(outcome_by_protocol.items())})
    print("local_controller_direct_codes=", dict(sorted(Counter(r["direct"] for r in results).items())))
    print("local_controller_relay_codes=", dict(sorted(Counter(r["relay"] for r in results).items())))
    print("secondary_https_confirmed_direct=", sum(r["direct_confirm"] == "ok" for r in results))
    print("secondary_https_confirmed_relay=", sum(r["relay_confirm"] == "ok" for r in results))
    print("NOTE=results_are_point_in_time; relay depends on current working Mihomo")
    print("DPI_CONFIRMED=unknown; per_destination_MikroTik_DIRECT_not_independently_verified")
    print("SECRETS_NODES_ADDRESSES_HIDDEN=YES")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("AB_AUDIT_INTERRUPTED", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print("AB_AUDIT_ERROR=", type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
