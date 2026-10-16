#!/usr/bin/env python3
"""One-shot read-only IP-target HTTPS diagnostic for Mihomo.

Review-only: not installed, scheduled or wired into selection. A proxy test
uses numeric HTTP CONNECT while retaining HTTPS hostname/SNI. A TUN test
uses curl --resolve and binds to the specified TUN interface. Both use the
Pi resolver, bounded work, TLS verification and fixed approved origin.
No subscription, route, selector, firewall or persistent-state access.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
import sys

ORIGIN = "api.ipify.org"
URL = "https://api.ipify.org/"
MAX_IPS = 2
RESOLVE_TIMEOUT = 4
CONNECT_TIMEOUT = 3
REQUEST_TIMEOUT = 8
SAFE_IF = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


def ipv4_candidates(raw: str) -> list[str]:
    result: list[str] = []
    for line in raw.splitlines():
        fields = line.split()
        if not fields:
            continue
        try:
            value = ipaddress.IPv4Address(fields[0])
        except ipaddress.AddressValueError:
            continue
        if not value.is_global:
            continue
        ip = str(value)
        if ip not in result:
            result.append(ip)
        if len(result) >= MAX_IPS:
            break
    return result


def curl_args(mode: str, ip: str, *, port: int | None, interface: str | None) -> list[str]:
    common = [
        "-q", "-4", "--silent", "--show-error",
        "--connect-timeout", str(CONNECT_TIMEOUT),
        "--max-time", str(REQUEST_TIMEOUT),
        "--output", "/dev/null",
        "--write-out", "%{http_code}",
    ]
    if mode == "proxy":
        common += [
            "--proxy", f"http://127.0.0.1:{port}",
            "--noproxy", "",
            "--connect-to", f"{ORIGIN}:443:{ip}:443",
        ]
    else:
        common += [
            "--noproxy", "*",
            "--interface", str(interface),
            "--resolve", f"{ORIGIN}:443:{ip}",
        ]
    return common + [URL]


def diagnose(mode: str, *, port: int | None, interface: str | None,
             resolver: str = "getent", curl: str = "curl") -> tuple[str, str, int]:
    try:
        res = subprocess.run([resolver, "ahostsv4", ORIGIN],
                             capture_output=True, text=True,
                             timeout=RESOLVE_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN", "DNS_UNAVAILABLE", 0
    if res.returncode != 0 or len(res.stdout) > 32768:
        return "UNKNOWN", "DNS_UNAVAILABLE", 0
    ips = ipv4_candidates(res.stdout)
    if not ips:
        return "UNKNOWN", "NO_GLOBAL_IPV4", 0

    checked = 0
    for ip in ips:
        checked += 1
        try:
            result = subprocess.run([curl, *curl_args(mode, ip, port=port, interface=interface)],
                                    capture_output=True, text=True,
                                    timeout=REQUEST_TIMEOUT + 2, check=False,
                                    env={**os.environ, "NO_PROXY": "", "no_proxy": ""})
        except (OSError, subprocess.TimeoutExpired):
            return "UNKNOWN", "CONNECT_ERROR", checked
        if result.returncode != 0:
            reason = "TLS_FAILED" if result.returncode == 35 else (
                "TIMEOUT" if result.returncode == 28 else "CONNECT_ERROR")
            return "UNKNOWN", reason, checked
        if result.stdout.strip() != "200":
            return "UNKNOWN", "HTTP_NOT_200", checked
    return "PASS", "ALL_CHECKED_IPV4_HTTPS_OK", checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--proxy-port", "--shadow-port", dest="proxy_port", type=int)
    group.add_argument("--tun-interface")
    args = parser.parse_args(argv)
    if args.proxy_port is not None and not (1 <= args.proxy_port <= 65535):
        parser.error("invalid proxy port")
    if args.tun_interface is not None and not SAFE_IF.fullmatch(args.tun_interface):
        parser.error("invalid interface")
    mode = "proxy" if args.proxy_port is not None else "tun"
    state, reason, count = diagnose(mode, port=args.proxy_port,
                                    interface=args.tun_interface,
                                    resolver=os.environ.get("AWG_IP_CONNECT_GETENT", "getent"),
                                    curl=os.environ.get("AWG_IP_CONNECT_CURL", "curl"))
    print("IP_CONNECT_MODE=" + mode.upper())
    print("IP_CONNECT_STATE=" + state)
    print("IP_CONNECT_REASON=" + reason)
    print("IP_CONNECT_CHECKED_IPV4=" + str(count))
    print("IP_CONNECT_SCOPE=" + ("LOOPBACK_PROXY" if mode == "proxy" else "PI_BOUND_TUN"))
    return 0 if state == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
