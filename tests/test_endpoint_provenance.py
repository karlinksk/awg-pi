#!/usr/bin/env python3
"""Offline route provenance tests: Pi local route != end-to-end DIRECT."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "src" / "awg-endpoint-provenance.py"
spec = importlib.util.spec_from_file_location("awg_endpoint_provenance", PATH)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def node(ip="194.38.11.86", **kwargs):
    return {"name": "test", "server": ip, "type": "ss", "port": 443, **kwargs}


def route(ip):
    return f"{ip} via 192.168.112.1 dev eth0 src 192.168.112.34 uid 1000\n cache\n"


class ProvenanceTests(unittest.TestCase):
    def test_pi_local_eth0_cannot_prove_router_is_direct(self):
        result = m.classify(node(), route_get=route)
        self.assertEqual(result["mode"], "DIRECT_LOCAL_UNVERIFIED")
        self.assertFalse(result["router_verified"])
        self.assertFalse(m.proved_direct(result))

    def test_real_awg_underlay_is_assisted(self):
        result = m.classify(node(), route_get=lambda ip: f"{ip} dev awg0 src 10.8.1.2")
        self.assertEqual(result["mode"], "ASSISTED_AWG")
        self.assertFalse(m.proved_direct(result))

    def test_mihomo_proxy_recursive_path_blocked(self):
        result = m.classify(node(), route_get=lambda ip: f"{ip} dev mihomo0")
        self.assertEqual(result["mode"], "ASSISTED_MIHOMO")

    def test_declared_dialer_proxy_is_assisted_even_if_route_eth0(self):
        result = m.classify(node(**{"dialer-proxy": "another-node"}), route_get=route)
        self.assertEqual(result["mode"], "ASSISTED_MIHOMO")

    def test_domain_endpoint_requires_separate_dns_proof(self):
        result = m.classify(node("example.org"), route_get=lambda _: self.fail("no DNS"))
        self.assertEqual((result["mode"], result["reason"]),
                         ("UNKNOWN", "endpoint_requires_dns_validation"))

    def test_public_ipv6_is_unknown(self):
        self.assertEqual(m.classify(node("2001:4860:4860::8888"))["mode"], "UNKNOWN")

    def test_private_loopback_cgnat_ip_disallowed(self):
        for address in ("10.0.0.1", "127.0.0.1", "192.168.112.1", "100.64.12.1"):
            self.assertEqual(m.classify(node(address))["mode"], "UNKNOWN")

    def test_unexpected_gateway_cannot_be_direct(self):
        result = m.classify(node(), route_get=lambda ip: f"{ip} via 10.77.77.1 dev eth0")
        self.assertEqual(result["mode"], "UNKNOWN")

    def test_route_get_error_is_unknown(self):
        result = m.classify(node(), route_get=lambda ip: (_ for _ in ()).throw(OSError()))
        self.assertEqual(result["mode"], "UNKNOWN")

    def test_ambiguous_multiple_interfaces_refused(self):
        result = m.classify(node(), route_get=lambda ip:
                            f"{ip} via 192.168.112.1 dev eth0 dev awg0")
        self.assertEqual(result["mode"], "UNKNOWN")

    def test_explicit_vpn_interface_refused(self):
        result = m.classify(node(**{"interface-name": "awg0"}), route_get=route)
        self.assertEqual(result["mode"], "ASSISTED_AWG")

    def test_proved_direct_requires_end_to_end_router_attestation(self):
        partial = m.classify(node(), route_get=route)
        forged = dict(partial, mode="DIRECT")
        self.assertFalse(m.proved_direct(forged))
        forged.update(scope="END_TO_END", reason="router_underlay_verified",
                      router_verified=True)
        self.assertTrue(m.proved_direct(forged))

    def test_injected_route_never_executes_shell(self):
        with patch.object(m.subprocess, "run", side_effect=AssertionError("no shell")):
            self.assertEqual(m.classify(node(), route_get=route)["mode"],
                             "DIRECT_LOCAL_UNVERIFIED")

    def test_route_parser_rejects_bogus_answer(self):
        for bad in ("", "unreachable 1.2.3.4", "1.2.3.4 dev",
                    "1.2.3.4 dev eth0 dev tun0"):
            with self.assertRaises(ValueError):
                m.route_tokens(bad)


if __name__ == "__main__":
    unittest.main()
