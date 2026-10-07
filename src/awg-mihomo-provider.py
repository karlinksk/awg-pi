#!/usr/bin/env python3
import argparse
import ipaddress
import json
import re
import socket
import sys
from pathlib import Path

import yaml

MAX_PROVIDER_BYTES = 32 * 1024 * 1024
REGEX_META = re.compile(r'([\\.^$|?*+(){}\[\]])')


def die(message: str, code: int = 2) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def load_provider(path: str):
    p = Path(path)
    if not p.is_file():
        die(f"Provider cache is not a regular file: {path}")
    size = p.stat().st_size
    if size <= 0 or size > MAX_PROVIDER_BYTES:
        die(f"Provider cache size is invalid: {size}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        die(f"Unable to parse provider cache: {exc}")
    if not isinstance(data, dict):
        die("Provider cache top-level YAML must be a mapping")
    proxies = data.get("proxies")
    if not isinstance(proxies, list) or not proxies:
        die("Provider cache does not contain a non-empty proxies list")
    return proxies


def clean_one_line(value, field: str) -> str:
    if not isinstance(value, str) or not value:
        die(f"Proxy {field} must be a non-empty string")
    if "\n" in value or "\r" in value or "\t" in value:
        die(f"Proxy {field} contains unsupported control whitespace")
    return value


def safe_proxy(proxy, index: int):
    if not isinstance(proxy, dict):
        die(f"Proxy #{index} must be a mapping")
    name = clean_one_line(proxy.get("name"), "name")
    ptype = clean_one_line(proxy.get("type"), "type")
    server = clean_one_line(proxy.get("server"), "server")
    port = proxy.get("port")
    if isinstance(port, str) and port.isdigit():
        port = int(port)
    if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
        die(f"Proxy {name!r} has an invalid port")
    return {"index": index, "name": name, "type": ptype, "server": server, "port": port}


def node_filter(name: str) -> str:
    # Go/RE2-compatible exact-match escaping. Do not escape spaces or '-',
    # because Go regexp rejects some Python re.escape() backslash forms.
    return "^" + REGEX_META.sub(r"\\\1", name) + "$"


def resolve_ipv4(server: str, port: int):
    try:
        literal = ipaddress.ip_address(server)
    except ValueError:
        literal = None
    if literal is not None:
        if literal.version != 4:
            die("IPv6-only proxy endpoints are not supported by v1.3 IPv4 transport selection")
        return [str(literal)]

    try:
        infos = socket.getaddrinfo(server, port, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        die(f"Unable to resolve proxy endpoint {server}: {exc}", 1)

    addresses = []
    for info in infos:
        ip = info[4][0]
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        die(f"Proxy endpoint has no IPv4 address: {server}", 1)
    return addresses


def cmd_list(args):
    result = []
    seen_names = set()
    for idx, raw in enumerate(load_provider(args.provider), start=1):
        item = safe_proxy(raw, idx)
        item["duplicate_name"] = item["name"] in seen_names
        seen_names.add(item["name"])
        result.append(item)
    if args.format == "tsv":
        for item in result:
            duplicate = "DUPLICATE" if item["duplicate_name"] else ""
            print(
                item["index"],
                item["name"],
                item["type"],
                f'{item["server"]}:{item["port"]}',
                duplicate,
                sep="\t",
            )
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")


def cmd_info(args):
    matches = []
    for idx, raw in enumerate(load_provider(args.provider), start=1):
        item = safe_proxy(raw, idx)
        if item["name"] == args.name:
            matches.append(item)
    if not matches:
        die(f"Proxy node not found: {args.name}", 1)
    if len(matches) != 1:
        die(f"Proxy node name is not unique: {args.name}", 1)
    item = matches[0]
    item["filter_regex"] = node_filter(item["name"])
    item["endpoint_ips"] = resolve_ipv4(item["server"], item["port"])
    json.dump(item, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Safe Mihomo provider metadata reader")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("provider")
    p_list.add_argument("--format", choices=("json", "tsv"), default="json")
    p_list.set_defaults(func=cmd_list)

    p_info = sub.add_parser("info")
    p_info.add_argument("provider")
    p_info.add_argument("name")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
