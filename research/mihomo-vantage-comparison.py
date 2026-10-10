#!/usr/bin/env python3
"""Read-only two-vantage connectivity comparison for sampled Mihomo endpoints.

Uses a fixed 25-node sample from an existing pool (20 TCP, 5 UDP skipped).
Vantage A: direct Pi TCP.
Vantage B: existing healthy Mihomo mixed HTTP CONNECT, without changing node.
Never modifies routes, nftables, services or provider. Aggregate-only output.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import ipaddress
from pathlib import Path
import socket
import ssl
import sys
import urllib.request

SOURCE = Path(__file__).with_name("mihomo-endpoint-reprobe.py")
spec = importlib.util.spec_from_file_location("reprobe_base", SOURCE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

PROXY = ("127.0.0.1", 7890)
CONNECT_TIMEOUT = 4.0
TLS_TIMEOUT = 4.0
MAX_CONCURRENT = 4


def tcp_direct(ip, port):
    try:
        sock = socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT)
        return sock, "connected"
    except socket.timeout:
        return None, "timeout"
    except ConnectionRefusedError:
        return None, "refused"
    except OSError:
        return None, "error"


def tcp_via_proxy(ip, port):
    """Connect to exact selected IPv4 through current foreign proxy.

    Returns live socket after CONNECT or an aggregate-only category.
    Proxy-side status is NOT a remote HTTP response.
    """
    sock = None
    try:
        sock = socket.create_connection(PROXY, timeout=CONNECT_TIMEOUT)
        sock.settimeout(CONNECT_TIMEOUT + 2)
        request = (f"CONNECT {ip}:{port} HTTP/1.1\r\nHost: {ip}:{port}\r\n"
                   "Proxy-Connection: close\r\n\r\n")
        sock.sendall(request.encode("ascii"))
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer and len(buffer) < 8192:
            data = sock.recv(1024)
            if not data:
                break
            buffer.extend(data)
        first = bytes(buffer).split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = first.split()
        if len(parts) >= 2 and parts[0].startswith("HTTP/") and parts[1] == "200":
            return sock, "connected"
        sock.close()
        return None, "proxy_connect_rejected"
    except socket.timeout:
        if sock:
            sock.close()
        return None, "timeout"
    except OSError:
        if sock:
            sock.close()
        return None, "proxy_or_network_error"


def tls_eligible(item):
    raw = item["raw"]
    if raw.get("reality-opts") or raw.get("reality_opts"):
        return False
    if item["kind"] == "trojan":
        return True
    if item["kind"] == "vless" and raw.get("tls") is True:
        return True
    return False


def tls_on_socket(sock, item):
    if sock is None:
        return "not_connected"
    raw = item["raw"]
    name = raw.get("sni") or raw.get("servername") or raw.get("server")
    if not isinstance(name, str) or not name or len(name) > 253:
        name = None
    try:
        if name and ipaddress.ip_address(name):
            name = None
    except ValueError:
        pass
    context = ssl.create_default_context()
    # This is *only* an indicative TLS handshake; cert validation and
    # client fingerprint correctness require the native proxy client.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        sock.settimeout(TLS_TIMEOUT)
        with context.wrap_socket(sock, server_hostname=name) as wrapped:
            _ = wrapped.version()
        return "tls_handshake"
    except ssl.SSLError:
        return "tls_error"
    except socket.timeout:
        return "tls_timeout"
    except OSError:
        return "tls_io_error"


def audit_one(item, ip):
    direct_sock, direct_status = tcp_direct(ip, item["port"])
    foreign_sock, foreign_status = tcp_via_proxy(ip, item["port"])
    tls_direct = tls_foreign = "not_eligible"
    if tls_eligible(item):
        tls_direct = tls_on_socket(direct_sock, item)
        tls_foreign = tls_on_socket(foreign_sock, item)
    else:
        if direct_sock:
            direct_sock.close()
        if foreign_sock:
            foreign_sock.close()
    return {
        "proto": item["kind"],
        "baseline": item["baseline"],
        "direct": direct_status,
        "foreign": foreign_status,
        "tls_direct": tls_direct,
        "tls_foreign": tls_foreign,
    }


def public_egress(use_proxy: bool):
    url = "https://api.ipify.org"
    handlers = [urllib.request.ProxyHandler(
        {"https": f"http://{PROXY[0]}:{PROXY[1]}"}
        if use_proxy else {})]
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(url, timeout=9) as response:
            addr = response.read(100).decode().strip()
        if ipaddress.ip_address(addr).version == 4 and ipaddress.ip_address(addr).is_global:
            return addr
    except Exception:
        return None
    return None


def main():
    if base.os.geteuid() != 0:
        base.fail("requires_root_for_private_snapshot")
    source, nodes, snapshot = base.load_matching()
    sample = base.choose(source, nodes)
    testable = [item for item in sample if item["kind"] != "hysteria2"]
    if len(sample) != 25 or len(testable) != 20:
        base.fail("unexpected_sample_sizes")
    if base.subprocess.run(["systemctl", "is-active", "--quiet", "awg-mihomo.service"]).returncode:
        base.fail("production_mihomo_unavailable")
    direct_egress = public_egress(False)
    proxy_egress = public_egress(True)
    if not direct_egress or not proxy_egress or direct_egress == proxy_egress:
        base.fail("independent_vantages_unverified")
    print("MIHOMO_VANTAGE_COMPARE", flush=True)
    print("vantages=distinct_public_ipv4; addresses_suppressed=true", flush=True)
    selected = []
    routing = Counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        future_map = {ex.submit(base.endpoint_preflight, item): item for item in testable}
        for future in as_completed(future_map):
            item = future_map[future]
            state, ip = future.result()
            routing[state] += 1
            if state == "pi_direct_only":
                selected.append((item, ip))
    print("pi_routing_preflight=", dict(routing), flush=True)
    if len(selected) < 10:
        base.fail("too_few_valid_direct_routes")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as ex:
        fut = {ex.submit(audit_one, item, ip): item for item, ip in selected}
        for idx, f in enumerate(as_completed(fut), 1):
            try:
                results.append(f.result())
            except Exception:
                results.append({"proto": fut[f]["kind"], "baseline": fut[f]["baseline"],
                                "direct": "probe_exception", "foreign": "probe_exception",
                                "tls_direct": "not_measured", "tls_foreign": "not_measured"})
            if idx % 5 == 0 or idx == len(fut):
                print("PROGRESS=", idx, "/", len(fut), flush=True)
    print("tested_tcp_endpoints=", len(results))
    print("direct_tcp=", dict(sorted(Counter(x["direct"] for x in results).items())))
    print("foreign_tcp=", dict(sorted(Counter(x["foreign"] for x in results).items())))
    comparisons = Counter()
    for x in results:
        d = x["direct"] == "connected"
        f = x["foreign"] == "connected"
        comparisons[("direct_ok" if d else "direct_failed") + "_" +
                    ("foreign_ok" if f else "foreign_failed")] += 1
    print("paired_tcp=", dict(sorted(comparisons.items())))
    print("paired_by_baseline=", {key: dict(sorted(Counter(
        ("direct_ok" if x["direct"] == "connected" else "direct_failed") + "_" +
        ("foreign_ok" if x["foreign"] == "connected" else "foreign_failed")
        for x in results if x["baseline"] == key).items())) for key in ("failed", "healthy")})
    print("paired_by_protocol=", {key: dict(sorted(Counter(
        ("direct_ok" if x["direct"] == "connected" else "direct_failed") + "_" +
        ("foreign_ok" if x["foreign"] == "connected" else "foreign_failed")
        for x in results if x["proto"] == key).items())) for key in ("ss", "trojan", "vless", "vmess")})
    print("generic_tls_direct=", dict(sorted(Counter(x["tls_direct"] for x in results).items())))
    print("generic_tls_foreign=", dict(sorted(Counter(x["tls_foreign"] for x in results).items())))
    print("NOTE=TCP CONNECT only; generic TLS is not a Mihomo protocol handshake")
    print("DPI_CONFIRMED=not_determined; MikroTik per-endpoint DIRECT policy unverified")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print("VANTAGE_AUDIT_ERROR=", type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
