#!/usr/bin/env python3
"""No-network observer validation: stale evidence never triggers switching."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

PATH = Path(__file__).resolve().parents[1] / "src" / "awg-service-observer.py"
spec = importlib.util.spec_from_file_location("awg_service_observer", PATH)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

NOW = 2_000_000
MONO = 1000


def evidence(transport, status, sample="sample-1", time=NOW, identity=""):
    statuses = {"PASS": ["PASS"] * 3, "FAIL": ["FAIL", "PASS", "PASS"],
                "UNKNOWN": ["PASS", "UNKNOWN", "PASS"]}
    return {"transport": transport, "status": status, "sample_id": sample,
            "checked_at": time, "identity": identity,
            "checks": {k: {"state": s, "reason": "fixture"}
                       for k, s in zip(("openai_api", "chatgpt_web", "youtube_video"),
                                       statuses[status])}}


def standby_state(now=NOW, status="PASS"):
    result = {"mode": "SHADOW_ONLY", "provider_sha256": "provider-hash",
              "generated_at": now, "warm": ["B", "C"], "entries": {}}
    for k in ("B", "C"):
        row = evidence("mihomo", status, sample="standby-" + k + "-" + str(now),
                       time=now, identity=k)
        row["fingerprint"] = "f"*64
        result["entries"][k] = row
    return result


def doc(active="mihomo", mh="PASS", aw="PASS", nmode="auto"):
    return {"main": {"transport": active, "node": "A"},
            "selection": {"mode": "auto", "priority": ["mihomo", "awg"],
                          "auto_failback": True},
            "node_policy": {"mode": nmode},
            "provider_sha256": "provider-hash",
            "standby": standby_state(),
            "service": {"mihomo": evidence("mihomo", mh, "m1", identity="A"),
                        "awg": evidence("awg", aw, "a1", identity="awg0")}}


class ObserverTests(unittest.TestCase):
    def test_full_pass_stays_mihomo(self):
        result, state = m.evaluate_document(doc(), now=NOW, mono=MONO)
        self.assertEqual((result["mode"], result["action"]), ("DRY_RUN_ONLY", "KEEP"))

    def test_stale_fail_cannot_trigger_switch(self):
        fixture = doc(mh="FAIL")
        fixture["service"]["mihomo"]["checked_at"] = NOW - 500
        result, state = m.evaluate_document(fixture, {"mihomo_fails": 20}, now=NOW, mono=MONO)
        self.assertEqual(result["action"], "KEEP")
        self.assertEqual(result["mihomo_service"], "UNKNOWN")

    def test_wrong_node_identity_is_unknown(self):
        fixture = doc(mh="FAIL")
        fixture["service"]["mihomo"]["identity"] = "B"
        status, _ = m.checked_status(fixture["service"]["mihomo"],
                                      now=NOW, transport="mihomo", identity="A")
        self.assertEqual(status, "UNKNOWN")

    def test_invalid_claim_of_pass_refused(self):
        fixture = evidence("awg", "PASS", identity="awg0")
        fixture["checks"]["youtube_video"]["state"] = "FAIL"
        status, sample = m.checked_status(fixture, now=NOW, transport="awg",
                                          identity="awg0")
        self.assertEqual((status, sample), ("UNKNOWN", ""))

    def test_cached_probe_reuse_not_counted_as_multiple_failures(self):
        first, state = m.evaluate_document(doc(mh="FAIL"), now=NOW, mono=MONO)
        second, state = m.evaluate_document(doc(mh="FAIL"), state, now=NOW+10, mono=MONO+10)
        self.assertEqual(first["action"], "KEEP")
        self.assertEqual(second["action"], "KEEP")
        self.assertEqual(state["mihomo_fails"], 1)

    def test_two_fresh_failures_choose_warm(self):
        _, state = m.evaluate_document(doc(mh="FAIL"), now=NOW, mono=MONO)
        nxt = doc(mh="FAIL")
        nxt["service"]["mihomo"]["sample_id"] = "m2"
        result, state = m.evaluate_document(nxt, state, now=NOW+10, mono=MONO+10)
        self.assertEqual((result["action"], result["target"]), ("SELECT_NODE", "B"))
        self.assertEqual(result["detection_seconds"], 10)

    def test_stale_standby_is_rejected(self):
        fixture = doc(mh="FAIL")
        fixture["standby"]["generated_at"] = NOW - 500
        self.assertEqual(m.standby_ready(fixture["standby"], now=NOW,
                                         provider_sha="provider-hash"), ())
        _, state = m.evaluate_document(fixture, now=NOW, mono=MONO)
        fixture["service"]["mihomo"]["sample_id"] = "m2"
        result, _ = m.evaluate_document(fixture, state, now=NOW+10, mono=MONO+10)
        self.assertEqual((result["action"], result["target"]),
                         ("SELECT_TRANSPORT", "awg"))

    def test_provider_change_invalidates_standby(self):
        fixture = doc()
        fixture["provider_sha256"] = "provider-changed"
        result, state = m.evaluate_document(fixture, now=NOW, mono=MONO)
        self.assertEqual(result["warm_count"], 0)

    def test_both_services_unqualified_enters_wait(self):
        fixture = doc(mh="FAIL", aw="FAIL")
        fixture["standby"]["warm"] = []
        _, state = m.evaluate_document(fixture, now=NOW, mono=MONO)
        fixture["service"]["mihomo"]["sample_id"] = "m2"
        fixture["service"]["awg"]["sample_id"] = "a2"
        result, _ = m.evaluate_document(fixture, state, now=NOW+10, mono=MONO+10)
        self.assertEqual(result["status"], "NO_WORKING_TRANSPORT")
        self.assertEqual(result["action"], "RECOVERY_WAIT")

    def test_nonautomatic_policy_is_not_overridden(self):
        fixture = doc(mh="FAIL")
        fixture["selection"]["mode"] = "fixed"
        result, _ = m.evaluate_document(fixture, {"mihomo_fails": 10},
                                        now=NOW, mono=MONO)
        self.assertEqual((result["action"], result["status"]),
                         ("KEEP", "MANUAL_OR_FIXED"))

    def test_auto_return_needs_fresh_passes(self):
        fixture = doc(active="awg")
        fixture["service"]["mihomo"]["identity"] = ""
        mem = {"last_switch_at": 700}
        result, mem = m.evaluate_document(fixture, mem, now=NOW, mono=MONO)
        self.assertEqual(result["action"], "KEEP")
        fixture["standby"] = standby_state(now=NOW+20)
        result, _ = m.evaluate_document(fixture, mem, now=NOW+20, mono=MONO+20)
        self.assertEqual((result["action"], result["target"]),
                         ("SELECT_TRANSPORT", "mihomo"))

    def test_on_awg_old_active_mihomo_result_cannot_force_failback(self):
        fixture = doc(active="awg")
        fixture["standby"]["entries"]["B"]["status"] = "UNKNOWN"
        fixture["standby"]["entries"]["C"]["status"] = "UNKNOWN"
        fixture["service"]["mihomo"] = evidence("mihomo", "PASS", "active-from-hours-ago",
                                                  identity="A")
        result, _ = m.evaluate_document(
            fixture, {"mihomo_passes": 5, "last_switch_at": 100},
            now=NOW, mono=MONO)
        self.assertEqual(result["action"], "KEEP")
        self.assertEqual(result["warm_count"], 0)
        self.assertEqual(result["mihomo_service"], "UNKNOWN")

    def test_replay_same_standby_success_cannot_count_twice(self):
        fixture = doc(active="awg")
        first, state = m.evaluate_document(fixture, {"last_switch_at": 1},
                                           now=NOW, mono=MONO)
        second, state = m.evaluate_document(fixture, state,
                                            now=NOW+25, mono=MONO+25)
        self.assertEqual((first["action"], second["action"]), ("KEEP", "KEEP"))
        self.assertEqual(state["mihomo_passes"], 1)

    def test_awg_service_probe_cannot_be_misattributed(self):
        fixture = evidence("awg", "PASS", identity="awg1")
        self.assertEqual(m.checked_status(fixture, now=NOW, transport="awg",
                                          identity="awg0"), ("UNKNOWN", ""))


if __name__ == "__main__":
    unittest.main()
