#!/usr/bin/env python3
"""Read-only MikroTik RouterOS endpoint path attestation (experimental).

Queries an existing pinned SSH alias with a hard-coded list of *read-only*
RouterOS print commands. No RouterOS writes, TUN changes, password prompts,
credential export, route changes, traceroutes or packet injection.

This attestation is a SHORT-LIVED OBSERVATION, not a cryptographic signature
or permission for a production switch. The action owner must independently
revalidate the destination and router state immediately before committing.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass

SECTIONS = {
    "MANGLE": "/ip/firewall/mangle/print terse without-paging",
    "RULES": "/routing/rule/print terse without-paging",
    "ROUTES": "/ip/route/print terse without-paging",
    "WAN": "/interface/list/member/print terse without-paging",
    "RAW": "/ip/firewall/raw/print terse without-paging",
    "NAT": "/ip/firewall/nat/print terse without-paging",
    "BRIDGE_FILTER": "/interface/bridge/filter/print terse without-paging",
    "BRIDGE_NAT": "/interface/bridge/nat/print terse without-paging",
    "TABLES": "/routing/table/print terse without-paging",
    "VRF": "/ip/vrf/print terse without-paging",
    "HOTSPOT": "/ip/hotspot/print terse without-paging",
    "IPSEC": "/ip/ipsec/policy/print terse without-paging",
}
# Re-read route and mangle at end of one session to detect concurrent edits.
ORDER = (*SECTIONS, "MANGLE_AFTER", "ROUTES_AFTER")
MARKER = "__AWG_RO_ROUTE_"
MAX_OUTPUT = 180_000


def router_script() -> str:
    commands = []
    for key in ORDER:
        name = key.removesuffix("_AFTER")
        commands.extend((f':put "{MARKER}{key}__"', SECTIONS[name]))
    commands.append(f':put "{MARKER}END__"')
    return "; ".join(commands)


def router_snapshot(ssh_alias: str = "mikrotik-gpt",
                    *, runner=subprocess.run, timeout: int = 18) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", ssh_alias):
        raise ValueError("invalid configured SSH alias")
    cmd = [
        "/usr/bin/ssh", "-T", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=4",
        "-o", "ConnectionAttempts=1",
        "-o", "NumberOfPasswordPrompts=0",
        "-o", "ForwardAgent=no",
        "-o", "ClearAllForwardings=yes",
        ssh_alias, router_script(),
    ]
    result = runner(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0 or len(result.stdout) > MAX_OUTPUT:
        raise ValueError("unavailable RouterOS read-only audit")
    return parse_sections(result.stdout)


def parse_sections(output: str) -> dict:
    if not isinstance(output, str) or len(output) > MAX_OUTPUT:
        raise ValueError("unusable RouterOS snapshot")
    state = {}
    current = None
    ended = False
    for raw in output.replace("\r", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.fullmatch(re.escape(MARKER) + r"([A-Z_]+)__", line)
        if match:
            key = match.group(1)
            if key == "END":
                ended = True
                current = None
                continue
            if ended or key not in ORDER or key in state:
                raise ValueError("duplicate or unexpected RouterOS section")
            current = key
            state[key] = []
            continue
        if current is None or ended:
            raise ValueError("RouterOS returned unframed output")
        if line.startswith(("bad command", "syntax error", "failure:", "input does not match")):
            raise ValueError("RouterOS query failed")
        state[current].append(line)
    if not ended or set(state) != set(ORDER):
        raise ValueError("incomplete RouterOS audit")
    if (state["MANGLE"] != state["MANGLE_AFTER"]
            or state["ROUTES"] != state["ROUTES_AFTER"]):
        raise ValueError("router policy changed during audit")
    return state


def records(lines: list[str]) -> list[dict]:
    """Strictly parse 'print terse': index/flags and unquoted key=value fields."""
    rows = []
    for line in lines:
        tokens = line.split()
        if not tokens or not tokens[0].isdigit():
            # Dynamic routes and main routing tables have no numeric index.
            if not tokens or "=" in tokens[0]:
                raise ValueError("unknown RouterOS record")
            if not re.fullmatch(r"[A-Za-z]+", tokens[0]):
                raise ValueError("ambiguous RouterOS flags")
            flags = tokens.pop(0)
            index = None
        else:
            index = int(tokens.pop(0))
            flags = ""
            if tokens and "=" not in tokens[0]:
                flags = tokens.pop(0)
                if not re.fullmatch(r"[A-Za-z]+", flags):
                    raise ValueError("ambiguous RouterOS flags")
        row = {"_index": index, "_flags": flags}
        # 'print terse' does not quote multi-word comments; these fields
        # have no routing semantics, and may be hex-encoded with spaces.
        comment = False
        for token in tokens:
            if "=" not in token:
                if token in ("fib", "blackhole"):
                    row[token] = True
                    comment = False
                elif comment:
                    row["comment"] = row.get("comment", "") + " " + token
                else:
                    raise ValueError("unrecognized RouterOS record field")
                continue
            k, v = token.split("=", 1)
            if not re.fullmatch("[a-zA-Z][a-zA-Z0-9-]*", k) or k in row:
                raise ValueError("invalid RouterOS field")
            row[k] = v.strip('"')
            comment = k == "comment"
        rows.append(row)
    return rows


def enabled(row: dict) -> bool:
    return "X" not in row["_flags"]


def reasoned(endpoint: str, port: int, protocol: str,
             pi_ip: str, local_interface: str, router_gateway: str,
             snapshot: dict) -> dict:
    """Decide only when the *specific* endpoint is unambiguously WAN-direct."""
    def nope(reason):
        return {"mode": "UNKNOWN", "reason": reason,
                "scope": "END_TO_END", "router_verified": False}
    try:
        dest = ipaddress.IPv4Address(endpoint)
        source = ipaddress.IPv4Address(pi_ip)
        router = ipaddress.IPv4Address(router_gateway)
        if (not dest.is_global or not source.is_private or not router.is_private
                or not isinstance(port, int) or isinstance(port, bool)
                or not 1 <= port <= 65535 or protocol not in ("tcp", "udp")):
            return nope("invalid_endpoint_or_source")
        required = ("MANGLE", "RULES", "ROUTES", "WAN", "RAW", "NAT",
                    "BRIDGE_FILTER", "BRIDGE_NAT", "TABLES")
        if not isinstance(snapshot, dict) or not all(k in snapshot for k in required):
            return nope("incomplete_policy_snapshot")
        if (snapshot["MANGLE"] != snapshot.get("MANGLE_AFTER")
                or snapshot["ROUTES"] != snapshot.get("ROUTES_AFTER")):
            return nope("router_policy_changed")
        mangle = records(snapshot["MANGLE"])
        rules = records(snapshot["RULES"])
        routes = records(snapshot["ROUTES"])
        wan = records(snapshot["WAN"])
        nat = records(snapshot["NAT"])
        tables = records(snapshot["TABLES"])
        if any(not isinstance(snapshot[x], list) or snapshot[x]
               for x in ("RAW", "BRIDGE_FILTER", "BRIDGE_NAT", "HOTSPOT")):
            return nope("unsupported_packet_interception")
        # The normal dynamic L2TP/IPsec transport policies do not affect
        # arbitrary Pi endpoint flows. Do not extrapolate to other IPsec
        # policies: accept only inert templates or narrowly scoped
        # L2TP-in-server UDP:1701 policies unrelated to this destination.
        for entry in snapshot["IPSEC"]:
            if "template=yes" in entry:
                continue
            match = re.search(r"\bdst-address=([0-9.]+)/(\d+)\b", entry)
            port_match = re.search(r"\bdst-port=(\d+)\b", entry)
            if (not match or not port_match
                    or "peer=l2tp-in-server" not in entry
                    or "protocol=udp" not in entry
                    or "src-port=1701" not in entry
                    or "action=encrypt" not in entry):
                return nope("ipsec_policy_unverified")
            remote = ipaddress.IPv4Network(match.group(1)+"/"+match.group(2),
                                           strict=False)
            if dest in remote and protocol == "udp" and port == int(port_match.group(1)):
                return nope("endpoint_matches_ipsec_policy")
        if any(enabled(r) for r in rules):
            return nope("routing_rules_unverified")
        # A VRF-bound ingress bridge would bypass assumptions about main.
        if (len(snapshot["VRF"]) != 1 or
                not re.fullmatch(r"0\s+\*\s+name=main\s+interfaces=all",
                                 snapshot["VRF"][0])):
            return nope("nondefault_vrf_unverified")
        if not any(r.get("name") == "main" and "fib" in r
                   for r in tables):
            return nope("main_fib_not_confirmed")
        wan_members = [r.get("interface") for r in wan
                       if enabled(r) and r.get("list") == "WAN"]
        lan_members = [r.get("interface") for r in wan
                       if enabled(r) and r.get("list") == "LAN"]
        if len(wan_members) != 1 or len(lan_members) != 1:
            return nope("unknown_wan_or_lan_membership")
        wan_if, bridge_if = wan_members[0], lan_members[0]
        if (not re.fullmatch("[a-zA-Z0-9_.-]{1,15}", wan_if)
                or bridge_if != "bridge"):
            return nope("unexpected_interface_topology")
        ingress = [r for r in mangle if enabled(r)
                   and r.get("chain") == "prerouting"]
        if not ingress:
            return nope("no_prerouting_protection")
        first = ingress[0]
        match = {k: v for k, v in first.items()
                 if k not in ("_index", "_flags", "comment")}
        if match != {"chain": "prerouting", "action": "accept",
                     "src-address": str(source), "in-interface": bridge_if}:
            return nope("direct_mangle_exemption_missing_or_not_first")
        for r in nat:
            if not enabled(r) or r.get("chain") != "dstnat":
                continue
            if (r.get("action") != "redirect"
                    or r.get("protocol") not in ("tcp", "udp")
                    or r.get("dst-port") != "53"):
                return nope("unsupported_destination_nat")
            if port == 53 and protocol == r["protocol"]:
                return nope("dns_port_intercepted")
        matched = []
        for row in routes:
            if not enabled(row) or row.get("routing-table") != "main":
                continue
            cidr = row.get("dst-address")
            if not isinstance(cidr, str):
                return nope("unknown_main_route")
            net = ipaddress.IPv4Network(cidr, strict=False)
            if dest in net and "A" in row["_flags"]:
                matched.append((net.prefixlen, row))
        if not matched:
            return nope("missing_active_main_route")
        longest = max(x[0] for x in matched)
        winners = [row for prefix, row in matched if prefix == longest]
        if len(winners) != 1:
            return nope("ambiguous_main_route")
        chosen = winners[0]
        if (chosen.get("blackhole") is not None
                or chosen.get("gateway", "").startswith(("sstp", "wg-"))
                or chosen.get("immediate-gw", "").split("%")[-1] != wan_if
                or not chosen.get("gateway")):
            return nope("main_route_not_wan_direct")
        # Caller must separately ensure the Pi's selected source, next hop
        # and interface match the trusted LAN values *before and after* SSH.
        return {"mode": "DIRECT", "scope": "END_TO_END",
                "reason": "router_underlay_verified", "router_verified": True}
    except (KeyError, IndexError, TypeError, ValueError):
        return nope("unparseable_router_policy")


def validate_local_route(endpoint: str, pi_ip: str, lan: str,
                         router: str, *, runner=subprocess.run) -> bool:
    """No packets sent. Verify Pi's source/dev/next-hop precisely."""
    try:
        result = runner(["/usr/sbin/ip", "-4", "route", "get", endpoint],
                        capture_output=True, text=True, timeout=2, check=False)
        if result.returncode or len(result.stdout) > 4096:
            return False
        fields = result.stdout.splitlines()[0].split()
        if (fields.count("via") != 1 or fields.count("dev") != 1
                or fields.count("src") != 1):
            return False
        return (fields[fields.index("via")+1] == router
                and fields[fields.index("dev")+1] == lan
                and fields[fields.index("src")+1] == pi_ip)
    except (OSError, IndexError, ValueError, subprocess.TimeoutExpired):
        return False


