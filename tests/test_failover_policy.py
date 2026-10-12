#!/usr/bin/env python3
"""Offline deterministic failures / failbacks for the read-only policy model."""
import importlib.util
from pathlib import Path
import sys
import unittest

PATH = Path(__file__).resolve().parents[1] / "src" / "awg-failover-policy.py"
spec = importlib.util.spec_from_file_location("awg_failover_policy", PATH)
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)


def o(*, t=1000, active="mihomo", node="A", mode="auto", nmode="auto",
      mihomo="PASS", awg="PASS", ms="m1", asample="a1",
      warm=("B", "C"), allowed=()):
    return p.Observation(t, active, node, mode, nmode, mihomo, awg,
                         ms, asample, warm, allowed)


class FailoverPolicyTests(unittest.TestCase):
    def test_normal_main_mihomo_is_sticky(self):
        decision, _ = p.evaluate(o(), p.Memory())
        self.assertEqual((decision.action, decision.status), ("KEEP", "ACTIVE_MIHOMO"))

    def test_mihomo_fail_requires_two_distinct_confirmations(self):
        first, mem = p.evaluate(o(mihomo="FAIL", ms="failure1"), p.Memory())
        self.assertEqual(first.action, "KEEP")
        repeat, mem = p.evaluate(o(mihomo="FAIL", ms="failure1"), mem)
        self.assertEqual(repeat.action, "KEEP")
        second, mem = p.evaluate(o(mihomo="FAIL", ms="failure2"), mem)
        self.assertEqual((second.action, second.target), ("SELECT_NODE", "B"))
        self.assertTrue(second.confirmed_failure)

    def test_fast_fallback_to_awg_if_no_hot_node(self):
        _, mem = p.evaluate(o(mihomo="FAIL", ms="m1", warm=()), p.Memory())
        decision, _ = p.evaluate(o(mihomo="FAIL", ms="m2", warm=()), mem)
        self.assertEqual((decision.action, decision.target),
                         ("SELECT_TRANSPORT", "awg"))

    def test_awg_unqualified_both_fail_enters_recovery_wait(self):
        _, mem = p.evaluate(o(mihomo="FAIL", awg="FAIL", warm=(), ms="m1"), p.Memory())
        decision, mem = p.evaluate(o(mihomo="FAIL", awg="FAIL", warm=(), ms="m2"), mem)
        self.assertEqual(decision.action, "RECOVERY_WAIT")
        self.assertEqual(decision.status, "NO_WORKING_TRANSPORT")
        self.assertTrue(mem.outage_since)

    def test_unknown_does_not_force_failover(self):
        state = p.Memory()
        for i in range(1, 5):
            result, state = p.evaluate(o(mihomo="UNKNOWN", ms=f"m{i}"), state)
            self.assertEqual(result.action, "KEEP")
            self.assertEqual(result.status, "PROBE_UNKNOWN")

    def test_awg_restores_first_while_mihomo_still_fails(self):
        _, mem = p.evaluate(o(mihomo="FAIL", awg="FAIL", warm=(), ms="m1"), p.Memory())
        decision, mem = p.evaluate(o(mihomo="FAIL", awg="FAIL", warm=(), ms="m2"), mem)
        self.assertEqual(decision.status, "NO_WORKING_TRANSPORT")
        next_decision, _ = p.evaluate(o(t=1040, mihomo="FAIL", awg="PASS",
                                        warm=(), ms="m3", asample="a2"), mem)
        self.assertEqual((next_decision.action, next_decision.target),
                         ("SELECT_TRANSPORT", "awg"))

    def test_awg_failure_recovery_mihomo_bypasses_dwell(self):
        obs = o(t=1010, active="awg", mihomo="PASS", awg="FAIL", ms="new1",
                asample="fail1", warm=("B",))
        _, mem = p.evaluate(obs, p.Memory(last_switch_at=1008))
        decision, _ = p.evaluate(o(t=1020, active="awg", mihomo="PASS",
                                   awg="FAIL", ms="new2", asample="fail2",
                                   warm=("B",)), mem)
        self.assertEqual((decision.action, decision.target),
                         ("SELECT_TRANSPORT", "mihomo"))

    def test_failback_waits_two_probes_and_dwell(self):
        state = p.Memory(last_switch_at=1000)
        first, state = p.evaluate(o(t=1010, active="awg", mihomo="PASS",
                                    ms="m1", asample="a1", warm=("B",)), state)
        self.assertEqual(first.action, "KEEP")
        again, state = p.evaluate(o(t=1170, active="awg", mihomo="PASS",
                                    ms="m1", asample="a1", warm=("B",)), state)
        self.assertEqual(again.action, "KEEP")  # same cached success is not two probes
        ready, state = p.evaluate(o(t=1180, active="awg", mihomo="PASS",
                                    ms="m2", asample="a2", warm=("B",)), state)
        self.assertEqual((ready.action, ready.target), ("SELECT_TRANSPORT", "mihomo"))

    def test_auto_failback_can_be_disabled(self):
        policy = p.Policy(auto_failback=False)
        state = p.Memory(last_switch_at=1, mihomo_passes=4)
        decision, _ = p.evaluate(o(t=1500, active="awg", mihomo="PASS",
                                   warm=("B",), ms="newprobe"), state, policy)
        self.assertEqual(decision.action, "KEEP")

    def test_reverse_priority_awg_remains_primary(self):
        policy = p.Policy(priority=("awg", "mihomo"))
        state = p.Memory(last_switch_at=1, mihomo_passes=4)
        decision, _ = p.evaluate(o(t=1500, active="awg", mihomo="PASS",
                                   warm=("B",), ms="newprobe"), state, policy)
        self.assertEqual(decision.action, "KEEP")

    def test_manual_fixed_are_not_overridden(self):
        for mode in ("manual", "fixed"):
            decision, _ = p.evaluate(o(mode=mode, mihomo="FAIL", awg="PASS",
                                       ms="m1"), p.Memory(mihomo_fails=10))
            self.assertEqual((decision.action, decision.status),
                             ("KEEP", "MANUAL_OR_FIXED"))

    def test_fixed_node_mode_cannot_pick_unlisted_node(self):
        obs = o(mihomo="FAIL", awg="PASS", nmode="fixed",
                warm=("B", "C"), allowed=("C",), ms="failed2")
        decision, _ = p.evaluate(obs, p.Memory(mihomo_fails=1))
        self.assertEqual((decision.action, decision.target), ("SELECT_NODE", "C"))

    def test_awg_can_return_to_saved_mihomo_node(self):
        state = p.Memory(last_switch_at=1, mihomo_passes=2)
        decision, _ = p.evaluate(o(t=1500, active="awg", node="B",
                                   mihomo="PASS", warm=("B",), ms="new"), state)
        self.assertEqual((decision.action, decision.target),
                         ("SELECT_TRANSPORT", "mihomo"))

    def test_fixed_chain_never_wraps_to_earlier_node(self):
        policy = p.Policy(required_failures=2)
        obs = o(node="C", nmode="fixed", mihomo="FAIL", ms="m2",
                warm=("A", "B", "D"), allowed=("A", "B", "C", "D"))
        decision, _ = p.evaluate(obs, p.Memory(mihomo_fails=1), policy)
        self.assertEqual((decision.action, decision.target), ("SELECT_NODE", "D"))
        no_tail = o(node="D", nmode="fixed", mihomo="FAIL", ms="m2",
                    warm=("A", "B"), allowed=("A", "B", "C", "D"))
        decision, _ = p.evaluate(no_tail, p.Memory(mihomo_fails=1), policy)
        self.assertEqual((decision.action, decision.target),
                         ("SELECT_TRANSPORT", "awg"))

    def test_manual_node_mode_cannot_pick_random_node(self):
        decision, _ = p.evaluate(o(mihomo="FAIL", nmode="manual",
                                   warm=("B",), ms="m2"), p.Memory(mihomo_fails=1))
        self.assertEqual((decision.action, decision.target),
                         ("SELECT_TRANSPORT", "awg"))

    def test_unknown_resets_consecutive_failure_streak(self):
        _, mem = p.evaluate(o(t=1000, mihomo="FAIL", ms="bad1"), p.Memory())
        _, mem = p.evaluate(o(t=1010, mihomo="UNKNOWN", ms="unknown"), mem)
        decision, mem = p.evaluate(o(t=1020, mihomo="FAIL", ms="bad2"), mem)
        self.assertEqual((decision.action, mem.mihomo_fails), ("KEEP", 1))

    def test_measures_detect_and_recovery_using_monotonic_seconds(self):
        _, state = p.evaluate(o(t=1000, mihomo="FAIL", ms="m1"), p.Memory())
        decision, state = p.evaluate(o(t=1012, mihomo="FAIL", ms="m2"), state)
        self.assertEqual(decision.action, "SELECT_NODE")
        self.assertEqual(state.last_detection_seconds, 12)
        self.assertEqual(state.outage_since, 1000)
        restored = p.commit_success(state, 1035)
        self.assertEqual(restored.last_recovery_seconds, 35)
        self.assertEqual(restored.switches_total, 1)

    def test_clean_boot_no_transport_available(self):
        decision, _ = p.evaluate(o(active="unconfigured", mihomo="FAIL",
                                   awg="FAIL", warm=()), p.Memory())
        self.assertEqual((decision.action, decision.status),
                         ("RECOVERY_WAIT", "NO_WORKING_TRANSPORT"))

    def test_clean_boot_uses_first_available(self):
        first, _ = p.evaluate(o(active="unconfigured", mihomo="PASS",
                                awg="PASS", warm=("B",)), p.Memory())
        self.assertEqual(first.target, "mihomo")
        other, _ = p.evaluate(o(active="unconfigured", mihomo="FAIL",
                                awg="PASS", warm=()), p.Memory())
        self.assertEqual(other.target, "awg")

    def test_commit_only_after_success(self):
        prior = p.Memory(mihomo_fails=2, awg_fails=1, mihomo_passes=3,
                         last_switch_at=1, outage_since=100)
        after = p.commit_success(prior, 120)
        self.assertEqual(after.last_switch_at, 120)
        self.assertEqual(after.mihomo_fails, 0)
        self.assertEqual(after.outage_since, 0)
        self.assertEqual(prior.last_switch_at, 1)

    def test_bad_policy_rejected(self):
        for transports in (("mihomo", "mihomo"), ("awg",), ("mihomo", "direct")):
            with self.assertRaises(ValueError):
                p.Policy(priority=transports)


if __name__ == "__main__":
    unittest.main()
