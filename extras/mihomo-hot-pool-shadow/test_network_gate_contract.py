#!/usr/bin/env python3
"""Regression contract for AUTO+balanced network-eligibility gate.

Rootless, synthetic strings only; no connection, service, route, or provider I/O.
"""
import subprocess
import unittest
from pathlib import Path

GATE = Path("/usr/local/sbin/awg-mihomo-network-eligibility.py")

def call_gate(*, openai="PASS", chatgpt="UNKNOWN", youtube="PASS",
              reason="chatgpt_web_http_403", aggregate="UNKNOWN"):
    data = "\n".join((
        "SERVICE_ELIGIBILITY=" + aggregate,
        "SERVICE_CHECK_OPENAI_API=" + openai,
        "SERVICE_CHECK_CHATGPT_WEB=" + chatgpt,
        "SERVICE_CHECK_YOUTUBE_VIDEO=" + youtube,
        "SERVICE_REASON_CHATGPT_WEB=" + reason,
    )) + "\n"
    return subprocess.run(["/usr/bin/python3", "-B", str(GATE)],
                          input=data, text=True, capture_output=True, timeout=5)

class BalancedContract(unittest.TestCase):
    def test_403_with_24_decoded_frames_is_medium_eligible(self):
        r=call_gate()
        self.assertEqual(r.returncode, 0)
        self.assertIn("NETWORK_ELIGIBILITY=ELIGIBLE", r.stdout)
        self.assertIn("NETWORK_REASON=MEDIUM_NETWORK_CONFIDENCE", r.stdout)

    def test_chatgpt_urlerror_never_passes(self):
        r=call_gate(reason="chatgpt_web_URLError")
        self.assertEqual(r.returncode,1)
        self.assertIn("NETWORK_REASON=CHATGPT_NETWORK_UNCONFIRMED",r.stdout)

    def test_no_video_never_passes_even_if_api_pass(self):
        r=call_gate(youtube="UNKNOWN")
        self.assertEqual(r.returncode,1)
        self.assertIn("NETWORK_REASON=YOUTUBE_VIDEO_NOT_DECODED",r.stdout)

    def test_api_not_confirmed_never_passes(self):
        r=call_gate(openai="UNKNOWN")
        self.assertEqual(r.returncode,1)
        self.assertIn("NETWORK_REASON=OPENAI_API_NOT_CONFIRMED",r.stdout)

    def test_chatgpt_http200_with_24_decoded_frames(self):
        r=call_gate(chatgpt="PASS",reason="chatgpt_web_http_200",aggregate="PASS")
        self.assertEqual(r.returncode,0)
        self.assertIn("NETWORK_ELIGIBILITY=ELIGIBLE",r.stdout)

    def test_unknown_403_not_treated_as_browser_pass(self):
        r=call_gate()
        self.assertNotIn("BROWSER_PASS",r.stdout)
        self.assertIn("MEDIUM_NETWORK_CONFIDENCE",r.stdout)

if __name__=="__main__":
    unittest.main()