#!/usr/bin/env python3
"""Fault-injection: switch transaction is isolated from real VPN actions."""
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest

FILE = Path(__file__).resolve().parents[1] / "src" / "awg-switch-transaction.py"
spec = importlib.util.spec_from_file_location("awg_switch_transaction", FILE)
tx = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tx
spec.loader.exec_module(tx)


def proof(transport, identity, status="PASS"):
    values = ["PASS"] * 3 if status == "PASS" else ["FAIL", "PASS", "PASS"]
    return {"transport": transport, "identity": identity, "status": status,
            "sample_id": "sample_" + transport,
            "checked_at": int(time.time()),
            "checks": {key: {"state": value, "reason": "test"}
                       for key, value in zip(("openai_api", "chatgpt_web", "youtube_video"), values)}}


def source(transport="mihomo", node="A", awg="PASS", mihomo="FAIL"):
    now = int(time.time())
    warm = {"mode": "SHADOW_ONLY", "provider_sha256": "provider-test",
            "generated_at": now, "warm": ["B", "C"],
            "entries": {name: {
                **proof("mihomo", name), "fingerprint": "f"*64,
                "service_qualified": True,
                "service_qualification": "SERVICE_READY",
                "service_confirmations": 2,
                "policy_generation": 1,
                "service_status": "PASS",
                "service_checked_at": now,
                "service_checks": proof("mihomo", name)["checks"],
                "underlay": {"mode": "DIRECT", "scope": "END_TO_END",
                             "reason": "router_underlay_verified",
                             "router_verified": True}}
                for name in ("B", "C")}}
    return {"version": 1, "generated_at": now,
            "main": {"transport": transport, "node": node},
            "selection": {"mode": "auto", "priority": ["mihomo", "awg"],
                          "auto_failback": True},
            "node_policy": {"mode": "auto", "allowed": []},
            "provider_sha256": "provider-test",
            "standby": warm,
            "service": {"mihomo": proof("mihomo", node, mihomo),
                        "awg": proof("awg", "awg0", awg)}}


def recommendation(action, target):
    return {"mode": "DRY_RUN_ONLY", "action": action,
            "target": target, "status": "RECOVERY_PENDING",
            "reason": ("no_warm_mihomo_node" if target == "awg"
                       else "service_failover_to_hot_spare"),
            "recovery_confirmed": True}


class FakeBackend:
    def __init__(self, transport="mihomo", node="A"):
        self.state = {"transport": transport, "node": node, "guard_safe": True,
                      "route": "dev mihomo0" if transport == "mihomo" else "dev awg0"}
        self.lock_available = True
        self.prepare_ok = True
        self.evidence_ok = True
        self.preflight_ok = True
        self.apply_ok = True
        self.postflight_ok = True
        self.restore_ok = True
        self.prepare_changes_route = False
        self.fenced = False
        self.actions = []

    def snapshot(self):
        return dict(self.state)
    def try_action_gate(self):
        self.actions.append("gate")
        return self.lock_available
    def release_action_gate(self):
        self.actions.append("unlock")
    def confirm_recent_evidence(self, advice, evidence):
        self.actions.append("verify_evidence")
        return self.evidence_ok
    def prepare(self, action, target):
        self.actions.append("prepare")
        if self.prepare_changes_route:
            self.state["route"] = "dev eth0"
        return self.prepare_ok
    def preflight(self, action, target):
        self.actions.append("preflight")
        return self.preflight_ok
    def apply(self, action, target):
        self.actions.append("apply")
        if action == "SELECT_NODE":
            self.state["node"] = target
        else:
            self.state["transport"] = target
            self.state["route"] = "dev awg0" if target == "awg" else "dev mihomo0"
        return self.apply_ok
    def postflight(self, action, target):
        self.actions.append("postflight")
        return self.postflight_ok
    def restore(self, original):
        self.actions.append("restore")
        if self.restore_ok:
            self.state = dict(original)
        return self.restore_ok
    def force_fail_closed(self):
        self.actions.append("fail_closed")
        self.fenced = True
        self.state["guard_safe"] = True
        self.state["route"] = "unreachable"


