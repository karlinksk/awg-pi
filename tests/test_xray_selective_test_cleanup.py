#!/usr/bin/env python3
"""One-shot Xray Selective success and passive cleanup static safety gates."""
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
RUN=(ROOT/"scripts/awg-xray-selective-one-shot-failover.sh").read_text()
CLEAN=(ROOT/"scripts/awg-xray-selective-test-cleanup.sh").read_text()

class SelectiveTestCleanup(unittest.TestCase):
    def test_shell_syntax(self):
        for name in ("awg-xray-selective-one-shot-failover.sh",
                     "awg-xray-selective-test-cleanup.sh"):
            p=subprocess.run(["bash","-n",str(ROOT/"scripts"/name)],
                             capture_output=True,text=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stderr)
    def test_no_literal_newline_command_in_tun_gate(self):
        self.assertIn('api mihomo0 &&\n     xray_transaction_committed;then first=XRAY_TUN',RUN)
        self.assertNotIn('&&\\n     xray_transaction_committed',RUN)
    def test_cleanup_only_test_pi_and_verified_awg(self):
        for key in ("TESTPI_ROOT_REQUIRED","NOT_SELECTIVE",
                    "AWG_NOT_HEALTHY_SELECTED","AWG_ROUTE_",
                    "AWG_CHANGED_UNDER_LOCK","ACTIVE_MIHOMO_UNEXPECTED",
                    "EXPERIMENT_WATCHDOG_STILL_ACTIVE","TEST_CANARY_STILL_ACTIVE",
                    "FOREIGN_BRIDGE_CONTENT","ORIGINAL_NODE_PROOF_MISSING"):
            self.assertIn(key,CLEAN)
    def test_cleanup_preserves_independent_awg(self):
        self.assertIn('systemctl stop "$XRAY_UNIT"',CLEAN)
        self.assertIn('systemctl disable "$XRAY_UNIT"',CLEAN)
        self.assertNotIn('systemctl stop awg-quick',CLEAN)
        self.assertNotIn('awg-transport select',CLEAN)
        self.assertNotIn('awg-pbr-failopen',CLEAN)
        self.assertNotIn('awg-transit-routing',CLEAN)
        self.assertNotIn('systemctl start awg-mihomo',CLEAN)
        self.assertIn('ACTIVE_TRANSPORT=AWG_UNCHANGED',CLEAN)
    def test_one_shot_watchdog_recovery_invokes_guarded_cleanup(self):
        self.assertIn(
            'install -o root -g root -m 0700 "$root/scripts/awg-xray-selective-test-cleanup.sh" "$dir/test-cleanup"',
            RUN)
        self.assertIn('XRAY_TEST_RECOVER_ACTIVE=1 "$dir/test-cleanup" "$dir"',RUN)
        self.assertLess(RUN.index('"$dir/test-cleanup" "$dir"'),
                        RUN.index("systemctl restart awg-selection-monitor"))
        self.assertIn('EXTERNAL_TEST_STILL_ACTIVE',CLEAN)
        self.assertIn('XRAY_TEST_RECOVER_ACTIVE',CLEAN)
        self.assertIn('EXPERIMENT_WATCHDOG_STILL_ACTIVE',CLEAN)

    def test_second_fault_requires_independent_auto_awg_proof(self):
        self.assertIn("automatic_awg_recovery_verified(){",RUN)
        self.assertIn("if automatic_awg_recovery_verified;then second=AWG;break;fi",RUN)
        self.assertIn("! up awg-xray-vless && ! up awg-mihomo",RUN)
        self.assertIn("api awg0",RUN)
        self.assertIn("AWG_ROUTE_POST_",RUN)
        self.assertIn("! up awg-xray-vless || die XRAY_FAULT_DID_NOT_STOP",RUN)
        self.assertIn("SELECTIVE_XRAY_AUTO_FAILOVER=NOT_VERIFIED",RUN)
        self.assertIn('if [[ "$first" != XRAY_TUN || "$second" != AWG ]]',RUN)
        self.assertLess(RUN.index('echo "SECOND_RESULT=$second"'),
                        RUN.index('bash "$dir/recover"'))
        self.assertLess(RUN.index('bash "$dir/recover"'),
                        RUN.index("SELECTIVE_XRAY_AUTO_FAILOVER=PASS"))

    def test_backup_before_removal(self):
        self.assertLess(CLEAN.index('echo XRAY_CLEANUP_BACKUP=VERIFIED'),
                        CLEAN.index('systemctl stop "$XRAY_UNIT"'))
        self.assertLess(CLEAN.index('cp -a -- "$OLD_NODE"'),
                        CLEAN.index('mv -f -- "$CURRENT.test-restore.$$" "$CURRENT"'))
        self.assertIn('NATIVE_NODE_SELECTION=RESTORED_NOT_LIVE_TESTED',CLEAN)
if __name__=="__main__":
    unittest.main()
