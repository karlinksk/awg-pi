#!/usr/bin/env python3
"""Opt-in short TTL authenticated Chrome acceptance + actual decoded video gate."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/"src"/"awg-mihomo-node-policy"
MONITOR=ROOT/"src"/"awg-selection-monitor"

class BrowserCandidateGate(unittest.TestCase):
    @staticmethod
    def function():
        source=POLICY.read_text()
        return "service_candidate_allowed(){"+source.split("service_candidate_allowed(){",1)[1].split("\n}\n",1)[0]+"\n}\n"

    def run_gate(self,*,proof="PASS",api="PASS",video="PASS",chat="UNKNOWN",
                 service="UNKNOWN",mode="browser",quick_exit=1):
        with tempfile.TemporaryDirectory(prefix="awg-browser-policy-",dir="/tmp") as temporary:
            temp=Path(temporary)
            helper=temp/"proof"
            probe=temp/"probe"
            cache=temp/"cache"
            def write(path,content):
                path.write_text("#!/bin/sh\n"+content)
                path.chmod(0o700)
            write(helper,f'echo BROWSER_PROOF={proof}\nexit '+("0" if proof=="PASS" else "1")+"\n")
            write(probe,(f'echo SERVICE_ELIGIBILITY={service}\n'
                        f'echo SERVICE_CHECK_OPENAI_API={api}\n'
                        f'echo SERVICE_CHECK_YOUTUBE_VIDEO={video}\n'
                        f'echo SERVICE_CHECK_CHATGPT_WEB={chat}\n'
                        f'echo SERVICE_EGRESS_IPV4=93.184.216.34\n'
                        f'exit {quick_exit}\n'))
            write(cache,"echo SERVICE_ELIGIBILITY=PASS\nexit 0\n")
            script=self.function()+f'''
MIHOMO_SERVICE_GATE_MODE={mode}
MIHOMO_BROWSER_PROOF_BIN={helper}
MIHOMO_SERVICE_QUICKCHECK_BIN={probe}
MIHOMO_SERVICE_GATE_BIN={cache}
service_candidate_allowed candidate-A
'''
            return subprocess.run(["bash","-c",script],capture_output=True,text=True,timeout=8)

    def test_operator_browser_proof_plus_video_and_api_pass(self):
        self.assertEqual(self.run_gate().returncode,0)

    def test_both_services_full_autocheck_also_requires_browser_proof(self):
        self.assertNotEqual(self.run_gate(proof="UNKNOWN",service="PASS",chat="PASS",quick_exit=0).returncode,0)

    def test_stale_or_missing_browser_proof_rejects_candidate(self):
        self.assertNotEqual(self.run_gate(proof="UNKNOWN").returncode,0)

    def test_live_video_unknown_rejects_candidate(self):
        self.assertNotEqual(self.run_gate(video="UNKNOWN").returncode,0)

    def test_live_video_fail_rejects_candidate(self):
        self.assertNotEqual(self.run_gate(video="FAIL").returncode,0)

    def test_live_openai_region_denial_rejects_candidate(self):
        self.assertNotEqual(self.run_gate(api="FAIL").returncode,0)

    def test_chatgpt_explicit_fail_cannot_be_overridden(self):
        self.assertNotEqual(self.run_gate(chat="FAIL").returncode,0)

    def test_full_service_fail_cannot_be_overridden(self):
        self.assertNotEqual(self.run_gate(service="FAIL").returncode,0)

    def test_egress_ip_required_by_candidate_gate(self):
        source=POLICY.read_text()
        self.assertIn('SERVICE_EGRESS_IPV4=',source)
        self.assertIn('--egress-ip "$egress"',source)

    def test_manual_claim_alone_not_enough(self):
        self.assertNotEqual(self.run_gate(api="UNKNOWN",video="UNKNOWN").returncode,0)

    def test_browser_mode_accepts_full_service_pass_with_browser_evidence(self):
        self.assertEqual(self.run_gate(service="PASS",chat="PASS",quick_exit=0).returncode,0)

    def test_require_legacy_mode_still_intact(self):
        self.assertEqual(self.run_gate(mode="require",service="PASS",quick_exit=0).returncode,0)

    def test_off_preserves_original_gate(self):
        self.assertEqual(self.run_gate(mode="off",proof="UNKNOWN",video="UNKNOWN").returncode,0)

    def test_unknown_mode_fails_closed(self):
        self.assertNotEqual(self.run_gate(mode="untrusted").returncode,0)

    def test_live_gate_disabled_unless_explicit_mode(self):
        source=POLICY.read_text()
        self.assertIn('MIHOMO_SERVICE_GATE_MODE_FILE=',source)
        self.assertIn('MIHOMO_BROWSER_PROOF_BIN=',source)
        self.assertIn('service-scan --node "$candidate"',source)
        self.assertIn('attempts < 3',source)
        self.assertIn('MIHOMO_SERVICE_GATE_MODE" == browser',source)
        self.assertIn('require|browser)',MONITOR.read_text())

if __name__=="__main__":
    unittest.main()
