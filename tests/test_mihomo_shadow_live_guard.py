#!/usr/bin/env python3
"""Offline live-underlay safety regression. Never launches Mihomo or accesses the network."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SMART = ROOT / "src/awg-mihomo-smart"
loader = importlib.machinery.SourceFileLoader("shadow_guard_review_smart", str(SMART))
spec = importlib.util.spec_from_loader(loader.name, loader)
smart = importlib.util.module_from_spec(spec)
loader.exec_module(smart)

LIVE = {"name": "vless-active", "server": "77.110.105.122", "port": 443}
ALIAS = {"name": "alias", "server": "77.110.105.122", "port": 8443}
OTHER = {"name": "vless-other", "server": "45.86.66.170", "port": 443}


class ShadowLiveGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="shadow-guard-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.transport = root / "transport"
        self.node = root / "node-name"
        self.endpoint = root / "endpoint-ip"
        self.health = root / "health.state"
        self.transport.write_text("mihomo\n")
        self.node.write_text("vless-active\n")
        self.endpoint.write_text("77.110.105.122\n")
        self.health.write_text("up\n")

    def guard(self, candidate, provider=None):
        return smart.shadow_guard_reason(
            candidate, provider or [LIVE, ALIAS, OTHER],
            transport_file=self.transport, node_file=self.node,
            endpoint_file=self.endpoint, health_file=self.health)

    def test_current_node_rejected(self):
        self.assertEqual(self.guard(LIVE), "ACTIVE_NODE")

    def test_alias_same_server_other_port_rejected(self):
        self.assertEqual(self.guard(ALIAS), "ACTIVE_ENDPOINT")

    def test_distinct_server_is_safe_only_when_live_up(self):
        self.assertIsNone(self.guard(OTHER))
        self.health.write_text("down\n")
        self.assertEqual(self.guard(OTHER), "LIVE_NOT_HEALTHY")
        self.health.write_text("unknown\n")
        self.assertEqual(self.guard(OTHER), "LIVE_NOT_HEALTHY")

    def test_refresh_removed_active_name_fails_closed(self):
        self.assertEqual(self.guard(OTHER, [OTHER]), "LIVE_IDENTITY_UNKNOWN")
        self.assertEqual(self.guard(ALIAS, [OTHER]), "ACTIVE_ENDPOINT")

    def test_missing_live_files_fail_closed(self):
        self.endpoint.unlink()
        self.assertEqual(self.guard(OTHER), "LIVE_IDENTITY_UNKNOWN")
        self.endpoint.write_text("77.110.105.122\n")
        self.node.unlink()
        self.assertEqual(self.guard(OTHER), "LIVE_IDENTITY_UNKNOWN")

    def test_no_transport_identity_is_not_safe(self):
        self.transport.unlink()
        self.assertEqual(self.guard(OTHER), "LIVE_TRANSPORT_UNKNOWN")
        self.transport.write_text("broken\n")
        self.assertEqual(self.guard(OTHER), "LIVE_TRANSPORT_UNKNOWN")

    def test_awg_transport_does_not_block_independent_mihomo_candidate(self):
        self.transport.write_text("awg\n")
        self.health.unlink()
        self.assertIsNone(self.guard(OTHER))

    def test_casefolded_alias_rejected(self):
        self.endpoint.write_text("EXAMPLE.COM\n")
        self.assertEqual(self.guard(
            {"name": "alias2", "server": "example.com", "port": 9001}),
            "ACTIVE_ENDPOINT")

    def test_undisclosed_secret_never_in_reason(self):
        self.assertNotIn("secret", self.guard({
            "name": "secret", "server": "77.110.105.122",
            "port": 443, "password": "secret"}))

    def test_guard_called_before_shadow_traffic_in_both_scanners(self):
        hot = (ROOT / "extras/mihomo-hot-pool-shadow/awg-mihomo-hot-service-scan.py").read_text()
        source = SMART.read_text()
        self.assertLess(
            hot.index("guard = smart.shadow_guard_reason(matched[0], raw)"),
            hot.index("instance = subprocess.Popen("))
        self.assertLess(
            source.index("require_shadow_safe(matched[0], raw)", source.index("def service_scan(")),
            source.index("instance = subprocess.Popen(", source.index("def service_scan(")))
        shadow = source[source.index("def shadow_scan("):]
        self.assertLess(shadow.index("shadow_guard_reason(matches[0], raw)"),
                        shadow.index("instance = subprocess.Popen("))
        self.assertIn("require_shadow_safe(by_name[node['name']][0], raw)", shadow)


if __name__ == "__main__":
    unittest.main()
