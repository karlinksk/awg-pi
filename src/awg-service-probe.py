#!/usr/bin/env python3
"""Read-only AWG service checks using an interface-bound HTTPS transport.

No default resolver, proxy environment, route changes or TUN reconfiguration.
DNS queries travel through the designated AWG interface as HTTPS to pinned
resolver IPs. ALL sockets are bound to that interface before connect.
"""
from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import re
import uuid
import socket
import ssl
import struct
import time
import urllib.parse
from pathlib import Path
import importlib.machinery
import importlib.util

SERVICE_MODULE = Path(__file__).with_name("awg-mihomo-service-check.py")
# Resolvers may be unreachable on some AWG tunnels: report UNKNOWN, never DIRECT.
RESOLVERS = (("dns.google", "8.8.8.8"), ("dns.quad9.net", "9.9.9.9"))
DNS_PATH = "/dns-query"
MAX_DNS_BYTES = 4096
MAX_REDIRECTS = 2


def service_module():
    loader = importlib.machinery.SourceFileLoader("awg_checker_service", str(SERVICE_MODULE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = mod
    loader.exec_module(mod)
    return mod


def validate_interface(interface: str) -> str:
    if not interface or len(interface) > 15 or not all(c.isalnum() or c in "-_." for c in interface):
        raise ValueError("invalid network interface")
    if not re.fullmatch(r"awg[0-9]{1,3}", interface):
        raise ValueError("only AmneziaWG tunnel interfaces are permitted")
    return interface


def bound_tls(ip: str, server_name: str, interface: str, timeout: float):
    """Never make a hostname lookup or a connection without SO_BINDTODEVICE."""
    ipaddress.IPv4Address(ip)
    interface = validate_interface(interface)
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        raw.settimeout(timeout)
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b"\0")
        raw.connect((ip, 443))
        return ssl.create_default_context().wrap_socket(raw, server_hostname=server_name)
    except BaseException:
        raw.close()
        raise


def https_get(ip: str, server_name: str, path: str, interface: str, timeout: float,
              max_bytes: int, extra_headers: dict | None = None) -> tuple[int, bytes, str]:
    if not path.startswith("/") or "\r" in path or "\n" in path:
        raise ValueError("invalid HTTP path")
    if not max_bytes in range(1, 2_000_001):
        raise ValueError("invalid body limit")
    connection = bound_tls(ip, server_name, interface, timeout)
    try:
        headers = {"Host": server_name, "User-Agent": "AWG-Service-Probe/1",
                   "Accept": "*/*", "Connection": "close"}
        if extra_headers:
            for key, value in extra_headers.items():
                if (not isinstance(key, str) or not isinstance(value, str)
                        or not key.replace("-", "").isalnum()
                        or any(c in value for c in "\r\n")):
                    raise ValueError("invalid HTTP header")
                headers[key] = value
        request = ("GET " + path + " HTTP/1.1\r\n" +
                   "".join(f"{k}: {v}\r\n" for k, v in headers.items()) +
                   "\r\n").encode("utf-8")
        connection.sendall(request)
        response = http.client.HTTPResponse(connection)
        response.begin()
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("response too large")
        return response.status, data, response.getheader("Location") or ""
    finally:
        connection.close()


def dns_wire_query(name: str) -> bytes:
    # DNS wire message with fixed ID, one A question and EDNS omitted.
    labels = name.rstrip(".").encode("idna").split(b".")
    if not labels or any(not label or len(label) > 63 for label in labels):
        raise ValueError("invalid DNS name")
    encoded = b"".join(bytes([len(label)]) + label for label in labels) + b"\0"
    return struct.pack("!HHHHHH", 0, 0x0100, 1, 0, 0, 0) + encoded + struct.pack("!HH", 1, 1)


def read_dns_name(packet: bytes, offset: int) -> int:
    # Skip compressed names, without chasing pointers. They are irrelevant
    # to extracting IPv4 address records.
    for _ in range(128):
        if offset >= len(packet):
            raise ValueError("short DNS name")
        length = packet[offset]
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                raise ValueError("short DNS pointer")
            return offset + 2
        if length & 0xC0:
            raise ValueError("invalid DNS compression")
        offset += 1
        if length == 0:
            return offset
        offset += length
    raise ValueError("DNS name too long")


def validate_dns_question(wire: bytes, expected_name: str) -> int:
    """Do not trust a valid-looking answer to a different DNS question."""
    pos = 12
    labels = []
    for _ in range(128):
        if pos >= len(wire):
            raise ValueError("short DNS question name")
        length = wire[pos]
        pos += 1
        if length == 0:
            break
        # Conservative: the echoed question normally has literal labels.
        # Reject pointers here rather than parsing an ambiguous name.
        if length > 63 or pos + length > len(wire):
            raise ValueError("invalid DNS question labels")
        try:
            labels.append(wire[pos:pos+length].decode("ascii").lower())
        except UnicodeDecodeError as exc:
            raise ValueError("invalid DNS question encoding") from exc
        pos += length
    else:
        raise ValueError("DNS question too long")
    if ".".join(labels) != expected_name.rstrip(".").lower():
        raise ValueError("DNS question mismatch")
    if pos + 4 > len(wire):
        raise ValueError("truncated DNS question")
    qtype, qclass = struct.unpack("!HH", wire[pos:pos+4])
    if qtype != 1 or qclass != 1:
        raise ValueError("unexpected DNS question type")
    return pos + 4


def dns_answers(wire: bytes, question: str) -> list[str]:
    if len(wire) < 12:
        raise ValueError("short DNS response")
    ident, flags, qd, an, _, _ = struct.unpack("!HHHHHH", wire[:12])
    if (ident != 0 or flags & 0x8000 == 0 or flags & 0x0200
            or flags & 0xF != 0 or qd != 1 or an > 64):
        raise ValueError("invalid DNS response")
    pos = validate_dns_question(wire, question)
    answers = []
    for _ in range(an):
        pos = read_dns_name(wire, pos)
        if pos + 10 > len(wire):
            raise ValueError("short DNS record")
        typ, cls, _, size = struct.unpack("!HHIH", wire[pos:pos+10])
        pos += 10
        if pos + size > len(wire):
            raise ValueError("short DNS address")
        if typ == 1 and cls == 1 and size == 4:
            ip = str(ipaddress.IPv4Address(wire[pos:pos+4]))
            address = ipaddress.IPv4Address(ip)
            if not (address.is_global and not address.is_multicast):
                raise ValueError("unsafe DNS address")
            answers.append(ip)
        pos += size
    return answers


def resolve_through_awg(host: str, interface: str, timeout: float = 4) -> list[str]:
    query = dns_wire_query(host)
    last_exception = None
    for resolver, ip in RESOLVERS:
        try:
            # DNS queries via DoH have to be delivered over the AWG interface.
            # POST is avoided: wire query encoded in URL-safe Base64.
            import base64
            encoded = base64.urlsafe_b64encode(query).rstrip(b"=").decode("ascii")
            code, data, _ = https_get(
                ip, resolver, DNS_PATH + "?dns=" + encoded,
                interface, timeout, MAX_DNS_BYTES,
                {"Accept": "application/dns-message"})
            if code == 200:
                addresses = dns_answers(data, host)
                if addresses:
                    return addresses
        except (OSError, ValueError, ssl.SSLError) as exc:
            last_exception = exc
    raise OSError("AWG DNS resolution unavailable") from last_exception


def fetch(interface: str, url: str, *, timeout: float = 5,
          headers: dict | None = None, max_bytes: int = 2_000_000,
          resolve=resolve_through_awg, get=https_get) -> tuple[int, bytes, str]:
    gates = service_module()
    validate_interface(interface)
    for _ in range(MAX_REDIRECTS + 1):
        if not gates.allowed_probe_url(url):
            raise ValueError("unapproved URL")
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        candidates = resolve(host, interface, timeout=timeout)
        if not candidates:
            raise OSError("AWG DNS returned no public IPv4")
        last_exception = None
        for ip in candidates[:3]:
            try:
                if not ipaddress.IPv4Address(ip).is_global:
                    raise ValueError("unsafe IP address from DNS")
                status, body, location = get(ip, host, path, interface, timeout, max_bytes, headers)
                break
            except (OSError, TimeoutError, ssl.SSLError) as exc:
                last_exception = exc
        else:
            raise OSError("AWG HTTPS unreachable") from last_exception
        if status not in (301, 302, 303, 307, 308):
            return status, body, url
        if not location:
            raise ValueError("missing redirect target")
        url = urllib.parse.urljoin(url, location)
    raise ValueError("too many redirects")


def assess(interface: str, timeout: float = 5, *,
           request_fn=fetch) -> dict:
    gates = service_module()
    checked = gates.assess(lambda url, **kw: request_fn(
        interface, url, timeout=timeout, **kw))
    checked["transport"] = "awg"
    checked["interface"] = interface
    checked["identity"] = interface
    checked["sample_id"] = uuid.uuid4().hex
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="awg0")
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 10:
        parser.error("timeout must be 1..10 seconds")
    result = assess(validate_interface(args.interface), args.timeout)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
