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
        row.update({"service_qualified": True,
                    "service_qualification": "SERVICE_READY",
                    "service_confirmations": 2,
                    "policy_generation": 1,
                    "boot_id": "fixture-boot",
                    "service_status": status,
                    "service_checked_at": now,
                    "service_checks": row["checks"]})
        # Test-only hypothetical router-attested path. A real Pi-only scan
        # MUST NOT mint this evidence on its own.
        row["underlay"] = {
            "mode": "DIRECT", "scope": "END_TO_END",
            "reason": "router_underlay_verified", "router_verified": True}
        result["entries"][k] = row
    return result


def doc(active="mihomo", mh="PASS", aw="PASS", nmode="auto"):
    return {"main": {"transport": active, "node": "A"},
            "selection": {"mode": "auto", "priority": ["mihomo", "awg"],
                          "auto_failback": True},
            "node_policy": {"mode": nmode},
            "provider_sha256": "provider-hash",
            "router_generation": 1, "router_boot_id": "fixture-boot",
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

    def test_single_pass_old_standby_cache_not_promoted(self):
        fixture = doc()
        for row in fixture["standby"]["entries"].values():
            row["service_confirmations"] = 1
            row["service_qualified"] = False
        result, _ = m.evaluate_document(fixture, now=NOW, mono=MONO)
        self.assertEqual(result["warm_count"], 0)

    def test_router_generation_drift_invalidates_standby(self):
        fixture = doc()
        fixture["router_generation"] = 2
        result, _ = m.evaluate_document(fixture, now=NOW, mono=MONO)
        self.assertEqual(result["warm_count"], 0)

    def test_router_boot_change_invalidates_standby(self):
        fixture = doc()
        fixture["router_boot_id"] = "rebooted"
        result, _ = m.evaluate_document(fixture, now=NOW, mono=MONO)
        self.assertEqual(result["warm_count"], 0)

    def test_missing_service_confirmation_refused(self):
        fixture = doc()
        for row in fixture["standby"]["entries"].values():
            row.pop("service_qualification")
            row.pop("service_qualified")
        result, _ = m.evaluate_document(fixture, now=NOW, mono=MONO)
        self.assertEqual(result["warm_count"], 0)

    def test_service_pass_over_awg_assisted_node_never_becomes_warm(self):
        fixture = doc()
        fixture["standby"]["entries"]["B"]["underlay"] = {
            "mode": "ASSISTED_AWG", "scope": "PI_ONLY",
            "reason": "routed_via_awg", "router_verified": False}
        fixture["standby"]["entries"]["C"]["underlay"] = {
            "mode": "DIRECT_LOCAL_UNVERIFIED", "scope": "PI_ONLY",
            "reason": "lan_next_hop_router_not_verified", "router_verified": False}
        result, _ = m.evaluate_document(fixture, now=NOW, mono=MONO)
        self.assertEqual(result["warm_count"], 0)

    def test_legacy_standby_without_underlay_is_not_promoted(self):
        fixture = doc()
        for k in ("B", "C"):
            fixture["standby"]["entries"][k].pop("underlay")
        result, _ = m.evaluate_document(fixture, now=NOW, mono=MONO)
        self.assertEqual(result["warm_count"], 0)

    def test_stale_standby_is_rejected(self):
        fixture = doc(mh="FAIL")
        fixture["standby"]["generated_at"] = NOW - 500
        self.assertEqual(m.standby_ready(fixture["standby"], now=NOW,
                                         provider_sha="provider-hash",
                                         router_generation=1,
                                         router_boot_id="fixture-boot"), ())
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

    def test_config_and_active_node_change_invalidate_shadow_memory(self):
        a = doc()
        old_key = m.state_identity(a)
        a["main"]["node"] = "another-node"
        self.assertNotEqual(old_key, m.state_identity(a))
        a["selection"]["priority"] = ["awg", "mihomo"]
        self.assertNotEqual(old_key, m.state_identity(a))

    def test_boot_id_change_drops_observer_counters(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            path = Path(directory) / "memory.json"
            path.write_text(json.dumps({"identity": "valid-key", "boot_id": "old-boot",
                                        "memory": {"mihomo_fails": 99}}))
            self.assertEqual(m.read_advisory_state(path, "valid-key", "new-boot"), {})
            self.assertEqual(m.read_advisory_state(path, "new-key", "old-boot"), {})
            self.assertEqual(m.read_advisory_state(path, "valid-key", "old-boot"),
                             {"mihomo_fails": 99})

    def test_shadow_memory_must_remain_under_ram_run_path(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            with self.assertRaises(ValueError):
                m.save_advisory_state(Path(directory) / "unsafe.json",
                                      "test", "boot", {})

    def test_awg_service_probe_cannot_be_misattributed(self):
        fixture = evidence("awg", "PASS", identity="awg1")
        self.assertEqual(m.checked_status(fixture, now=NOW, transport="awg",
                                          identity="awg0"), ("UNKNOWN", ""))


if __name__ == "__main__":
    unittest.main()
