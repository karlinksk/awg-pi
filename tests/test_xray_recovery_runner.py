#!/usr/bin/env python3
import importlib.util
import sys
import unittest
from pathlib import Path

path=Path(__file__).resolve().parents[1]/"src"/"awg-xray-recovery-runner.py"
spec=importlib.util.spec_from_file_location("xray_recovery_runner",path)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

class RecoveryRunnerTests(unittest.TestCase):
    def test_failed_node_is_never_reactivated(self):
        calls=[]
        result=m.recover("dead",["dead","vless"],
            activate=lambda n:calls.append(n) or True,
            verify=lambda n:True,quiesce=lambda:True)
        self.assertEqual(calls,["vless"])
        self.assertEqual(result.selected,"vless")

    def test_tun_failure_retries_next_distinct_node(self):
        calls=[]
        result=m.recover("dead",["vless","vless","hy2"],
            activate=lambda n:calls.append(("activate",n)) or True,
            verify=lambda n:calls.append(("verify",n)) or n=="hy2",
            quiesce=lambda:True,reject_cleanup=lambda n:True)
        self.assertEqual(result.selected,"hy2")
        self.assertEqual(result.attempted,("vless","hy2"))

    def test_activation_exception_is_not_success(self):
        calls=[]
        def activate(name):
            calls.append(name)
            if name=="bad":raise RuntimeError("core timeout")
            return True
        result=m.recover("dead",["bad","good"],activate=activate,
            verify=lambda n:True,quiesce=lambda:True,reject_cleanup=lambda n:True)
        self.assertEqual(result.selected,"good")
        self.assertEqual(calls,["bad","good"])

    def test_exhaustion_must_quiesce(self):
        state=[]
        with self.assertRaisesRegex(m.RecoveryFailed,"NO_VERIFIED_RECOVERY"):
            m.recover("dead",["bad"],activate=lambda n:True,
                verify=lambda n:False,quiesce=lambda:state.append("guarded") or True,
                reject_cleanup=lambda n:True)
        self.assertEqual(state,["guarded"])

    def test_failed_quiesce_not_claimed_as_safe(self):
        with self.assertRaisesRegex(m.RecoveryFailed,"QUIESCE_FAILED"):
            m.recover("dead",[],activate=lambda n:True,
                verify=lambda n:True,quiesce=lambda:False)

    def test_rejected_candidate_requires_independent_cleanup(self):
        calls=[]
        with self.assertRaisesRegex(m.RecoveryFailed,"REJECT_CLEANUP_UNVERIFIED"):
            m.recover("dead",["xray","hy2"],
                activate=lambda n:calls.append("start:"+n) or True,
                verify=lambda n:False,
                reject_cleanup=lambda n:calls.append("cleanup:"+n) or False,
                quiesce=lambda:calls.append("quiesce") or True)
        self.assertEqual(calls,["start:xray","cleanup:xray","quiesce"])

    def test_missing_cleanup_never_advances_to_next_candidate(self):
        attempts=[]
        with self.assertRaisesRegex(m.RecoveryFailed,"REJECT_CLEANUP_UNVERIFIED"):
            m.recover("dead",["bad","good"],
                activate=lambda n:attempts.append(n) or True,
                verify=lambda n:False,quiesce=lambda:True)
        self.assertEqual(attempts,["bad"])

    def test_failed_cleanup_and_quiesce_is_distinct(self):
        with self.assertRaisesRegex(m.RecoveryFailed,"REJECT_CLEANUP_AND_QUIESCE_FAILED"):
            m.recover("dead",["xray"],activate=lambda n:True,
                verify=lambda n:False,reject_cleanup=lambda n:False,
                quiesce=lambda:False)

    def test_attempt_limit_prevents_unbounded_scan(self):
        calls=[]
        with self.assertRaises(m.RecoveryFailed):
            m.recover("dead",[str(i) for i in range(50)],
                activate=lambda n:calls.append(n) or False,
                verify=lambda n:False,quiesce=lambda:True,
                reject_cleanup=lambda n:True,max_attempts=3)
        self.assertEqual(calls,["0","1","2"])

if __name__=="__main__":unittest.main()
