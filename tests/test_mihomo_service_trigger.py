#!/usr/bin/env python3
"""Service-trigger regression: only explicit FAIL, never Cloudflare UNKNOWN."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

MONITOR=Path(__file__).resolve().parents[1]/"src"/"awg-selection-monitor"

class TriggerTests(unittest.TestCase):
    @staticmethod
    def extract(source, name):
        return name+"(){"+source.split(name+"(){",1)[1].split("\n}\n",1)[0]+"\n}\n"

    def simulate(self, first="FAIL", second="FAIL", mode="require"):
        with tempfile.TemporaryDirectory(prefix="awg-service-trigger-",dir="/tmp") as temp:
            root=Path(temp)
            checker=root/"fake-check"
            node=root/"node-name"
            node.write_text("fake-node-1\n")
            def check_script(status):
                payload=json.dumps({"status":status},separators=(",",":")) if status!="INVALID" else "not-json"
                return "#!/bin/sh\nprintf '%s\\n' '"+payload+"'\nexit 1\n"
            checker.write_text(check_script(first))
            checker.chmod(0o700)
            source=MONITOR.read_text()
            body=self.extract(source,"service_probe_verdict")
            body+=self.extract(source,"service_healthy_mihomo")
            body+=f'''
MIHOMO_SERVICE_GATE_MODE={mode}
MIHOMO_SERVICE_CHECK_BIN={checker}
MIHOMO_SERVICE_NODE_FILE={node}
MIHOMO_SERVICE_CHECK_INTERVAL=60
SERVICE_LAST_TS=0
SERVICE_BAD_PROBES=0
SERVICE_LAST_NODE=""
date(){{ echo "$MOCK_NOW"; }}
MOCK_NOW=1000
service_healthy_mihomo; echo "ONE:$?"
'''
            # Original test used exit codes only; now the JSON status matters.
            content=check_script(second)
            body+=f"cat > {checker} <<'AWG_FAKE_SCRIPT_EOF'\n{content}AWG_FAKE_SCRIPT_EOF\nchmod 700 {checker}\n"
            body+='''MOCK_NOW=1005
service_healthy_mihomo; echo "CACHED:$?"
MOCK_NOW=1061
service_healthy_mihomo; echo "TWO:$?"
'''
            # Write script file via a non-executing heredoc to avoid nested
            # escape/newline corruption in the shell command.
            script=root/"simulate.sh"
            script.write_text(body)
            result=subprocess.run(["bash",str(script)],capture_output=True,text=True,timeout=8)
            return result

    def test_two_independent_hard_failures_required(self):
        result=self.simulate()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("ONE:0",result.stdout)
        self.assertIn("CACHED:0",result.stdout)
        self.assertIn("TWO:1",result.stdout)

    def test_unknown_after_explicit_fail_resets_streak(self):
        result=self.simulate(first="FAIL",second="UNKNOWN")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("TWO:0",result.stdout)

    def test_cloudflare_unknown_stays_healthy(self):
        result=self.simulate(first="UNKNOWN",second="UNKNOWN")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("TWO:0",result.stdout)

    def test_unknown_then_fail_is_only_first_fail(self):
        result=self.simulate(first="UNKNOWN",second="FAIL")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("TWO:0",result.stdout)

    def test_success_resets_streak(self):
        result=self.simulate(first="FAIL",second="PASS")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("TWO:0",result.stdout)

    def test_malformed_json_not_evidence_of_failure(self):
        result=self.simulate(first="INVALID",second="INVALID")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("TWO:0",result.stdout)

    def test_gate_off_does_not_trigger(self):
        result=self.simulate(mode="off")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("TWO:0",result.stdout)

    def test_unknown_mode_fails_closed(self):
        result=self.simulate(mode="bogus")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("ONE:1",result.stdout)

    def test_json_status_is_inspected_not_just_exit_code(self):
        text=MONITOR.read_text()
        self.assertIn('case "$verdict" in',text)
        self.assertIn('FAIL) SERVICE_BAD_PROBES=',text)
        self.assertIn('PASS|UNKNOWN) SERVICE_BAD_PROBES=0',text)
        self.assertIn('if [[ "$current" != mihomo ]] || service_healthy_mihomo; then',text)
        self.assertIn('--proxy-port 7890 --timeout 4',text)

    def test_no_router_or_nas_operations(self):
        source=MONITOR.read_text()
        self.assertNotIn("ssh mikrotik",source.lower())
        self.assertNotIn("nas-backup",source.lower())

if __name__ == "__main__":
    unittest.main()
