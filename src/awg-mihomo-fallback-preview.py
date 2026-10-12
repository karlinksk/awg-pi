#!/usr/bin/env python3
"""Stage27: generate a RAM-only, TUN-disabled native Mihomo fallback preview.

Does not install, start or switch any production transport, route or service.
"""
import argparse
import copy
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import sys
import yaml


def choose_nodes(provider, names):
    proxies = provider.get("proxies")
    if not isinstance(proxies, list) or not 2 <= len(names) <= 4 or len(names) != len(set(names)):
        raise ValueError("require 2-4 unique explicitly named nodes and valid provider")
    result = []
    for name in names:
        matches = [p for p in proxies if isinstance(p, dict) and p.get("name") == name]
        if len(matches) != 1:
            raise ValueError(f"missing or ambiguous node: {name!r}")
        node = copy.deepcopy(matches[0])
        if node.get("type") != "ss":
            raise ValueError("Stage27 only accepts verified Shadowsocks nodes")
        endpoint = node.get("server")
        try:
            ip = ipaddress.ip_address(endpoint)
        except ValueError as ex:
            raise ValueError("Stage27 requires literal IPv4 endpoints") from ex
        if ip.version != 4 or not ip.is_global:
            raise ValueError("node endpoint must be a public IPv4 address")
        if type(node.get("port")) is not int or not 1 <= node["port"] <= 65535:
            raise ValueError("invalid endpoint port")
        if not isinstance(node.get("password"), str) or not node["password"]:
            raise ValueError("missing Shadowsocks credentials")
        result.append(node)
    return result


def require_direct(endpoint, iface, gateway, route_text):
    first = route_text.splitlines()[0].split() if route_text.strip() else []
    if not first or first[0] != endpoint or "dev" not in first or "via" not in first:
        raise ValueError("no proven DIRECT route")
    try:
        device = first[first.index("dev") + 1]
        next_hop = first[first.index("via") + 1]
    except IndexError as ex:
        raise ValueError("incomplete DIRECT route") from ex
    if device != iface or next_hop != gateway:
        raise ValueError(f"DIRECT route mismatch for {endpoint}: dev={device} via={next_hop}")
    if any(t in first for t in ("awg0", "mihomo0", "tun0")):
        raise ValueError("recursive VPN route")
    return True


def check_routes(nodes, iface, gateway, runner=subprocess.run):
    for node in nodes:
        endpoint = node["server"]
        cmd = ["ip", "-4", "route", "get", endpoint]
        proc = runner(cmd, capture_output=True, text=True, timeout=5)
        if proc.returncode:
            raise ValueError(f"route query failed: {endpoint}")
        require_direct(endpoint, iface, gateway, proc.stdout)


def candidate(base, nodes, *, http_port=17931, controller_port=17932):
    if not isinstance(base, dict) or not isinstance(base.get("rules"), list):
        raise ValueError("invalid Mihomo baseline")
    if "tun" not in base:
        raise ValueError("missing baseline TUN block")
    cfg = copy.deepcopy(base)
    cfg.pop("proxy-providers", None)  # avoid loading all 1838 subscribed nodes
    cfg["proxies"] = nodes
    cfg["proxy-groups"] = [{
        "name": "AWG-MIHOMO", "type": "fallback",
        "proxies": [n["name"] for n in nodes],
        "url": "https://www.gstatic.com/generate_204",
        "interval": 10, "lazy": False,
    }]
    cfg["mixed-port"] = http_port
    cfg["external-controller"] = f"127.0.0.1:{controller_port}"
    cfg["allow-lan"] = False
    cfg["bind-address"] = "127.0.0.1"
    cfg["ipv6"] = False
    cfg["tun"]["enable"] = False
    cfg["tun"]["auto-route"] = False
    cfg["tun"]["auto-redirect"] = False
    cfg.setdefault("profile", {})["store-selected"] = False
    cfg["profile"]["store-fake-ip"] = False
    return cfg


def save_ram_private(path, data):
    path = Path(path)
    if not path.is_absolute() or not path.resolve().is_relative_to(Path("/tmp").resolve()) or path.name in ("", ".", ".."):
        raise ValueError("preview output must be an absolute /tmp path")
    if subprocess.run(["findmnt", "-n", "-o", "FSTYPE", "-T", "/tmp"],
                      capture_output=True, text=True, timeout=5).stdout.strip() != "tmpfs":
        raise ValueError("/tmp is not tmpfs; refusing to write secrets")
    if not path.parent.is_dir():
        raise ValueError("create private output directory first")
    if path.parent.stat().st_mode & 0o077:
        raise ValueError("output directory must be private (0700)")
    content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--node", required=True, action="append", dest="nodes")
    p.add_argument("--iface", required=True)
    p.add_argument("--gateway", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", args.iface):
        p.error("invalid LAN interface")
    try:
        gateway = ipaddress.ip_address(args.gateway)
        if gateway.version != 4:
            raise ValueError("IPv4 gateway required")
        base = yaml.safe_load(Path(args.base).read_text(encoding="utf-8"))
        provider = yaml.safe_load(Path(args.provider).read_text(encoding="utf-8"))
        nodes = choose_nodes(provider, args.nodes)
        check_routes(nodes, args.iface, str(gateway))
        cfg = candidate(base, nodes)
        save_ram_private(args.output, cfg)
        print(f"STAGE27_SHADOW_READY nodes={len(nodes)} routes=DIRECT_VERIFIED tun=OFF providers=INLINE_ONLY")
    except (ValueError, OSError, yaml.YAMLError, subprocess.TimeoutExpired) as ex:
        print(f"STAGE27_REJECTED: {ex}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
