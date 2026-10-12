#!/usr/bin/env python3
"""Offline no-network regression tests for interface-bound AWG service checks."""
import importlib.util
import ipaddress
import json
from pathlib import Path
import socket
import struct
import sys
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "src" / "awg-service-probe.py"
spec = importlib.util.spec_from_file_location("awg_service_probe", PATH)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def response_for(ip="142.251.1.1"):
    question = probe.dns_wire_query("chatgpt.com")
    response = bytearray(question)
    struct.pack_into("!H", response, 2, 0x8180)
    struct.pack_into("!H", response, 6, 1)
    response += b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 30, 4)
    response += ipaddress.IPv4Address(ip).packed
    return bytes(response)


class AwgServiceProbeTests(unittest.TestCase):
    def test_dns_response_parsed(self):
        self.assertEqual(probe.dns_answers(response_for(), "chatgpt.com"),
                         ["142.251.1.1"])

    def test_dns_rejects_private_and_malformed(self):
        with self.assertRaises(ValueError):
            probe.dns_answers(response_for("192.168.1.7"), "chatgpt.com")
        with self.assertRaises(ValueError):
            probe.dns_answers(b"bad", "chatgpt.com")
        buf = bytearray(response_for())
        struct.pack_into("!H", buf, 0, 77)
        with self.assertRaises(ValueError):
            probe.dns_answers(bytes(buf), "chatgpt.com")

    def test_domain_and_interface_validation(self):
        self.assertEqual(probe.validate_interface("awg0"), "awg0")
        for iface in ("", "lo", "a/b", "eth0", "eth0\n", "tooooooooo-long-interface"):
            with self.assertRaises(ValueError):
                probe.validate_interface(iface)
        with self.assertRaises(ValueError):
            probe.dns_wire_query("invalid..name")

    def test_dns_uses_only_pinned_https_resolvers(self):
        calls = []
        def get(ip, host, path, interface, timeout, max_bytes, headers):
            calls.append((ip, host, interface, path[:12], headers["Accept"]))
            return 200, response_for(), ""
        with patch.object(probe, "https_get", side_effect=get):
            result = probe.resolve_through_awg("chatgpt.com", "awg0", 2)
        self.assertEqual(result, ["142.251.1.1"])
        self.assertEqual(calls[0][:3], ("8.8.8.8", "dns.google", "awg0"))
        self.assertEqual(calls[0][4], "application/dns-message")

    def test_dns_no_direct_fallback_on_resolver_failure(self):
        seen = []
        def failed(*args):
            seen.append(args[:3])
            raise OSError("unavailable")
        with patch.object(probe, "https_get", side_effect=failed):
            with self.assertRaises(OSError):
                probe.resolve_through_awg("chatgpt.com", "awg0")
        self.assertEqual(len(seen), 2)
        self.assertEqual([call[0] for call in seen], ["8.8.8.8", "9.9.9.9"])

    def test_https_fetch_routes_through_bound_interface(self):
        calls = []
        def dns(host, interface, timeout):
            calls.append(("dns", host, interface))
            return ["142.251.1.1"]
        def get(ip, hostname, path, interface, timeout, max_bytes, headers):
            calls.append(("https", ip, hostname, interface))
            return 200, b"<html>chatgpt</html>", ""
        code, body, final = probe.fetch("awg0", "https://chatgpt.com/",
                                        resolve=dns, get=get)
        self.assertEqual((code, final), (200, "https://chatgpt.com/"))
        self.assertEqual(calls, [("dns", "chatgpt.com", "awg0"),
                                 ("https", "142.251.1.1", "chatgpt.com", "awg0")])

    def test_untrusted_redirect_is_rejected_before_resolve(self):
        calls = []
        def resolver(host, iface, timeout):
            calls.append(host)
            return ["142.251.1.1"]
        def get(*args):
            return 302, b"", "https://127.0.0.1/private"
        with self.assertRaisesRegex(ValueError, "unapproved"):
            probe.fetch("awg0", "https://chatgpt.com/", resolve=resolver, get=get)
        self.assertEqual(calls, ["chatgpt.com"])

    def test_redirect_loop_is_bounded(self):
        calls = []
        def dns(host, iface, timeout):
            calls.append(host)
            return ["142.251.1.1"]
        def get(*args):
            return 302, b"", "/loop"
        with self.assertRaisesRegex(ValueError, "too many redirects"):
            probe.fetch("awg0", "https://chatgpt.com/", resolve=dns, get=get)
        self.assertEqual(len(calls), 3)

    def test_bound_socket_sets_device_before_connect(self):
        ordered = []
        class Socket:
            def settimeout(self, timeout): ordered.append("timeout")
            def setsockopt(self, level, option, value):
                self._bind = option == socket.SO_BINDTODEVICE
                ordered.append(("bind", value))
            def connect(self, target):
                ordered.append("connect")
                self.bound_before_connect = self._bind
            def close(self): ordered.append("close")
        class SSL:
            def wrap_socket(self, raw, server_hostname):
                self.assert_bound = raw.bound_before_connect
                return raw
        raw = Socket()
        with patch.object(probe.socket, "socket", return_value=raw), \
             patch.object(probe.ssl, "create_default_context", return_value=SSL()):
            result = probe.bound_tls("1.1.1.1", "example.com", "awg0", 2)
        self.assertIs(raw, result)
        self.assertEqual(ordered[1], ("bind", b"awg0\x00"))
        self.assertEqual(ordered[2], "connect")

    def test_result_is_attributed_to_interface_with_new_sample_id(self):
        def failed(*args, **kwargs):
            raise OSError("offline")
        a = probe.assess("awg0", request_fn=failed)
        b = probe.assess("awg0", request_fn=failed)
        self.assertEqual(a["identity"], "awg0")
        self.assertNotEqual(a["sample_id"], b["sample_id"])

    def test_block_local_dns_results_even_when_injected(self):
        with self.assertRaises(ValueError):
            probe.fetch("awg0", "https://chatgpt.com/",
                        resolve=lambda *args, **kw: ["127.0.0.1"],
                        get=lambda *args: (200, b"x", ""))

    def test_awkward_network_errors_are_unknown(self):
        def failed(interface, url, *, timeout, **kwargs):
            raise OSError("tun is down")
        result = probe.assess("awg0", request_fn=failed)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["transport"], "awg")
        self.assertTrue(all(x["state"] == "UNKNOWN" for x in result["checks"].values()))

    def test_access_to_openai_not_proof_of_chatgpt(self):
        def response(interface, url, *, timeout, **kw):
            if "api.openai.com" in url:
                return 401, b"unauthorized", url
            if "chatgpt.com" in url:
                return 403, b"Just a moment...", url
            return 200, b"<html></html>", url
        result = probe.assess("awg0", request_fn=response)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["checks"]["openai_api"]["state"], "PASS")
        self.assertEqual(result["checks"]["chatgpt_web"]["state"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
