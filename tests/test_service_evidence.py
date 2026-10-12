#!/usr/bin/env python3
"""No-network proof that the evidence producer cannot switch routes."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "src" / "awg-service-evidence.py"
spec = importlib.util.spec_from_file_location("awg_service_evidence", PATH)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def sample(transport, identity, status="PASS"):
    states = ["PASS", "PASS", "PASS"] if status == "PASS" else ["FAIL", "PASS", "PASS"]
    return {"transport": transport, "identity": identity, "status": status,
            "sample_id": "fresh-run-001", "checked_at": int(time.time()),
            "checks": {k: {"state": value, "reason": "ok"}
                       for k, value in zip(m.CHECK_NAMES, states)}}


def mock_subprocess(commands, stdout, stderr, check, timeout):
    if "awg-service-probe.py" in commands[1]:
        payload = sample("awg", "awg0")
    elif "awg-mihomo-service-check.py" in commands[1]:
        node = commands[commands.index("--identity")+1]
        payload = sample("mihomo", node, "FAIL")
    else:
        raise AssertionError("unapproved command " + str(commands))
    return types.SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode())


def fixture(active="mihomo"):
    return {"selection": {"mode": "auto", "priority": ["mihomo", "awg"],
                          "auto_failback": False},
            "active": active, "node": "ss-testnode",
            "node_policy": "auto", "provider_sha256": "hash",
            "standby": {}}


class EvidenceTests(unittest.TestCase):
    def test_parse_known_settings(self):
        valid = ("SELECTION_MODE=auto\nSELECTION_PRIMARY=mihomo\n"
                 "SELECTION_ORDER=awg\nSELECTION_AUTO_FAILBACK=1")
        data = m.parse_policy_env(valid)
        self.assertEqual(data, {"mode": "auto", "priority": ["mihomo", "awg"],
                                "auto_failback": True})

    def test_broken_settings_default_manual(self):
        self.assertEqual(m.parse_policy_env("SELECTION_MODE=$(echo hacked)")["mode"],
                         "manual")

    def test_atomic_output_must_be_ram_only(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            with self.assertRaises(ValueError):
                m.atomic_json(Path(directory)/"test.json", {})

    def test_clean_probes_preserve_only_reason_codes(self):
        inp = sample("awg", "awg0")
        inp["private_key"] = "do_not_store"
        result = m.sanitize_probe(inp, "awg", "awg0")
        self.assertNotIn("private_key", result)
        self.assertEqual(result["status"], "PASS")

    def test_fake_pass_with_failed_youtube_is_unknown(self):
        inp = sample("awg", "awg0")
        inp["checks"]["youtube_video"]["state"] = "FAIL"
        self.assertEqual(m.sanitize_probe(inp, "awg", "awg0")["status"], "UNKNOWN")

    def test_misidentified_node_cannot_report_pass(self):
        inp = sample("mihomo", "old-node")
        self.assertEqual(m.sanitize_probe(inp, "mihomo", "new-node")["status"], "UNKNOWN")

    def test_expired_probe_rejected(self):
        inp = sample("awg", "awg0")
        inp["checked_at"] -= 9999
        self.assertEqual(m.sanitize_probe(inp, "awg", "awg0")["status"], "UNKNOWN")

    def test_probe_error_returns_unknown_not_pass(self):
        def err(*args, **kw):
            raise subprocess.TimeoutExpired("fake", 1)
        r = m.run_probe(m.AWG_PROBE, ["--interface", "awg0"],
                        transport="awg", identity="awg0", runner=err)
        self.assertEqual(r["status"], "UNKNOWN")

    def test_provider_digest_mismatch_invalidates_warm(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            provider = root/"provider.yaml"
            provider.write_text("data")
            pool = root/"pool.json"
            pool.write_text(json.dumps({"provider_sha256": "a"*64}))
            self.assertEqual(m.source_sha(pool, provider), "")

    def test_active_mihomo_gets_a_probe_without_changing_router(self):
        with patch.object(m.socket, "if_nameindex", return_value=[(1, "lo"), (2, "awg0")]):
            result = m.collect(config=fixture(), runner=mock_subprocess)
        self.assertEqual(result["service"]["mihomo"]["status"], "FAIL")
        self.assertEqual(result["service"]["awg"]["status"], "PASS")
        self.assertEqual(result["selection"]["mode"], "auto")

    def test_evidence_to_observer_recommends_awg_only_after_second_distinct_failure(self):
        import importlib.util
        observer_path = PATH.with_name("awg-service-observer.py")
        spec = importlib.util.spec_from_file_location("evidence_integration_observer", observer_path)
        observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(observer)
        def runner_factory(seq):
            def runner(commands, **kwargs):
                response = mock_subprocess(commands, **kwargs)
                result = json.loads(response.stdout)
                result["sample_id"] = f"cycle-{seq}-{result['transport']}"
                response.stdout = json.dumps(result).encode("utf-8")
                return response
            return runner
        with patch.object(m.socket, "if_nameindex", return_value=[(1, "lo"), (2, "awg0")]):
            first = m.collect(config=fixture(), runner=runner_factory(1))
            decision1, memory = observer.evaluate_document(first, now=int(time.time()), mono=1000)
            second = m.collect(config=fixture(), runner=runner_factory(2))
            decision2, _ = observer.evaluate_document(second, memory, now=int(time.time()), mono=1012)
        self.assertEqual(decision1["action"], "KEEP")
        self.assertEqual((decision2["action"], decision2["target"]),
                         ("SELECT_TRANSPORT", "awg"))

    def test_double_outage_evidence_never_authorizes_unqualified_awg(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("evidence_obs2", PATH.with_name("awg-service-observer.py"))
        observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(observer)
        def failing(commands, **kwargs):
            if "awg-service-probe.py" in commands[1]:
                data = sample("awg", "awg0", "FAIL")
                return types.SimpleNamespace(returncode=1, stdout=json.dumps(data).encode())
            return mock_subprocess(commands, **kwargs)
        with patch.object(m.socket, "if_nameindex", return_value=[(1, "lo"), (2, "awg0")]):
            snapshot = m.collect(config=fixture(), runner=failing)
        decision, _ = observer.evaluate_document(snapshot, {"mihomo_fails": 1},
                                                 now=int(time.time()), mono=1010)
        self.assertEqual(decision["action"], "RECOVERY_WAIT")
        self.assertEqual(decision["status"], "NO_WORKING_TRANSPORT")

    def test_when_awg_active_production_mihomo_stays_untouched(self):
        calls = []
        def runner(commands, **kwargs):
            calls.append(commands)
            return mock_subprocess(commands, **kwargs)
        with patch.object(m.socket, "if_nameindex", return_value=[(1, "lo"), (2, "awg0")]):
            result = m.collect(config=fixture("awg"), runner=runner)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1].endswith("awg-service-probe.py"))
        self.assertEqual(result["service"]["mihomo"]["status"], "UNKNOWN")

    def test_awg_missing_does_not_test_physical_interface(self):
        with patch.object(m.socket, "if_nameindex", return_value=[(1, "lo"), (2, "eth0")]):
            result = m.collect(config=fixture("awg"),
                               runner=lambda *args, **kw: self.fail("unexpected process"))
        self.assertEqual(result["service"]["awg"]["status"], "UNKNOWN")

    def test_show_does_not_run_subprocess(self):
        # Code path is data-only, does not import routing or invoke transport select.
        with patch.object(m.subprocess, "run", side_effect=AssertionError("no")):
            self.assertEqual(m.parse_policy_env("SELECTION_MODE=manual")["mode"], "manual")


if __name__ == "__main__":
    unittest.main()
