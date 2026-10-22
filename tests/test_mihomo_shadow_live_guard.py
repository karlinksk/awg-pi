#!/usr/bin/env python3
"""Offline live-underlay safety regression. Never launches Mihomo or accesses the network."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SMART = ROOT / "src/awg-mihomo-smart"
loader = importlib.machinery.SourceFileLoader("shadow_guard_review_smart", str(SMART))
spec = importlib.util.spec_from_loader(loader.name, loader)
smart = importlib.util.module_from_spec(spec)
loader.exec_module(smart)

HOT_SOURCE = ROOT / "extras/mihomo-hot-pool-shadow/awg-mihomo-hot-service-scan.py"
hot_loader = importlib.machinery.SourceFileLoader("shadow_guard_hot_service_scan", str(HOT_SOURCE))
hot_spec = importlib.util.spec_from_loader(hot_loader.name, hot_loader)
hot = importlib.util.module_from_spec(hot_spec)
hot_loader.exec_module(hot)

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
            hot.index("guard = smart.shadow_guard_reason(matched[0], live_guard_profiles(helper))"),
            hot.index("instance = subprocess.Popen("))
        self.assertLess(
            source.index("require_shadow_safe(matched[0], raw)", source.index("def service_scan(")),
            source.index("instance = subprocess.Popen(", source.index("def service_scan(")))
        shadow = source[source.index("def shadow_scan("):]
        self.assertLess(shadow.index("shadow_guard_reason(matches[0], raw)"),
                        shadow.index("instance = subprocess.Popen("))
        self.assertIn("require_shadow_safe(by_name[node['name']][0], raw)", shadow)
        self.assertEqual(hot.count("live_guard_profiles(helper)"), 5)
        self.assertNotIn("smart.require_shadow_safe(matched[0], raw)", hot)

    def canonical_guard(self, candidate, provider_nodes):
        helper = SimpleNamespace(read_provider=lambda path: provider_nodes)
        safe_list = hot.live_guard_profiles(helper, Path(self.tmp.name) / "provider")
        return smart.shadow_guard_reason(
            candidate, safe_list,
            transport_file=self.transport, node_file=self.node,
            endpoint_file=self.endpoint, health_file=self.health)

    def test_unicode_original_identity_survives_hot_aliasing(self):
        original = dict(LIVE, name="🇩🇪 Germany 2 Hysteria2")
        alias = dict(original, name="hot-123456789abc")
        candidate = dict(OTHER, name="hot-reserve")
        self.node.write_text(original["name"])
        # The old, aliased shadow provider cannot identify the live node.
        self.assertEqual(self.guard(candidate, [alias, candidate]), "LIVE_IDENTITY_UNKNOWN")
        # The canonical live provider does, and an unrelated endpoint is safe.
        self.assertIsNone(self.canonical_guard(candidate, [original, OTHER]))
        self.assertEqual(self.canonical_guard(alias, [original, OTHER]), "ACTIVE_ENDPOINT")
        self.assertEqual(
            self.canonical_guard(dict(candidate, server=original["server"], port=8443),
                                 [original, OTHER]),
            "ACTIVE_ENDPOINT")

    def test_live_alias_missing_from_canonical_provider_stays_fail_closed(self):
        self.node.write_text("🇩🇪 Germany 2 Hysteria2")
        self.assertEqual(self.canonical_guard(OTHER, [OTHER]), "LIVE_IDENTITY_UNKNOWN")
        self.assertEqual(self.canonical_guard(OTHER, []), "LIVE_IDENTITY_UNKNOWN")
        self.assertEqual(self.canonical_guard(OTHER, {}), "LIVE_IDENTITY_UNKNOWN")

    def test_canonical_provider_read_failure_cannot_bypass_guard(self):
        def broken(_):
            raise OSError("unavailable canonical provider")
        safe_list = hot.live_guard_profiles(SimpleNamespace(read_provider=broken),
                                             Path(self.tmp.name) / "provider")
        self.assertEqual(safe_list, [])
        self.assertEqual(self.guard(OTHER, safe_list), "LIVE_IDENTITY_UNKNOWN")

    def test_shadow_guard_reloads_canonical_identity_each_time(self):
        unicode_live = dict(LIVE, name="🇩🇪 Germany 2 Hysteria2")
        self.node.write_text(unicode_live["name"])
        calls = [0]
        def changed_provider(_):
            calls[0] += 1
            return [unicode_live] if calls[0] == 1 else [OTHER]
        reader = SimpleNamespace(read_provider=changed_provider)
        path = Path(self.tmp.name) / "provider"
        first = hot.live_guard_profiles(reader, path)
        second = hot.live_guard_profiles(reader, path)
        self.assertIsNone(self.canonical_guard(OTHER, first))
        self.assertEqual(self.canonical_guard(OTHER, second), "LIVE_IDENTITY_UNKNOWN")
        self.assertEqual(calls[0], 2)



if __name__ == "__main__":
    unittest.main()
