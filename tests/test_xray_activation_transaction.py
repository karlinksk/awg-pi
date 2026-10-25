#!/usr/bin/env python3
import importlib.util
import sys
import unittest
from pathlib import Path

p=Path(__file__).resolve().parents[1]/"src"/"awg-xray-activation-transaction.py"
spec=importlib.util.spec_from_file_location("awg_activation_tx",p)
tx=importlib.util.module_from_spec(spec);sys.modules[spec.name]=tx;spec.loader.exec_module(tx)

class FakeBackend:
    def __init__(self, reject=None):
        self.events=[]
        self.reject=reject
    def record(self, key):
        self.events.append(key)
        if self.reject==key:raise RuntimeError(key)
    def preflight(self, failed, candidate):self.record("preflight")
    def arm_watchdog(self):self.record("arm")
    def stage_xray(self, candidate):self.record("stage")
    def start_xray(self):self.record("xray")
    def check_local_ready(self):
        self.record("local")
        return self.reject!="local_false"
    def check_provider_unchanged(self):
        self.record("provider")
        return self.reject!="provider_false"
    def stage_mihomo_bridge(self):self.record("bridge")
    def restart_mihomo(self):self.record("restart")
    def restore_kernel_routes(self):self.record("routes")
    def select_xray_bridge(self):self.record("select")
    def check_tun_ready(self):
        self.record("tun")
        return self.reject!="tun_false"
    def check_policy_routes(self):
        self.record("policy")
        return self.reject!="policy_false"
    def install_boot_dependencies(self):self.record("boot_install")
    def check_boot_dependencies(self):
        self.record("boot_verify")
        return self.reject!="boot_false"
    def verify_committed_node(self, candidate):
        self.record("node_verify")
        return self.reject!="node_false"
    def commit(self):self.record("commit")
    def disarm_watchdog(self):self.record("disarm")
    def fail_closed(self):
        self.record("failclosed")
        return self.reject!="failclosed_false"

class ActivationTests(unittest.TestCase):
    def test_success_requires_all_stages(self):
        b=FakeBackend()
        rec=tx.activate("dead","new",b)
        self.assertTrue(rec.runtime_ready and rec.boot_wiring_verified)
        self.assertEqual(rec.candidate,"new")
        self.assertEqual(b.events[0:3],["preflight","arm","stage"])
        self.assertLess(b.events.index("tun"),b.events.index("boot_verify"))
        self.assertLess(b.events.index("node_verify"),b.events.index("commit"))
        self.assertEqual(b.events[-2:],["commit","disarm"])
        self.assertNotIn("failclosed",b.events)
    def test_never_restore_dead_original(self):
        b=FakeBackend()
        with self.assertRaises(tx.ActivationFailure):
            tx.activate("same","same",b)
        self.assertEqual(b.events,[])
    def test_preflight_failure_no_mutation(self):
        b=FakeBackend("preflight")
        with self.assertRaises(tx.ActivationFailure):
            tx.activate("dead","new",b)
        self.assertEqual(b.events,["preflight"])
    def test_failure_after_watchdog_fails_closed_and_retains_watchdog(self):
        for reject in ("stage","xray","local_false","provider_false",
                       "bridge","restart","routes","select","tun_false",
                       "policy_false","boot_install","boot_false",
                       "node_false","commit"):
            with self.subTest(reject=reject):
                b=FakeBackend(reject)
                with self.assertRaises(tx.ActivationFailure):
                    tx.activate("dead","new",b)
                self.assertIn("arm",b.events)
                self.assertIn("failclosed",b.events)
                self.assertNotIn("disarm",b.events)
    def test_quiesce_failure_is_explicit_and_not_pass(self):
        b=FakeBackend("failclosed_false")
        b.check_tun_ready=lambda:False
        with self.assertRaisesRegex(tx.ActivationFailure,"FAIL_CLOSED_UNCONFIRMED"):
            tx.activate("dead","new",b)
        self.assertIn("failclosed",b.events)
        self.assertNotIn("disarm",b.events)
    def test_missing_boot_check_refuses_commit(self):
        b=FakeBackend("boot_false")
        with self.assertRaises(tx.ActivationFailure):
            tx.activate("dead","new",b)
        self.assertNotIn("commit",b.events)
        self.assertIn("failclosed",b.events)

if __name__=="__main__":unittest.main()
