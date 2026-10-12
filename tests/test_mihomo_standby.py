#!/usr/bin/env python3
"""No-network tests for rolling Hot Standby on the Pi's RAM workspace."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "src" / "awg-mihomo-standby.py"
spec = importlib.util.spec_from_file_location("awg_mihomo_standby", PATH)
standby = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = standby
spec.loader.exec_module(standby)


TEST_ROUTER_PROOF = {
    "mode": "DIRECT", "scope": "END_TO_END",
    "reason": "router_underlay_verified", "router_verified": True
}


def node(n, *, delay=10, server=None):
    return {"name": f"node-{n}", "type": "ss", "server": server or f"192.0.2.{n}",
            "port": 443, "delay_ms": delay + n, "healthy": True, "index": n}


class StandbyTests(unittest.TestCase):
    def test_windows_rotate_beyond_initial_ten(self):
        nodes = [node(i) for i in range(1, 26)]
        first, cursor = standby.choose_window(nodes, 0, 10)
        second, cursor = standby.choose_window(nodes, cursor, 10)
        third, _ = standby.choose_window(nodes, cursor, 10)
        self.assertEqual([n["name"] for n in first], [f"node-{i}" for i in range(1, 11)])
        self.assertEqual([n["name"] for n in second], [f"node-{i}" for i in range(11, 21)])
        self.assertEqual([n["name"] for n in third], [f"node-{i}" for i in range(21, 26)] +
                         [f"node-{i}" for i in range(1, 6)])

    def test_warm_nodes_kept_in_rotation(self):
        nodes = [node(i) for i in range(1, 21)]
        choice, cursor = standby.choose_window(nodes, 10, 10, ["node-1", "node-8"])
        self.assertEqual([n["name"] for n in choice[:2]], ["node-1", "node-8"])
        self.assertEqual(len(choice), 10)
        self.assertEqual(cursor, 18)

    def test_duplicate_names_and_endpoints_are_not_warm(self):
        n1, n2, n3, n4 = node(1), node(2), node(3), node(4, server="192.0.2.3")
        n2["name"] = n1["name"]
        nodes = [n1, n2, n3, n4]
        chosen, _ = standby.choose_window(nodes, 0, 10)
        self.assertEqual([n["name"] for n in chosen], ["node-3", "node-4"])
        t = int(time.time())
        entries = {n["name"]: {"status": "PASS", "checked_at": t,
                                "fingerprint": standby.fingerprint(n),
                                "underlay": dict(TEST_ROUTER_PROOF)} for n in nodes}
        self.assertEqual(standby.qualified_spares(entries, nodes, t), ["node-3"])

    def test_cache_invalidation_time_endpoint_and_identity(self):
        n = node(4)
        current = int(time.time())
        entry = {"status": "PASS", "checked_at": current,
                 "fingerprint": standby.fingerprint(n)}
        self.assertTrue(standby.fresh_entry(entry, n, current))
        self.assertFalse(standby.fresh_entry(entry, n, current + 181))
        self.assertFalse(standby.fresh_entry(entry, n, current - 1))
        changed = dict(n, server="198.51.100.77")
        self.assertFalse(standby.fresh_entry(entry, changed, current))

    def test_provider_hash_and_policy_invalidate_cache(self):
        state = {"version": 1, "provider_sha256": "old",
                 "region": "all", "protocol": "ss", "entries": {"a": {}}}
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp:
            path = Path(tmp) / "state.json"
            standby.atomic_state(path, state)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(standby.read_state(path, "old", "all", "ss"))
            self.assertEqual(standby.read_state(path, "new", "all", "ss"), {})
            self.assertEqual(standby.read_state(path, "old", "europe", "ss"), {})
            self.assertEqual(standby.read_state(path, "old", "all", "vless"), {})

    def test_adaptive_checks_back_off_during_outage(self):
        self.assertEqual(standby.adaptive_interval(2, 0), 120)
        self.assertEqual(standby.adaptive_interval(0, 0), 30)
        self.assertEqual(standby.adaptive_interval(0, 1), 30)
        self.assertEqual(standby.adaptive_interval(0, 3), 120)
        self.assertEqual(standby.adaptive_interval(0, 8), 600)

    def test_pass_without_verified_underlay_does_not_become_warm(self):
        n = node(1)
        now = int(time.time())
        row = {"status": "PASS", "checked_at": now,
               "fingerprint": standby.fingerprint(n),
               "underlay": {"mode": "DIRECT_LOCAL_UNVERIFIED",
                            "scope": "PI_ONLY", "router_verified": False}}
        self.assertEqual(standby.qualified_spares({n["name"]: row}, [n], now), [])

    def test_no_false_positive_on_unknown(self):
        now = int(time.time())
        n1, n2 = node(1), node(2)
        rows = {
            n1["name"]: {"status": "UNKNOWN", "checked_at": now,
                         "fingerprint": standby.fingerprint(n1)},
            n2["name"]: {"status": "FAIL", "checked_at": now,
                         "fingerprint": standby.fingerprint(n2)},
        }
        self.assertEqual(standby.qualified_spares(rows, [n1, n2], now), [])

    def test_scan_with_mocked_proxy_does_not_change_live_routing(self):
        nodes = [node(i) for i in range(1, 16)]
        raw = [{"name": n["name"], "type": n["type"],
                "server": n["server"], "port": n["port"]} for n in nodes]
        t = int(time.time())
        fake_smart = types.SimpleNamespace(
            fresh_pool=lambda pool, path, age: True,
            eligible=lambda pool, **kw: list(nodes),
            load_pool_code=lambda: fake_helper,
            load_service_code=lambda: object())
        fake_helper = types.SimpleNamespace(
            read_policy_values=lambda: ("all", "all"),
            read_provider=lambda path: raw,
            load_cooldown=lambda: {})
        inspected = []
        def mock_probe(chosen, raw_provider, helper, service, *, timeout, deadline):
            inspected.append([n["name"] for n in chosen])
            return {n["name"]: {
                "status": "PASS" if n["name"] in ("node-2", "node-4") else "UNKNOWN",
                "underlay": dict(TEST_ROUTER_PROOF),
                "transport": "mihomo",
                "identity": n["name"],
                "sample_id": "test-" + n["name"] + "-" + str(len(inspected)),
                "checks": {key: {"state": ("PASS" if n["name"] in ("node-2", "node-4")
                                            else "UNKNOWN"), "reason": "mock"}
                           for key in ("openai_api", "chatgpt_web", "youtube_video")}
            } for n in chosen}
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp, \
             patch.object(standby.os, "geteuid", return_value=0), \
             patch.object(standby, "load_module", return_value=fake_smart):
            root = Path(tmp)
            provider = root / "provider.yaml"
            provider.write_text("fixture only")
            pool = root / "pool.json"
            pool.write_text(json.dumps({"provider_sha256": "hash", "scanned_at": t}))
            state_path = root / "standby" / "state.json"
            first = standby.scan(pool_file=pool, provider_file=provider,
                                 state_file=state_path, perform_probe=mock_probe)
            self.assertEqual(first["candidate_cap"], 10)
            self.assertEqual(first["tested"], 10)
            self.assertEqual(first["warm"], ["node-2", "node-4"])
            self.assertEqual(first["mode"], "SHADOW_ONLY")
            self.assertEqual(first["entries"]["node-2"]["identity"], "node-2")
            self.assertEqual(first["entries"]["node-2"]["transport"], "mihomo")
            self.assertEqual(first["entries"]["node-2"]["checks"]["youtube_video"]["state"], "PASS")
            self.assertNotIn("password", state_path.read_text())
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
            second = standby.scan(pool_file=pool, provider_file=provider,
                                  state_file=state_path, perform_probe=mock_probe)
            self.assertEqual(inspected[1][:2], ["node-2", "node-4"])
            self.assertIn("node-11", inspected[1])
            self.assertEqual(second["candidate_cap"], 10)
            self.assertEqual(len(inspected[1]), 10)

    def test_expired_status_not_advertised_as_ready(self):
        t = int(time.time())
        n = node(1)
        state = {"version": 1, "mode": "SHADOW_ONLY",
                 "generated_at": t-200, "ttl_seconds": 120,
                 "warm": [n["name"]],
                 "entries": {n["name"]: {"status": "PASS", "checked_at": t-200}}}
        self.assertEqual(standby.report(state)["status"], "STALE")
        self.assertEqual(standby.report(state)["warm"], [])

    def test_next_scan_respects_oldest_warm_cache_ttl(self):
        t = int(time.time())
        entries = {"A": {"checked_at": t-120}, "B": {"checked_at": t-10}}
        self.assertEqual(standby.next_interval(entries, ["A", "B"], t, 180, 0), 45)
        self.assertEqual(standby.next_interval(entries, [], t, 180, 2), 60)

    def test_watch_uses_adaptive_interval_and_does_not_switch_transport(self):
        waits, scanned = [], []
        def scan_stub():
            scanned.append("scan")
            return {"mode": "SHADOW_ONLY", "generated_at": int(time.time()),
                    "ttl_seconds": 180, "warm": [],
                    "suggested_interval_seconds": 45}
        standby.watch(scanner=scan_stub, sleeper=waits.append, max_cycles=2)
        self.assertEqual(scanned, ["scan", "scan"])
        self.assertEqual(waits, [45])

    def test_watch_recovers_from_probe_errors_without_stop_restart(self):
        waits, calls = [], []
        def scan_stub():
            calls.append("probe")
            if len(calls) <= 2:
                raise RuntimeError("offline")
            return {"mode": "SHADOW_ONLY", "generated_at": int(time.time()),
                    "ttl_seconds": 180, "warm": [],
                    "suggested_interval_seconds": 120}
        standby.watch(scanner=scan_stub, sleeper=waits.append, max_cycles=3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(waits, [30, 60])

    def test_no_candidates_does_not_launch_probe_instance(self):
        fake_helper = types.SimpleNamespace(
            read_policy_values=lambda: ("all", "all"),
            read_provider=lambda path: [],
            load_cooldown=lambda: {})
        fake_smart = types.SimpleNamespace(
            fresh_pool=lambda pool, path, age: True,
            eligible=lambda pool, **kw: [],
            load_pool_code=lambda: fake_helper, load_service_code=lambda: object())
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp, \
             patch.object(standby.os, "geteuid", return_value=0), \
             patch.object(standby, "load_module", return_value=fake_smart):
            root = Path(tmp)
            (root/"provider").write_text("fixture")
            (root/"pool").write_text(json.dumps(
                {"provider_sha256": "hash", "scanned_at": int(time.time())}))
            state = standby.scan(pool_file=root/"pool", provider_file=root/"provider",
                                 state_file=root/"state"/"cache.json",
                                 perform_probe=lambda *args, **kw: self.fail("unwanted probe"))
            self.assertEqual(state["tested"], 0)
            self.assertEqual(state["warm"], [])


if __name__ == "__main__":
    unittest.main()
