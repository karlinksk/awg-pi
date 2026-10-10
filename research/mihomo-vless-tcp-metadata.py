#!/usr/bin/env python3
"""Metadata-only TCP trace during isolated native VLESS+REALITY A/B.

No pcap, no payload bytes, no raw tcpdump output, no secrets in report.
A root-only transient Mihomo config lives only in /run; no changes to TUN,
nftables, routes, production Mihomo or SSTP. This traces Pi eth0 only.
"""
from __future__ import annotations

from collections import Counter
import copy
import importlib.util
import ipaddress
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import yaml

ROOT = Path(__file__).with_name("mihomo-endpoint-reprobe.py")
sp = importlib.util.spec_from_file_location("mihomo_reprobe_base", ROOT)
base = importlib.util.module_from_spec(sp)
sp.loader.exec_module(base)

TARGET_IP = "159.89.87.21"
TARGET_PORT = 28190
HEALTH_URL = "https://www.gstatic.com/generate_204"
CONTROL_URL = "https://www.cloudflare.com/cdn-cgi/trace"
TIMEOUT_MS = 10000


def get_item():
    source, snapshot, _ = base.load_matching()
    candidates = [i for i in base.choose(source, snapshot)
                  if i["kind"] == "vless" and i["baseline"] == "failed"
                  and i["host"] == TARGET_IP and i["port"] == TARGET_PORT]
    if len(candidates) != 1:
        base.fail("no_unique_matching_candidate")
    item = candidates[0]
    if (item["raw"].get("tls") is not True or
        item["raw"].get("flow") != "xtls-rprx-vision" or
        not item["raw"].get("reality-opts")):
        base.fail("not_expected_reality_vision_profile")
    status, address = base.endpoint_preflight(item)
    if status != "pi_direct_only" or address != TARGET_IP:
        base.fail("pi_direct_preflight_failed")
    return item


def test_delay(port: int, alias: str, url: str):
    route = urllib.parse.quote(alias, safe="")
    query = urllib.parse.urlencode({"url": url, "timeout": TIMEOUT_MS})
    state, latency = base.controller(
        port, f"/proxies/{route}/delay?{query}", seconds=13
    )
    return state if state != "ok" else ("ok" if latency else "no_positive_delay")


def tcp_trace_metrics(text: str) -> dict:
    result = Counter()
    for line in text.splitlines():
        if " IP " not in line or f"{TARGET_IP}.{TARGET_PORT}" not in line:
            continue
        fields = line.split(" IP ", 1)[1].split(": ", 1)
        if len(fields) != 2 or " > " not in fields[0]:
            continue
        lhs, rhs = fields[0].split(" > ", 1)
        if rhs.endswith(":"):
            rhs = rhs[:-1]
        direction = "out" if lhs.startswith("192.168.112.34.") and rhs.startswith(TARGET_IP+".") else (
            "in" if lhs.startswith(TARGET_IP+".") and rhs.startswith("192.168.112.34.") else "other")
        if direction == "other":
            continue
        result[f"pkts_{direction}"] += 1
        flags = re.search(r"Flags \[([^\]]+)\]", fields[1])
        if flags:
            flag = flags.group(1)
            if direction == "out" and flag == "S":
                result["out_syn"] += 1
            if direction == "in" and "S" in flag and "." in flag:
                result["in_synack"] += 1
            if direction == "in" and ("R" in flag or "F" in flag):
                result["in_close_reset"] += 1
        match = re.search(r"\blength (\d+)\b", fields[1])
        if match and int(match.group(1)) > 0:
            result[f"data_pkts_{direction}"] += 1
            result[f"data_bytes_{direction}"] += int(match.group(1))
    return {k: result.get(k, 0) for k in (
        "pkts_out", "pkts_in", "out_syn", "in_synack", "in_close_reset",
        "data_pkts_out", "data_pkts_in", "data_bytes_out", "data_bytes_in")}


def capture_for_direct(port: int, alias: str) -> tuple[str, dict]:
    # Text-only TCP headers. TemporaryFile resides in tmpfs, unlinked immediately.
    with tempfile.TemporaryFile(mode="w+t", dir="/run") as log:
        sniffer = subprocess.Popen(
            ["/usr/bin/tcpdump", "-i", "eth0", "-nn", "-tt", "-l", "-U",
             f"tcp and host {TARGET_IP} and port {TARGET_PORT}"],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.4)
            if sniffer.poll() is not None:
                base.fail("tcpdump_failed_to_start")
            status = test_delay(port, alias, HEALTH_URL)
        finally:
            sniffer.terminate()
            try:
                sniffer.wait(timeout=3)
            except subprocess.TimeoutExpired:
                sniffer.kill()
                sniffer.wait(timeout=2)
        log.seek(0)
        return status, tcp_trace_metrics(log.read())


def main():
    if base.os.geteuid() != 0:
        base.fail("requires_root")
    item = get_item()
    if subprocess.run(["systemctl", "is-active", "--quiet", "awg-mihomo.service"]).returncode:
        base.fail("production_mihomo_not_healthy")
    with socket.create_connection(("127.0.0.1", 7890), timeout=3):
        pass
    raw = item["raw"]
    direct = copy.deepcopy(raw)
    relay = copy.deepcopy(raw)
    direct["name"] = "AUDIT-VLESS-DIRECT"
    relay["name"] = "AUDIT-VLESS-RELAY"
    if relay.get("dialer-proxy"):
        base.fail("unexpected_original_dialer_proxy")
    relay["dialer-proxy"] = "AUDIT-UPSTREAM"
    port = base.free_port()
    with tempfile.TemporaryDirectory(prefix="awg-vless-metadata-", dir="/run") as tmp:
        root = Path(tmp)
        cfg = {
            "mixed-port": 0, "allow-lan": False, "ipv6": False,
            "mode": "rule", "log-level": "silent",
            "external-controller": f"127.0.0.1:{port}",
            "profile": {"store-selected": False, "store-fake-ip": False},
            "proxies": [
                {"name":"AUDIT-UPSTREAM","type":"socks5",
                 "server":"127.0.0.1","port":7890,"udp":False},
                direct, relay
            ],
            "proxy-groups":[{"name":"AUDIT-SELECT","type":"select",
                             "proxies":[direct["name"],relay["name"]]}],
            "rules":["MATCH,AUDIT-SELECT"]
        }
        conf = root / "config.yaml"
        conf.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        conf.chmod(0o600)
        proc = subprocess.Popen([base.MIHOMO, "-d", str(root), "-f", str(conf)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            base.wait_ready(port, [direct["name"], relay["name"]], proc)
            print("VLESS_REALITY_TCP_METADATA_AUDIT", flush=True)
            print("endpoint="+TARGET_IP+":"+str(TARGET_PORT), "mode=isolated", flush=True)
            for attempt in (1, 2):
                direct_result, metrics = capture_for_direct(port, direct["name"])
                relay_result = test_delay(port, relay["name"], HEALTH_URL)
                relay_control = test_delay(port, relay["name"], CONTROL_URL) if relay_result == "ok" else "not_tested"
                print("ATTEMPT", attempt,
                      "direct=",direct_result,
                      "relay=",relay_result,
                      "relay_second_target=",relay_control,
                      "tcp=",metrics,flush=True)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
    print("CAUTION=TCP_payload_sizes_do_not_reveal_tls_or_reality_contents")
    print("DPI_CONFIRMED=unknown; secrets_redacted=yes; persistent_capture=no")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("AUDIT_ERROR",type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
