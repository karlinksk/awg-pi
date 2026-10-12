#!/usr/bin/env python3
"""Evidence about the Pi-to-node underlay; SHADOW ONLY.

Local `ip route get` can identify a Pi interface and next hop; it CANNOT
prove how MikroTik routes traffic after it receives the packet. A local
LAN default route must never be called router-verified DIRECT.
No DNS lookup, packet emission, networking configuration or privileged
command is performed.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path
import re
import subprocess
from typing import Callable

VALID_KINDS = ("DIRECT_LOCAL_UNVERIFIED", "ASSISTED_AWG",
               "ASSISTED_MIHOMO", "UNKNOWN")
CHAIN_KEYS = ("dialer-proxy", "detour")
TIMEOUT_SECONDS = 2


def route_tokens(output: str) -> dict:
    """Parse one `ip -4 route get` result; no interpolation or shell."""
    if not isinstance(output, str) or len(output) > 4096:
        raise ValueError("unusable route result")
    line = output.splitlines()[0] if output.strip() else ""
    tokens = line.split()
    if not tokens or any(w in tokens for w in ("unreachable", "blackhole", "prohibit")):
        raise ValueError("route unavailable")
    values = {}
    for keyword in ("dev", "via", "src", "table"):
        if tokens.count(keyword) > 1:
            raise ValueError("ambiguous route")
        if keyword in tokens:
            i = tokens.index(keyword)
            if i + 1 >= len(tokens):
                raise ValueError("incomplete route")
            values[keyword] = tokens[i + 1]
    return values


def configured_lan(env_path: Path = Path("/etc/awg-pbr/env")) -> tuple[str, str]:
    """Read the *installed* gateway LAN policy; never execute shell from env."""
    if env_path.stat().st_size > 16384:
        raise ValueError("LAN configuration too large")
    vals = {}
    for line in env_path.read_text("utf-8").splitlines():
        line = line.strip()
        match = re.fullmatch(r"([A-Z_]+)=['\"]?([a-zA-Z0-9_./:-]+)['\"]?", line)
        if match and match.group(1) in ("LAN_IF", "ROUTER_IP"):
            vals[match.group(1)] = match.group(2)
    dev, gw = vals.get("LAN_IF", ""), vals.get("ROUTER_IP", "")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,14}", dev):
        raise ValueError("invalid LAN device in gateway config")
    ipaddress.IPv4Address(gw)
    return dev, gw


def classify(node: dict, *, route_get: Callable | None = None,
             lan_interface: str = "eth0", lan_gateway: str = "192.168.112.1") -> dict:
    """Return sanitized evidence only; NEVER assert MikroTik-side DIRECT."""
    evidence = {"mode": "UNKNOWN", "reason": "unverified_endpoint",
                "scope": "PI_ONLY", "router_verified": False}
    if route_get is None:
        # The installed gateway supports SSH-safe LAN reconfiguration, so
        # never assume the test-stand's eth0/192.168.112.1 in production.
        try:
            lan_interface, lan_gateway = configured_lan()
        except (OSError, ValueError):
            return {**evidence, "reason": "lan_policy_unavailable"}
    if not isinstance(node, dict):
        return evidence
    if any(node.get(key) for key in CHAIN_KEYS):
        return {**evidence, "mode": "ASSISTED_MIHOMO",
                "reason": "proxy_chain_declared"}
    explicit_interface = node.get("interface-name")
    if explicit_interface and explicit_interface != lan_interface:
        mode = "ASSISTED_AWG" if str(explicit_interface).startswith("awg") else "UNKNOWN"
        return {**evidence, "mode": mode, "reason": "non_lan_interface"}
    server = node.get("server")
    try:
        address = ipaddress.IPv4Address(server)
        if not address.is_global:
            return {**evidence, "reason": "endpoint_not_global_ipv4"}
    except (ValueError, TypeError, ipaddress.AddressValueError):
        return {**evidence, "reason": "endpoint_requires_dns_validation"}
    if (not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,14}", lan_interface)
            or not isinstance(lan_gateway, str)):
        return {**evidence, "reason": "invalid_underlay_policy"}
    try:
        if route_get is None:
            def route_get(ip):
                completed = subprocess.run(
                    ["/usr/sbin/ip", "-4", "route", "get", ip],
                    capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                    check=False)
                if completed.returncode != 0:
                    raise OSError("route inspection failed")
                return completed.stdout
        routes = route_tokens(route_get(str(address)))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {**evidence, "reason": "route_inspection_unavailable"}
    device = routes.get("dev", "")
    if device.startswith("awg"):
        return {**evidence, "mode": "ASSISTED_AWG", "reason": "routed_via_awg"}
    if device.startswith("mihomo"):
        return {**evidence, "mode": "ASSISTED_MIHOMO", "reason": "routed_via_mihomo"}
    if device == lan_interface and routes.get("via") == lan_gateway:
        # This is the ONLY claim the Pi can verify. Router-side SSTP policy
        # remains unknown until separately verified on MikroTik.
        return {**evidence, "mode": "DIRECT_LOCAL_UNVERIFIED",
                "reason": "lan_next_hop_router_not_verified"}
    return {**evidence, "reason": "unexpected_next_hop"}


def proved_direct(evidence: dict) -> bool:
    """Provisionally impossible on Pi-only measurements by design."""
    return (
        isinstance(evidence, dict)
        and evidence.get("mode") == "DIRECT"
        and evidence.get("scope") == "END_TO_END"
        and evidence.get("router_verified") is True
        and evidence.get("reason") == "router_underlay_verified"
    )
