#!/usr/bin/env python3
"""One-shot Selective Xray AUTO trace contract: harmless, nonsecret events."""
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"scripts/awg-xray-selective-one-shot-failover.sh"
S=SRC.read_text()
class CanaryTrace(unittest.TestCase):
    def test_syntax(self):
        proc=subprocess.run(["bash","-n",str(SRC)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
    def test_environment_verified_before_fault(self):
        a=S.index('systemctl restart awg-selection-monitor\neffective="$(systemctl show')
        b=S.index("die CANARY_EFFECTIVE_ENVIRONMENT_NOT_APPLIED")
        c=S.index("systemctl stop awg-mihomo\n")
        self.assertTrue(a<b<c)
        self.assertIn("MIHOMO_NODE_POLICY_CLI=$dir/trace-node-policy",S)
        self.assertIn("MIHOMO_POOL_CLI=$dir/native-exhausted",S)
    def test_trace_logs_only_fixed_safe_codes(self):
        self.assertIn("PHASE=NODE_POLICY_ENABLED",S)
        self.assertIn("PHASE=NODE_POLICY_NOT_ENABLED",S)
        self.assertIn("PHASE=NODE_FAILOVER_ENTER",S)
        self.assertIn("PHASE=XRAY_CANDIDATE_FRESH",S)
        self.assertIn("PHASE=XRAY_CANDIDATE_MISSING",S)
        self.assertIn("PHASE=NODE_FAILOVER_RETURN_$result",S)
        self.assertIn("PHASE=XRAY_EXECUTOR_ABORTED",S)
        self.assertIn('cat "$dir/node.out"',S)
        self.assertIn('2>"$dir/node.err"',S)
        self.assertNotIn('cat "$dir/node.err"',S)
    def test_test_executables_never_live_on_noexec_run(self):
        self.assertIn('mktemp -d /dev/shm/awg-xray-auto-test.', S)
        self.assertNotIn('mktemp -d /run/awg-xray-auto-test.', S)
        self.assertIn('"$dir/exec-preflight" || die TEMP_RUNTIME_NOEXEC', S)
        self.assertIn('CANARY_TMPFS_EXEC=PASS', S)
        self.assertLess(S.index('CANARY_TMPFS_EXEC=PASS'),
                        S.index('systemd-run --quiet --collect'))

    def test_watchdog_armed_before_failure(self):
        self.assertLess(S.index("systemd-run --quiet --collect"),
                        S.index("systemctl stop awg-mihomo\n"))
        self.assertIn("RECOVERY_SCRIPT=PASS",S)
if __name__=="__main__":
    unittest.main()