class TransactionTests(unittest.TestCase):
    def test_warm_spare_commit(self):
        backend = FakeBackend()
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                            source(), backend)
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(backend.state["node"], "B")
        self.assertEqual(backend.state["route"], "dev mihomo0")
        self.assertEqual(backend.actions, ["gate", "verify_evidence", "prepare", "preflight",
                                          "apply", "postflight", "unlock"])

    def test_awg_fallback_commit_after_mihomo_spares_exhausted(self):
        evidence = source()
        evidence["standby"]["warm"] = []
        advice = recommendation("SELECT_TRANSPORT", "awg")
        backend = FakeBackend()
        result = tx.execute_mock_transaction(advice, evidence, backend)
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(backend.state["route"], "dev awg0")

    def test_forged_advisory_cannot_skip_independent_confirmation(self):
        backend = FakeBackend()
        backend.evidence_ok = False
        verdict = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                              source(), backend)
        self.assertEqual((verdict.status, verdict.reason),
                         ("BLOCKED", "independent_evidence_unconfirmed"))
        self.assertNotIn("prepare", backend.actions)
        self.assertEqual(backend.state["route"], "dev mihomo0")

    def test_preflight_abort_failed_requires_fail_closed(self):
        backend = FakeBackend()
        backend.preflight_ok = False
        backend.restore_ok = False
        verdict = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                              source(), backend)
        self.assertEqual(verdict.status, "FAIL_CLOSED_REQUIRED")
        self.assertEqual(backend.state["route"], "unreachable")

    def test_wrong_awk_qualification_blocked_without_prepare(self):
        evidence = source(awg="UNKNOWN")
        evidence["standby"]["warm"] = []
        backend = FakeBackend()
        result = tx.execute_mock_transaction(recommendation("SELECT_TRANSPORT", "awg"),
                                             evidence, backend)
        self.assertEqual(result.status, "BLOCKED")
        self.assertNotIn("prepare", backend.actions)

    def test_assisted_aws_node_is_never_promoted(self):
        fixture = source()
        fixture["standby"]["entries"]["B"]["underlay"]["mode"] = "ASSISTED_AWG"
        fixture["standby"]["entries"]["C"]["underlay"]["mode"] = "UNKNOWN"
        result = tx.execute_mock_transaction(
            recommendation("SELECT_NODE", "B"), fixture, FakeBackend())
        self.assertEqual(result.status, "BLOCKED")

    def test_pi_local_eth0_route_is_not_router_direct_attestation(self):
        fixture = source()
        fixture["standby"]["entries"]["B"]["underlay"] = {
            "mode": "DIRECT_LOCAL_UNVERIFIED", "scope": "PI_ONLY",
            "reason": "lan_next_hop_router_not_verified", "router_verified": False}
        result = tx.execute_mock_transaction(
            recommendation("SELECT_NODE", "B"), fixture, FakeBackend())
        self.assertEqual(result.status, "BLOCKED")

    def test_legacy_single_service_pass_cannot_switch(self):
        source_doc = source()
        for n in ("B","C"):
            source_doc["standby"]["entries"][n]["service_confirmations"] = 1
            source_doc["standby"]["entries"][n]["service_qualified"] = False
        b=FakeBackend()
        decision=tx.execute_mock_transaction(
            recommendation("SELECT_NODE","B"),source_doc,b)
        self.assertEqual(decision.status,"BLOCKED")
        self.assertNotIn("apply",b.actions)

    def test_provider_stale_cache_blocks_node(self):
        evidence = source()
        evidence["provider_sha256"] = "changed"
        backend = FakeBackend()
        r = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                        evidence, backend)
        self.assertEqual((r.status, r.reason), ("BLOCKED", "target_not_service_qualified_in_hot_spare"))

    def test_node_change_rejected_before_preflight(self):
        backend = FakeBackend(node="C")
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             source(), backend)
        self.assertEqual(result.status, "BLOCKED")
        self.assertNotIn("prepare", backend.actions)

    def test_manual_mode_has_no_automatic_switch(self):
        evidence = source()
        evidence["selection"]["mode"] = "manual"
        backend = FakeBackend()
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             evidence, backend)
        self.assertEqual(result.status, "BLOCKED")

    def test_fixed_never_wraps_backward(self):
        evidence = source(node="C")
        evidence["node_policy"] = {"mode": "fixed", "allowed": ["A", "B", "C"]}
        backend = FakeBackend(node="C")
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             evidence, backend)
        self.assertEqual((result.status, result.reason),
                         ("BLOCKED", "fixed_chain_cannot_wrap"))

    def test_live_guard_failure_prevents_all_changes(self):
        backend = FakeBackend()
        backend.state["guard_safe"] = False
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             source(), backend)
        self.assertEqual(result.reason, "guard_not_safe")
        self.assertEqual(backend.actions, [])

    def test_concurrent_action_lock_does_not_block_indefinitely(self):
        backend = FakeBackend()
        backend.lock_available = False
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             source(), backend)
        self.assertEqual((result.status, result.reason),
                         ("BLOCKED", "concurrent_switch_or_maintenance"))
        self.assertNotIn("prepare", backend.actions)

    def test_prepare_fails_without_route_change(self):
        backend = FakeBackend()
        backend.prepare_ok = False
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             source(), backend)
        self.assertEqual(result.reason, "prepare_failed")
        self.assertEqual(backend.state["route"], "dev mihomo0")

    def test_prepare_must_not_change_user_route(self):
        backend = FakeBackend()
        backend.prepare_changes_route = True
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             source(), backend)
        self.assertEqual(result.status, "ROLLED_BACK")
        self.assertEqual(backend.state["route"], "dev mihomo0")
        self.assertTrue(result.rolled_back)

    def test_preflight_refusal_does_not_commit(self):
        backend = FakeBackend()
        backend.preflight_ok = False
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             source(), backend)
        self.assertEqual(result.reason, "preflight_failed")
        self.assertNotIn("apply", backend.actions)

    def test_postflight_failure_rolls_back(self):
        backend = FakeBackend()
        backend.postflight_ok = False
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             source(), backend)
        self.assertEqual(result.status, "ROLLED_BACK")
        self.assertEqual(backend.state["node"], "A")
        self.assertEqual(backend.state["route"], "dev mihomo0")

    def test_prepare_rollback_failure_closes_egress(self):
        backend = FakeBackend()
        backend.prepare_changes_route = True
        backend.restore_ok = False
        result = tx.execute_mock_transaction(recommendation("SELECT_NODE", "B"),
                                             source(), backend)
        self.assertEqual(result.status, "FAIL_CLOSED_REQUIRED")
        self.assertEqual(backend.state["route"], "unreachable")

    def test_forged_or_stale_recommendations_rejected(self):
        for mutate in (
            lambda a, e: e.update(generated_at=int(time.time()) - 999),
            lambda a, e: a.update(recovery_confirmed=False),
            lambda a, e: a.update(status="ACTIVE_MIHOMO"),
            lambda a, e: a.update(reason="never_seen"),
            lambda a, e: e["service"]["mihomo"].update(status="PASS"),
        ):
            advice = recommendation("SELECT_NODE", "B")
            evidence = source()
            mutate(advice, evidence)
            result = tx.execute_mock_transaction(advice, evidence, FakeBackend())
            self.assertEqual(result.status, "BLOCKED")

    def test_awg_cannot_be_selected_when_hot_spare_passed(self):
        result = tx.execute_mock_transaction(recommendation("SELECT_TRANSPORT", "awg"),
                                             source(), FakeBackend())
        self.assertEqual((result.status, result.reason),
                         ("BLOCKED", "warm_mihomo_spare_has_priority"))

    def test_failback_needs_enabled_setting_and_awg_active(self):
        evidence = source(transport="awg", awg="PASS")
        backend = FakeBackend(transport="awg")
        advice = recommendation("SELECT_TRANSPORT", "mihomo")
        advice.update(reason="confirmed_priority_failback", recovery_confirmed=False)
        permitted = tx.execute_mock_transaction(advice, evidence, backend)
        self.assertEqual(permitted.status, "COMMITTED")
        evidence = source(transport="awg", awg="PASS")
        evidence["selection"]["auto_failback"] = False
        result = tx.execute_mock_transaction(advice, evidence, FakeBackend(transport="awg"))
        self.assertEqual(result.reason, "priority_failback_not_enabled")

    def test_failed_rollback_demands_failclosed_not_direct(self):
        backend = FakeBackend()
        backend.postflight_ok = False
        backend.restore_ok = False
        result = tx.execute_mock_transaction(recommendation("SELECT_TRANSPORT", "awg"),
                                             {**source(), "standby": {**source()["standby"],
                                                                     "warm": []}},
                                             backend)
        self.assertEqual(result.status, "FAIL_CLOSED_REQUIRED")
        self.assertTrue(result.fail_closed)
        self.assertEqual(backend.state["route"], "unreachable")
        self.assertNotEqual(backend.state["route"], "dev eth0")


if __name__ == "__main__":
    unittest.main()
