#!/usr/bin/env python3
"""Service-trigger regression with a synthetic clock and fake service checker."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

MONITOR=Path(__file__).resolve().parents[1]/"src"/"awg-selection-monitor"

class TriggerTests(unittest.TestCase):
    def source_func(self):
        source=MONITOR.read_text()
        return "service_healthy_mihomo(){"+source.split("service_healthy_mihomo(){",1)[1].split("\n}\n",1)[0]+"\n}\n"

    def simulate(self, first_fail=True, second_fail=True, mode="require"):
        with tempfile.TemporaryDirectory(prefix="awg-service-trigger-",dir="/tmp") as temp:
            root=Path(temp)
            checker=root/"fake-check"
            node=root/"node-name"
            node.write_text("fake-node-1\n")
            checker.write_text("#!/bin/sh\nexit 1\n")
            checker.chmod(0o700)
            body=self.source_func()
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
            if not second_fail:
                body+=f"printf '#!/bin/sh\\nexit 0\\n' > {checker}\nchmod 700 {checker}\n"
            body+='''
MOCK_NOW=1005
service_healthy_mihomo; echo "CACHED:$?"
MOCK_NOW=1061
service_healthy_mihomo; echo "TWO:$?"
'''
            result=subprocess.run(["bash","-c",body],capture_output=True,text=True,timeout=8)
            return result

    def test_failures_need_two_independent_observations(self):
        r=self.simulate()
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("ONE:0",r.stdout)
        self.assertIn("CACHED:0",r.stdout)
        self.assertIn("TWO:1",r.stdout)

    def test_success_resets_negative_streak(self):
        r=self.simulate(second_fail=False)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("ONE:0",r.stdout)
        self.assertIn("TWO:0",r.stdout)

    def test_gate_off_does_not_trigger(self):
        r=self.simulate(mode="off")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("TWO:0",r.stdout)

    def test_unknown_mode_is_fail_closed(self):
        r=self.simulate(mode="bogus")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("ONE:1",r.stdout)

    def test_live_path_only_used_in_optin_mode(self):
        source=MONITOR.read_text()
        self.assertIn('if [[ "$current" != mihomo ]] || service_healthy_mihomo; then',source)
        self.assertIn('MIHOMO_SERVICE_GATE_MODE_FILE=',source)
        self.assertIn('MIHOMO_SERVICE_CHECK_INTERVAL="${MIHOMO_SERVICE_CHECK_INTERVAL:-60}"',source)
        self.assertIn('--proxy-port 7890 --timeout 4',source)

    def test_no_router_or_nas_operations(self):
        text=MONITOR.read_text()
        self.assertNotIn("ssh mikrotik",text.lower())
        self.assertNotIn("nas-backup",text.lower())

if __name__=="__main__":
    unittest.main()
