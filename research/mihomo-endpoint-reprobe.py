#!/usr/bin/env python3
"""Controlled isolated Mihomo proxy health re-probe. NO TUN, NO ROUTE/NFT CHANGES.

This program reads the root-only subscription and a corresponding saved pool,
chooses a stratified sample of distinct host:port entries, validates Pi DIRECT
routes, starts an isolated Mihomo instance with a localhost-only controller,
and tests two public HTTPS URLs at 4.5s and 10s. Do not equate failure to DPI.
Secrets are held only in root-only tmpfs configuration, removed at exit.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import ipaddress
import json
import os
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

PROVIDER = Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
POOL = Path("/run/awg-pbr/mihomo-pool/live.json")
MIHOMO = "/usr/local/bin/mihomo"
ROUTER = "192.168.112.1"
LAN_IF = "eth0"
URLS = ["https://www.gstatic.com/generate_204",
        "https://www.cloudflare.com/cdn-cgi/trace"]
TIMEOUTS_MS = [4500, 10000]
PROTOCOLS = ["hysteria2", "ss", "trojan", "vless", "vmess"]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fail(message):
    print("AUDIT_ABORT:", message, file=sys.stderr)
    raise SystemExit(2)


def load_matching():
    raw_data = PROVIDER.read_bytes()
    pool = json.loads(POOL.read_text())
    if hashlib.sha256(raw_data).hexdigest() != pool.get("provider_sha256"):
        fail("provider-pool-checksum-mismatch")
    config = yaml.safe_load(raw_data)
    source = config.get("proxies") if isinstance(config, dict) else None
    nodes = pool.get("nodes")
    if not isinstance(source, list) or not isinstance(nodes, list) or len(nodes) != len(source):
        fail("snapshot-indices-do-not-match-provider")
    if len(nodes) < 1:
        fail("empty-provider")
    return source, nodes, pool


def choose(source, nodes, failed_per_proto=4, healthy_per_proto=1):
    # Maintain a single globally unique textual host:port per test.
    picked = []
    used = set()
    counters = Counter()
    for ptype in PROTOCOLS:
        for want_healthy, n in ((False, failed_per_proto), (True, healthy_per_proto)):
            candidates = []
            for i, node in enumerate(nodes):
                if not isinstance(node, dict) or not isinstance(source[i], dict):
                    continue
                if str(node.get("type", "")).lower() != ptype:
                    continue
                if (node.get("healthy") is True) != want_healthy:
                    continue
                raw = source[i]
                host, port = raw.get("server"), raw.get("port")
                if isinstance(port, str) and port.isdigit():
                    port = int(port)
                if not isinstance(host, str) or not host or not isinstance(port, int) or not 1 <= port <= 65535:
                    continue
                if node.get("server") != host or int(node.get("port", -1)) != port:
                    continue
                key = (host, port)
                # Stable pseudorandom selection without disclosing host or endpoint.
                rank = hashlib.sha256(f"{host}:{port}:{i}".encode()).hexdigest()
                candidates.append((rank, key, i))
            for _, key, i in sorted(candidates):
                if key in used:
                    continue
                used.add(key)
                picked.append({"kind": ptype, "baseline": "healthy" if want_healthy else "failed",
                               "raw": source[i].copy(), "host": key[0], "port": key[1], "index": i})
                counters[(ptype, "healthy" if want_healthy else "failed")] += 1
                if counters[(ptype, "healthy" if want_healthy else "failed")] >= n:
                    break
    return picked


def endpoint_preflight(item):
    host, port = item["host"], item["port"]
    try:
        answers = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        ips = sorted({ans[4][0] for ans in answers})[:4]
    except (OSError, ValueError):
        return "dns_failed", None
    if not ips:
        return "dns_failed", None
    for ip in ips:
        try:
            if not ipaddress.ip_address(ip).is_global:
                return "non_public_endpoint", None
            proc = subprocess.run(["/usr/sbin/ip", "-4", "route", "get", ip],
                                  capture_output=True, text=True, timeout=2)
            routing = proc.stdout.strip()
            if proc.returncode != 0 or f"via {ROUTER} " not in routing or f"dev {LAN_IF}" not in routing:
                return "pi_route_not_direct", None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return "route_unknown", None
    return "pi_direct_only", ips[0]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def controller(port, path, seconds):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with OPENER.open(req, timeout=seconds) as resp:
            data = json.loads(resp.read(65536))
            delay = data.get("delay")
            return ("ok", delay if isinstance(delay, int) and delay > 0 else None)
    except urllib.error.HTTPError as exc:
        return (f"api_{exc.code}", None)
    except Exception:
        return ("api_exception", None)


def wait_ready(port, expected, proc):
    deadline = time.monotonic() + 14
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            fail("isolated-mihomo-exited")
        try:
            with OPENER.open(f"http://127.0.0.1:{port}/proxies", timeout=1) as r:
                data = json.loads(r.read(300000))
            known = data.get("proxies", {})
            if isinstance(known, dict) and all(k in known for k in expected):
                return
        except Exception:
            pass
        time.sleep(0.2)
    fail("isolated-mihomo-not-ready")


def probe(item, port):
    alias = item["alias"]
    code = urllib.parse.quote(alias, safe="")
    results = []
    for url in URLS:
        for ms in TIMEOUTS_MS:
            query = urllib.parse.urlencode({"url": url, "timeout": ms})
            status, delay = controller(port, f"/proxies/{code}/delay?{query}", seconds=ms / 1000 + 3)
            results.append((status, delay))
    return results


def direct_tcp(ip, port, ptype):
    if ptype == "hysteria2":
        return "udp_not_tested"
    try:
        with socket.create_connection((ip, port), timeout=2.5):
            return "tcp_connected"
    except socket.timeout:
        return "tcp_timeout"
    except ConnectionRefusedError:
        return "tcp_refused"
    except OSError:
        return "tcp_error"


def direct_control(url):
    try:
        with OPENER.open(url, timeout=6) as resp:
            return "reachable" if 200 <= resp.status < 400 else "http_other"
    except Exception:
        return "unreachable"


def evaluate(item, port):
    statuses = probe(item, port)
    short_ok = any(x[0] == "ok" for x in [statuses[0], statuses[2]])
    long_ok = any(x[0] == "ok" for x in [statuses[1], statuses[3]])
    target1_ok = any(x[0] == "ok" for x in statuses[:2])
    target2_ok = any(x[0] == "ok" for x in statuses[2:])
    def classify():
        if short_ok and long_ok:
            return "working_both_timeouts"
        if not short_ok and long_ok:
            return "recovered_at_10s"
        if short_ok and not long_ok:
            return "inconsistent"
        return "still_failing"
    return {
        "baseline": item["baseline"], "proto": item["kind"],
        "result": classify(), "gstatic_ok": target1_ok, "cloudflare_ok": target2_ok,
        "api_responses": [s[0] for s in statuses],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="select only; no network")
    ap.add_argument("--run", action="store_true", help="perform bounded isolated network tests")
    args = ap.parse_args()
    if args.plan == args.run:
        fail("choose exactly one of --plan and --run")
    if os.geteuid() != 0:
        fail("requires root to read private subscription")
    source, nodes, pool = load_matching()
    selected = choose(source, nodes)
    print("MIHOMO_REPROBE_PHASE_B")
    print("snapshot_profiles=", len(nodes), "sample_selected=", len(selected), "mode=", "run" if args.run else "plan", flush=True)
    print("sample_by_type_and_baseline=", dict(sorted(Counter((x["kind"], x["baseline"]) for x in selected).items())), flush=True)
    if args.plan:
        return
    if len(selected) < 20:
        fail("too_few_sample_nodes")
    if subprocess.run(["systemctl", "is-active", "--quiet", "awg-mihomo.service"]).returncode != 0:
        fail("production_mihomo_not_running")
    if subprocess.run(["/usr/sbin/ip", "-4", "route", "get", "1.1.1.1"],
                      capture_output=True, text=True).returncode != 0:
        fail("routing_unavailable")
    # Preflight routes first, no routes or nft changes. DNS can still resolve differently in Mihomo.
    preflights = {}
    with ThreadPoolExecutor(max_workers=5) as pool_executor:
        future_map = {pool_executor.submit(endpoint_preflight, it): i for i, it in enumerate(selected)}
        for future in as_completed(future_map):
            preflights[future_map[future]] = future.result()
    route_counts = Counter(v[0] for v in preflights.values())
    print("endpoint_preflight=", dict(sorted(route_counts.items())), flush=True)
    runnable = []
    for i, item in enumerate(selected):
        route_status, ip = preflights[i]
        if route_status == "pi_direct_only":
            item["ip_for_tcp"] = ip
            item["alias"] = f"AUDIT-{i:03}"
            runnable.append(item)
    if len(runnable) < 5:
        fail("too_few_direct_endpoints")
    control_results = {("gstatic" if i == 0 else "cloudflare"): direct_control(url)
                       for i, url in enumerate(URLS)}
    print("direct_https_controls=", control_results, flush=True)
    for item in runnable:
        raw = item["raw"]
        raw["name"] = item["alias"]
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="awg-dpi-reprobe-", dir="/run") as temp:
        root = Path(temp)
        config = {
            "mixed-port": 0, "allow-lan": False, "ipv6": False, "mode": "rule",
            "log-level": "silent", "external-controller": f"127.0.0.1:{port}",
            "profile": {"store-selected": False, "store-fake-ip": False},
            "proxies": [it["raw"] for it in runnable],
            "proxy-groups": [{"name": "AWG-REPROBE", "type": "select",
                              "proxies": [it["alias"] for it in runnable]}],
            "rules": ["MATCH,AWG-REPROBE"],
        }
        path = root / "config.yaml"
        path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
        path.chmod(0o600)
        proc = subprocess.Popen([MIHOMO, "-d", str(root), "-f", str(path)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            wait_ready(port, [i["alias"] for i in runnable], proc)
            done = 0
            observed = []
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = {executor.submit(evaluate, it, port): it for it in runnable}
                for future in as_completed(futures):
                    it = futures[future]
                    try:
                        result = future.result()
                    except Exception:
                        result = {"baseline": it["baseline"], "proto": it["kind"],
                                  "result": "test_exception", "gstatic_ok": False,
                                  "cloudflare_ok": False, "api_responses": []}
                    result["tcp"] = direct_tcp(it["ip_for_tcp"], it["port"], it["kind"])
                    observed.append(result)
                    done += 1
                    if done % 5 == 0 or done == len(runnable):
                        print("PROGRESS=", done, "/", len(runnable), flush=True)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
    print("completed_nodes=", len(observed))
    print("outcomes=", dict(sorted(Counter(x["result"] for x in observed).items())))
    print("tcp_reachability=", dict(sorted(Counter(x["tcp"] for x in observed).items())))
    print("local_mihomo_api_fail_codes=", dict(sorted(Counter(s for x in observed for s in x["api_responses"] if s != "ok").items())))
    print("by_baseline=", {key: dict(sorted(Counter(x["result"] for x in observed if x["baseline"] == key).items()))
                           for key in ("failed", "healthy")})
    print("by_protocol=", {key: dict(sorted(Counter(x["result"] for x in observed if x["proto"] == key).items()))
                           for key in PROTOCOLS})
    print("gstatic_success_nodes=", sum(x["gstatic_ok"] for x in observed),
          "cloudflare_success_nodes=", sum(x["cloudflare_ok"] for x in observed))
    print("DPI_CONFIRMED=unknown")
    print("LIMITS=Pi route only; MikroTik DIRECT not verified; DNS/TLS/UDP cause not isolated")
    print("SECRETS_ENDPOINTS_AND_NAMES_SUPPRESSED=YES")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("AUDIT_INTERRUPTED", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print("AUDIT_ERROR=", type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
