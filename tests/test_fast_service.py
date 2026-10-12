#!/usr/bin/env python3
"""Offline fast-region sensor and no-route-write tests."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / "src" / "awg-fast-service.py"
spec = importlib.util.spec_from_file_location("awg_fast_service", FILE)
fast = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fast
spec.loader.exec_module(fast)


def proof(region="REGION_BLOCKED", sample="sample1", t=1000):
    return {"region": region, "reason": "fixture",
            "sample_id": sample, "checked_at": t, "monotonic_ms": t*1000}


class FastServiceTests(unittest.TestCase):
    def test_block_first_not_enough_second_is_urgent(self):
        with patch.object(fast, "boot_id", return_value="boot1"):
            one = fast.update(proof(sample="probeA"), {}, "node1")
            two = fast.update(proof(sample="probeB"), one, "node1")
        self.assertEqual(one["consecutive_blocks"], 1)
        self.assertFalse(one["urgent_service_confirmation"])
        self.assertEqual(two["consecutive_blocks"], 2)
        self.assertTrue(two["urgent_service_confirmation"])
        self.assertEqual(two["mode"], "ADVISORY_ONLY")

    def test_api_ok_clears_previous_block(self):
        with patch.object(fast, "boot_id", return_value="boot1"):
            previous = fast.update(proof(), {}, "node1")
            new = fast.update(proof("API_REGION_OK", "ok2"), previous, "node1")
        self.assertEqual(new["consecutive_blocks"], 0)
        self.assertFalse(new["urgent_service_confirmation"])

    def test_unknown_does_not_become_pass(self):
        with patch.object(fast, "boot_id", return_value="boot1"):
            previous = fast.update(proof(), {}, "node1")
            new = fast.update(proof("UNKNOWN", "timeout"), previous, "node1")
        self.assertEqual(new["consecutive_blocks"], 0)
        self.assertEqual(new["region"], "UNKNOWN")

    def test_node_change_resets_streak(self):
        with patch.object(fast, "boot_id", return_value="boot1"):
            previous = fast.update(proof(), {}, "node1")
            new = fast.update(proof(sample="probe2"), previous, "node2")
        self.assertEqual(new["consecutive_blocks"], 1)

    def test_reboot_resets_streak(self):
        with patch.object(fast, "boot_id", return_value="boot1"):
            prev = fast.update(proof(), {}, "node1")
        with patch.object(fast, "boot_id", return_value="boot2"):
            new = fast.update(proof(sample="other"), prev, "node1")
        self.assertEqual(new["consecutive_blocks"], 1)

    def test_duplicate_evidence_not_accepted_as_second(self):
        with patch.object(fast, "boot_id", return_value="boot1"):
            prev = fast.update(proof(), {}, "node1")
            new = fast.update(proof(), prev, "node1")
        self.assertFalse(new["urgent_service_confirmation"])

    def test_quick_probe_blocked_region_is_not_automatic_failover(self):
        m = fast.service_code()
        payload = fast.quick_probe(request=lambda url, **k: (
            403, b'{"error":{"code":"unsupported_country_region_territory"}}', url))
        self.assertEqual(payload["region"], "REGION_BLOCKED")
        self.assertNotIn("action", payload)
        self.assertEqual(len(payload["sample_id"]), 32)

    def test_api_auth_not_full_service_eligibility(self):
        payload = fast.quick_probe(request=lambda url, **k: (401, b"unauthorized", url))
        self.assertEqual(payload["region"], "API_REGION_OK")
        self.assertNotIn("service_eligible", payload)

    def test_other_http_response_unknown(self):
        payload = fast.quick_probe(request=lambda url, **k: (502, b"bad", url))
        self.assertEqual(payload["region"], "UNKNOWN")

    def test_reader_suppresses_when_awg_active(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp:
            node = Path(tmp)/"node"; node.write_text("node1")
            trans = Path(tmp)/"transport"; trans.write_text("awg")
            self.assertEqual(fast.read_identity(node, trans), "")
            trans.write_text("mihomo")
            self.assertEqual(fast.read_identity(node, trans), "node1")

    def test_no_direct_when_active_changed_mid_sample(self):
        it = iter(["nodeA", "nodeB"])
        called = []
        result = fast.scan(read_node=lambda: next(it),
                           probe=lambda **kw: (called.append("once") or proof()),
                           path=Path("/run/awg-pbr/service-fast/test.json"))
        self.assertEqual(result["reason"], "node_changed_during_probe")
        self.assertEqual(called, ["once"])

    def test_no_active_probes_are_skipped(self):
        def fail(**kwargs):
            self.fail("probe must not run")
        result = fast.scan(read_node=lambda: "", probe=fail)
        self.assertEqual(result["region"], "UNKNOWN")
        self.assertFalse(result["urgent_service_confirmation"])

    def test_interval_adapts_without_speed_tests(self):
        self.assertEqual(fast.interval("REGION_BLOCKED"), 10)
        self.assertEqual(fast.interval("API_REGION_OK"), 20)
        self.assertEqual(fast.interval("UNKNOWN", 3), 120)

    def test_watch_polls_without_route_changes(self):
        calls, waits = [], []
        fast.watch(poll=lambda: (calls.append("p") or proof("REGION_BLOCKED")),
                   sleeper=waits.append, cycles=3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(waits, [10, 10])

    def test_unsupported_persistent_path_rejected(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp:
            with self.assertRaises(ValueError):
                fast.atomic(Path(tmp)/"wrong.json", {})


if __name__ == "__main__":
    unittest.main()