def ssh_alias_points_to_router(alias: str, router_ip: str,
                               *, runner=subprocess.run) -> bool:
    """No hostnames/port-forwarding or guessed MikroTik SSH endpoints."""
    try:
        result = runner(["/usr/bin/ssh", "-G", alias],
                        capture_output=True, text=True, timeout=2, check=False)
        if result.returncode or len(result.stdout) > 80_000:
            return False
        fields = {}
        for line in result.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] in ("hostname", "port"):
                fields[parts[0]] = parts[1]
        return (fields.get("hostname") == router_ip
                and fields.get("port", "").isdigit()
                and 1 <= int(fields["port"]) <= 65535
                and not any(line.startswith(("proxyjump ", "proxycommand "))
                            and line.split(None, 1)[1].strip().lower() not in
                            ("", "none")
                            for line in result.stdout.splitlines()))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def attest_ip(endpoint: str, port: int, protocol: str, pi_ip: str,
              local_interface: str, router_gateway: str,
              *, ssh_alias="mikrotik-gpt", snapshot_loader=router_snapshot,
              local_check=validate_local_route,
              alias_check=ssh_alias_points_to_router) -> dict:
    """Observation is not a certificate: MUST be revalidated before switching."""
    if not (alias_check(ssh_alias, router_gateway)
            and local_check(endpoint, pi_ip, local_interface, router_gateway)):
        return {"mode": "UNKNOWN", "scope": "END_TO_END",
                "router_verified": False, "reason": "local_or_ssh_path_unverified"}
    snapshot = snapshot_loader(ssh_alias)
    verdict = reasoned(endpoint, port, protocol, pi_ip, local_interface,
                       router_gateway, snapshot)
    if not local_check(endpoint, pi_ip, local_interface, router_gateway):
        verdict = {"mode": "UNKNOWN", "scope": "END_TO_END",
                   "router_verified": False, "reason": "pi_route_changed_during_audit"}
    verdict["checked_at"] = int(time.time())
    verdict["valid_for_seconds"] = 30 if verdict["router_verified"] else 0
    digest = hashlib.sha256()
    digest.update(f"{endpoint}|{port}|{protocol}|{pi_ip}|{router_gateway}".encode())
    verdict["endpoint_binding_sha256"] = digest.hexdigest()
    # Only metadata leaves this process: no RouterOS full config/creds.
    return verdict


