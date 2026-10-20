#!/usr/bin/env python3
"""Balanced network-only eligibility never implies authenticated chat."""
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/"src"/"awg-mihomo-network-eligibility.py"
POLICY=ROOT/"src"/"awg-mihomo-node-policy"
spec=importlib.util.spec_from_file_location("balanced_gate",GATE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class NetworkGateTests(unittest.TestCase):
    @staticmethod
    def probe(api="PASS",web="UNKNOWN",youtube="PASS",reason="chatgpt_web_antibot_challenge",
              aggregate="UNKNOWN"):
        return "\n".join((
            "SERVICE_ELIGIBILITY="+aggregate,
            "SERVICE_CHECK_OPENAI_API="+api,
            "SERVICE_CHECK_CHATGPT_WEB="+web,
            "SERVICE_CHECK_YOUTUBE_VIDEO="+youtube,
            "SERVICE_REASON_CHATGPT_WEB="+reason,
        ))+"\n"

    def test_real_cloudflare_403_is_network_eligible(self):
        self.assertEqual(m.qualify(self.probe()),("ELIGIBLE","MEDIUM_NETWORK_CONFIDENCE"))

    def test_real_http200_is_network_eligible(self):
        self.assertEqual(m.qualify(self.probe(web="PASS",reason="chatgpt_web_http_200",
                                               aggregate="PASS"))[0],"ELIGIBLE")

    def test_challenge_200_and_login_redirect_are_network_evidence(self):
        for reason in ("chatgpt_web_challenge","chatgpt_web_login_only"):
            self.assertEqual(m.qualify(self.probe(reason=reason))[0],"ELIGIBLE")

    def test_generic_403_only_counts_as_network_not_chat_success(self):
        self.assertEqual(m.qualify(self.probe(reason="chatgpt_web_http_403")),
                         ("ELIGIBLE","MEDIUM_NETWORK_CONFIDENCE"))
        self.assertIn("UNKNOWN",self.probe(reason="chatgpt_web_http_403"))

    def test_timeout_must_not_appear_eligible(self):
        self.assertEqual(m.qualify(self.probe(reason="chatgpt_web_TimeoutError"))[0],"UNKNOWN")

    def test_api_region_restriction_rejects(self):
        self.assertEqual(m.qualify(self.probe(api="FAIL"))[0],"UNKNOWN")

    def test_video_without_decoded_frames_rejects(self):
        self.assertEqual(m.qualify(self.probe(youtube="UNKNOWN"))[0],"UNKNOWN")

    def test_explicit_chat_fail_rejects(self):
        self.assertEqual(m.qualify(self.probe(web="FAIL",reason="chatgpt_region_denied"))[0],"UNKNOWN")

    def test_full_service_fail_rejects(self):
        self.assertEqual(m.qualify(self.probe(aggregate="FAIL"))[0],"UNKNOWN")

    def test_duplicate_fields_reject(self):
        self.assertEqual(m.qualify(self.probe()+"SERVICE_CHECK_OPENAI_API=PASS\n")[0],"UNKNOWN")

    def test_partial_or_malformed_probe_rejects(self):
        for content in ("","SERVICE_ELIGIBILITY=UNKNOWN\n","BROKEN\n",
                        "a"*8500):
            self.assertEqual(m.qualify(content)[0],"UNKNOWN")

    def test_malformed_unknown_extra_field_rejects(self):
        self.assertEqual(m.qualify(self.probe()+"SERVICE_TOKEN=secret\n")[0],"UNKNOWN")

    def test_cli_pass_and_no_full_chat_claim(self):
        result=subprocess.run(["python3","-B",str(GATE)],input=self.probe(),
                              text=True,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0)
        self.assertIn("NETWORK_ELIGIBILITY=ELIGIBLE",result.stdout)
        self.assertNotIn("CHATGPT_PASS",result.stdout)

    def test_negative_cli_exit(self):
        result=subprocess.run(["python3","-B",str(GATE)],input=self.probe(youtube="UNKNOWN"),
                              text=True,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,1)

class NetworkCandidatePolicyTests(unittest.TestCase):
    def test_readonly_gate_before_live_select(self):
        src=POLICY.read_text()
        self.assertIn('balanced)',src)
        self.assertIn('MIHOMO_NETWORK_GATE_BIN=',src)
        self.assertIn('service-scan --node "$candidate"',src)
        fixed=src.split("failover_fixed(){",1)[1].split("failover_auto(){",1)[0]
        auto=src.split("failover_auto(){",1)[1].split("failover(){",1)[0]
        for block in (fixed,auto):
            self.assertLess(block.index("service_candidate_allowed"),block.index("node select-auto"))
        self.assertIn('attempts < 3',fixed)
        self.assertIn('attempts < max_checks',auto)
        self.assertIn('local max_checks=3',auto)
        self.assertIn('max_checks=6',auto)
        self.assertIn('from_ready == 0',auto)

    def exercise(self,probe):
        src=POLICY.read_text()
        f="service_candidate_allowed(){"+src.split("service_candidate_allowed(){",1)[1].split("\n}\n",1)[0]+"\n}\n"
        with tempfile.TemporaryDirectory(prefix="awg-balanced-policy-",dir="/tmp") as temp:
            root=Path(temp)
            scan=root/"scan"
            scan.write_text("#!/bin/sh\ncat <<'SHADOW_RESULT'\n"+probe+"SHADOW_RESULT\nexit 1\n")
            scan.chmod(0o700)
            cmd=(f+"MIHOMO_SERVICE_GATE_MODE=balanced\n"
                 +f"MIHOMO_SERVICE_QUICKCHECK_BIN={scan}\nMIHOMO_NETWORK_GATE_BIN={GATE}\n"
                 +"service_candidate_allowed fake-node\n")
            return subprocess.run(["bash","-c",cmd],capture_output=True,text=True,timeout=8)

    def test_shell_balanced_pass_despite_legacy_unknown_exit(self):
        result=self.exercise(NetworkGateTests.probe())
        self.assertEqual(result.returncode,0)
        # Selection-monitor expects pure MIHOMO_NODE_FAILOVER=, not helper logs.
        self.assertEqual(result.stdout,"")


    def test_shell_rejects_unreachable_chat(self):
        self.assertNotEqual(self.exercise(NetworkGateTests.probe(
            reason="chatgpt_web_TimeoutError")).returncode,0)

    def test_shell_rejects_unproven_youtube(self):
        self.assertNotEqual(self.exercise(NetworkGateTests.probe(youtube="UNKNOWN")).returncode,0)

if __name__=="__main__":unittest.main()
