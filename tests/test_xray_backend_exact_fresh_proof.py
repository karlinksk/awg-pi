#!/usr/bin/env python3
"""Rootless verification: Xray activation must not trust cache NETWORK_OK."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"src/awg-xray-live-backend.py"
spec=importlib.util.spec_from_file_location("xray_backend_exact_fresh",SOURCE)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

class FreshProofBeforeAnyMutation(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.provider=self.root/"provider.yaml"
        self.provider.write_bytes(b"proxies: []\n")
        self.sha=hashlib.sha256(self.provider.read_bytes()).hexdigest()
        self.helper=mock.Mock()
        self.helper.is_file.return_value=True
        self.helper.is_symlink.return_value=False
        self.helper.stat.return_value.st_uid=0
        self.helper.__str__=mock.Mock(return_value="/usr/local/sbin/awg-xray-manual-switch")
        self.patches=[
            mock.patch.object(m,"PROVIDER",self.provider),
            mock.patch.object(m,"FRESH_XRAY_PROOF",self.helper),
        ]
        for p in self.patches:
            p.start();self.addCleanup(p.stop)

    def test_fresh_exact_probe_proves_current_profile_without_mutation(self):
        with mock.patch.object(m,"run",return_value="FRESH_CANDIDATE_PROOF=PASS_NO_MUTATION") as p:
            m.fresh_exact_xray_https(3,self.sha)
        p.assert_called_once_with("/usr/local/sbin/awg-xray-manual-switch",
                                  "probe-xray","3",timeout=75)

    def test_failed_probe_cannot_be_accepted_as_cached_network_ok(self):
        for outcome in ("NETWORK_OK","FRESH_CANDIDATE_PROOF=FAIL",""):
            with self.subTest(outcome=outcome),\
                 mock.patch.object(m,"run",return_value=outcome),\
                 self.assertRaisesRegex(RuntimeError,"XRAY_EXACT_ISOLATED_HTTPS_UNVERIFIED"):
                m.fresh_exact_xray_https(3,self.sha)

    def test_probe_error_is_safe_pre_mutation_failure(self):
        with mock.patch.object(m,"run",side_effect=RuntimeError("PROCESS_FAILED")),\
             self.assertRaisesRegex(RuntimeError,"XRAY_EXACT_ISOLATED_HTTPS_UNVERIFIED"):
            m.fresh_exact_xray_https(3,self.sha)

    def test_proof_helper_must_be_owned_and_regular(self):
        for attr,value in (("is_symlink",True),("is_file",False)):
            with self.subTest(attr=attr):
                getattr(self.helper,attr).return_value=value
                with mock.patch.object(m,"run") as cmd,\
                     self.assertRaisesRegex(RuntimeError,"XRAY_FRESH_PROOF_HELPER_UNTRUSTED"):
                    m.fresh_exact_xray_https(1,self.sha)
                cmd.assert_not_called()
                getattr(self.helper,attr).return_value=not value
        self.helper.stat.return_value.st_uid=1000
        with self.assertRaisesRegex(RuntimeError,"XRAY_FRESH_PROOF_HELPER_UNTRUSTED"):
            m.fresh_exact_xray_https(1,self.sha)

    def test_provider_rotates_during_probe_never_accepted(self):
        def change(*args,**kwargs):
            self.provider.write_bytes(b"proxies: []\n# rotated\n")
            return "FRESH_CANDIDATE_PROOF=PASS_NO_MUTATION"
        with mock.patch.object(m,"run",side_effect=change),\
             self.assertRaisesRegex(RuntimeError,"XRAY_PROVIDER_CHANGED_DURING_PROOF"):
            m.fresh_exact_xray_https(3,self.sha)

    def test_executor_must_call_fresh_proof_before_watchdog_arm(self):
        source=SOURCE.read_text()
        body=source.split("    def preflight(self,failed,candidate):",1)[1].split(
            "    def arm_watchdog(self):",1)[0]
        self.assertIn("fresh_exact_xray_https(self.index,self.provider_hash)",body)
        self.assertNotIn("NODE_BASIC_NETWORK",body)
        self.assertIn("fields.get(\"NODE_PROVIDER_SHA256\")!=self.provider_hash",body)
        logic=(ROOT/"src/awg-xray-activation-transaction.py").read_text()
        self.assertLess(logic.index("backend.preflight(failed, candidate)"),
                        logic.index("backend.arm_watchdog()"))
        self.assertNotIn("systemctl",body)
        self.assertNotIn("awg-transit-routing\",\"disable",body)

if __name__=="__main__": unittest.main()