def attest_batch(endpoints: list[dict], pi_ip: str, local_interface: str,
                 router_gateway: str, *, ssh_alias="mikrotik-gpt",
                 snapshot_loader=router_snapshot, local_check=validate_local_route,
                 alias_check=ssh_alias_points_to_router) -> list[dict]:
    """Efficient audit: one pinned read-only RouterOS SSH query per <=20 endpoints.

    Each candidate's Pi-local route is checked separately before and after
    the single RouterOS query. Neither provider credentials nor node names
    are read or emitted.
    """
    if not isinstance(endpoints, list) or not 1 <= len(endpoints) <= 20:
        raise ValueError("expected 1..20 endpoints")
    if not alias_check(ssh_alias, router_gateway):
        return [{"mode":"UNKNOWN", "router_verified":False,
                 "reason":"ssh_target_unverified"} for _ in endpoints]
    def values(item):
        if not isinstance(item, dict):
            return "", 0, ""
        return item.get("ip", ""), item.get("port", 0), item.get("protocol", "")
    before = []
    for item in endpoints:
        ip, _, _ = values(item)
        before.append(bool(isinstance(ip,str) and
                           local_check(ip, pi_ip, local_interface, router_gateway)))
    if not any(before):
        return [{"mode":"UNKNOWN", "router_verified":False,
                 "reason":"local_route_unverified"} for _ in endpoints]
    snapshot = snapshot_loader(ssh_alias)
    checked_at = int(time.time())
    result = []
    for i, entry in enumerate(endpoints):
        ip, port, protocol = values(entry)
        if not before[i]:
            verdict = {"mode":"UNKNOWN", "scope":"END_TO_END",
                       "router_verified":False, "reason":"local_route_unverified"}
        else:
            verdict = reasoned(ip, port, protocol, pi_ip, local_interface,
                               router_gateway, snapshot)
            if not local_check(ip, pi_ip, local_interface, router_gateway):
                verdict = {"mode":"UNKNOWN", "scope":"END_TO_END",
                           "router_verified":False,
                           "reason":"pi_route_changed_during_audit"}
        verdict["checked_at"] = checked_at
        verdict["valid_for_seconds"] = 30 if verdict["router_verified"] else 0
        if isinstance(ip,str) and isinstance(port,int) and isinstance(protocol,str):
            digest = hashlib.sha256(
                f"{ip}|{port}|{protocol}|{pi_ip}|{router_gateway}".encode())
            verdict["endpoint_binding_sha256"] = digest.hexdigest()
        result.append(verdict)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--protocol", required=True, choices=("tcp", "udp"))
    parser.add_argument("--pi-ip", required=True)
    parser.add_argument("--local-interface", required=True)
    parser.add_argument("--router-gateway", required=True)
    parser.add_argument("--ssh-alias", default="mikrotik-gpt")
    args = parser.parse_args()
    try:
        result = attest_ip(args.ip, args.port, args.protocol,
                           args.pi_ip, args.local_interface,
                           args.router_gateway, ssh_alias=args.ssh_alias)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        result = {"mode": "UNKNOWN", "scope": "END_TO_END",
                  "router_verified": False, "reason": "router_audit_unavailable"}
    # Only a narrow summary, never raw firewall rules or credentials.
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("router_verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
