#!/usr/bin/env python3
import argparse
import base64
import binascii
import ipaddress
import json
import re
import socket
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

MAX_PROVIDER_BYTES = 32 * 1024 * 1024
REGEX_META = re.compile(r'([\\.^$|?*+(){}\[\]])')
SUPPORTED_FORMATS = ("auto", "mihomo", "vless", "base64")


def die(message: str, code: int = 2) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def read_text(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        die(f"Provider input is not a regular file: {path}")
    size = p.stat().st_size
    if size <= 0 or size > MAX_PROVIDER_BYTES:
        die(f"Provider input size is invalid: {size}")
    try:
        return p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        die(f"Unable to read provider input: {exc}")


def parse_mihomo_text(text: str):
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    proxies = data.get("proxies")
    if not isinstance(proxies, list) or not proxies:
        return None
    for index, proxy in enumerate(proxies, start=1):
        safe_proxy(proxy, index)
    return proxies


def load_provider(path: str):
    proxies = parse_mihomo_text(read_text(path))
    if proxies is None:
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


def first_query(query, *names, default=""):
    for name in names:
        values = query.get(name)
        if values:
            return values[0]
    return default


def bool_query(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def parse_vless_uri(uri: str, index: int):
    try:
        parts = urlsplit(uri.strip())
    except ValueError as exc:
        die(f"Invalid VLESS URI #{index}: {exc}")
    if parts.scheme.lower() != "vless":
        die(f"Unsupported subscription URI scheme in item #{index}: {parts.scheme or 'missing'}")
    try:
        host = parts.hostname
        port = parts.port
    except ValueError:
        die(f"VLESS URI #{index} has an invalid server/port")
    if not parts.username or parts.password is not None or not host or port is None:
        die(f"VLESS URI #{index} must include UUID, server and port")

    raw_uuid = unquote(parts.username)
    try:
        parsed_uuid = str(uuid.UUID(raw_uuid))
    except ValueError:
        die(f"VLESS URI #{index} has an invalid UUID")

    try:
        port = int(port)
    except (TypeError, ValueError):
        die(f"VLESS URI #{index} has an invalid port")
    if not (1 <= port <= 65535):
        die(f"VLESS URI #{index} has an invalid port")

    query = parse_qs(parts.query, keep_blank_values=True)
    encryption = first_query(query, "encryption", default="none").lower()
    if encryption not in ("", "none"):
        die(f"VLESS URI #{index} uses unsupported encryption={encryption!r}")

    network = first_query(query, "type", "network", default="tcp").lower()
    if network in ("", "none"):
        network = "tcp"
    if network not in ("tcp", "ws", "grpc"):
        die(f"VLESS URI #{index} uses unsupported transport type={network!r}")

    security = first_query(query, "security", default="none").lower()
    if security in ("", "none"):
        security = "none"
    if security not in ("none", "tls", "reality"):
        die(f"VLESS URI #{index} uses unsupported security={security!r}")

    name = unquote(parts.fragment).strip() or f"VLESS {host}:{port}"
    if any(ch in name for ch in "\r\n\t"):
        die(f"VLESS URI #{index} has an invalid display name")

    proxy = {
        "name": name,
        "type": "vless",
        "server": host,
        "port": port,
        "uuid": parsed_uuid,
        "network": network,
        "udp": True,
    }

    flow = first_query(query, "flow")
    if flow:
        proxy["flow"] = flow

    packet_encoding = first_query(query, "packetEncoding", "packet-encoding")
    if packet_encoding:
        proxy["packet-encoding"] = packet_encoding

    if security in ("tls", "reality"):
        proxy["tls"] = True
        sni = first_query(query, "sni", "servername")
        if sni:
            proxy["servername"] = sni
        fingerprint = first_query(query, "fp", "fingerprint")
        if fingerprint:
            proxy["client-fingerprint"] = fingerprint
        alpn = first_query(query, "alpn")
        if alpn:
            proxy["alpn"] = [item for item in alpn.split(",") if item]
        insecure = first_query(query, "allowInsecure", "insecure")
        if insecure:
            proxy["skip-cert-verify"] = bool_query(insecure)

    if security == "reality":
        public_key = first_query(query, "pbk", "publicKey", "public-key")
        if not public_key:
            die(f"VLESS Reality URI #{index} is missing pbk/publicKey")
        reality = {"public-key": public_key}
        short_id = first_query(query, "sid", "shortId", "short-id")
        if short_id:
            reality["short-id"] = short_id
        proxy["reality-opts"] = reality

    if network == "ws":
        ws = {}
        path = first_query(query, "path")
        if path:
            ws["path"] = unquote(path)
        host = first_query(query, "host")
        if host:
            ws["headers"] = {"Host": host}
        if ws:
            proxy["ws-opts"] = ws
    elif network == "grpc":
        service = first_query(query, "serviceName", "service-name", "grpc-service-name")
        if service:
            proxy["grpc-opts"] = {"grpc-service-name": service}

    return proxy


def parse_vless_text(text: str):
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    if not lines:
        return None
    if not all(line.lower().startswith("vless://") for line in lines):
        return None
    return [parse_vless_uri(line, idx) for idx, line in enumerate(lines, start=1)]


def decode_base64_text(text: str):
    compact = "".join(text.split())
    if not compact:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]+", compact):
        return None
    padded = compact + ("=" * (-len(compact) % 4))
    candidates = []
    try:
        candidates.append(base64.b64decode(padded, validate=True))
    except (binascii.Error, ValueError):
        pass
    try:
        candidates.append(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError):
        pass
    for raw in candidates:
        if not raw or len(raw) > MAX_PROVIDER_BYTES:
            continue
        try:
            decoded = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        if parse_vless_text(decoded) is not None:
            return decoded
    return None


def normalize_provider(text: str, requested_format: str):
    if requested_format not in SUPPORTED_FORMATS:
        die(f"Unsupported provider format: {requested_format}")

    if requested_format in ("auto", "mihomo"):
        proxies = parse_mihomo_text(text)
        if proxies is not None:
            return "mihomo", proxies
        if requested_format == "mihomo":
            die("Input is not a Mihomo/Clash YAML provider with a non-empty proxies list")

    if requested_format in ("auto", "vless"):
        proxies = parse_vless_text(text)
        if proxies is not None:
            return "vless", proxies
        if requested_format == "vless":
            die("Input is not a plain VLESS URI subscription")

    if requested_format in ("auto", "base64"):
        decoded = decode_base64_text(text)
        if decoded is not None:
            proxies = parse_vless_text(decoded)
            if proxies is None:
                die("Decoded base64 subscription does not contain VLESS URIs")
            return "base64", proxies
        if requested_format == "base64":
            die("Input is not a supported base64 VLESS subscription")

    die("Unable to detect provider format. Supported: Mihomo YAML, VLESS URI list, base64 VLESS subscription")


def write_normalized(path: str, proxies):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = yaml.safe_dump(
            {"proxies": proxies},
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        output.write_text(text, encoding="utf-8")
    except (OSError, yaml.YAMLError) as exc:
        die(f"Unable to write normalized provider: {exc}")


def cmd_normalize(args):
    detected, proxies = normalize_provider(read_text(args.input), args.format)
    write_normalized(args.output, proxies)
    print(f"MIHOMO_PROVIDER_FORMAT_DETECTED={detected}")
    print(f"MIHOMO_PROVIDER_NODE_COUNT={len(proxies)}")


def cmd_detect(args):
    detected, proxies = normalize_provider(read_text(args.input), args.format)
    print(f"format={detected}")
    print(f"nodes={len(proxies)}")


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
    parser = argparse.ArgumentParser(description="Mihomo provider adapter and safe metadata reader")
    sub = parser.add_subparsers(dest="command", required=True)

    p_normalize = sub.add_parser("normalize")
    p_normalize.add_argument("input")
    p_normalize.add_argument("output")
    p_normalize.add_argument("--format", choices=SUPPORTED_FORMATS, default="auto")
    p_normalize.set_defaults(func=cmd_normalize)

    p_detect = sub.add_parser("detect")
    p_detect.add_argument("input")
    p_detect.add_argument("--format", choices=SUPPORTED_FORMATS, default="auto")
    p_detect.set_defaults(func=cmd_detect)

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
    try:
        main()
    except BrokenPipeError:
        # Normal Unix pipelines such as "candidate list | head" close stdout
        # early. Treat that as successful consumer termination, not a traceback.
        try:
            sys.stdout.close()
        except OSError:
            pass
        raise SystemExit(0)
