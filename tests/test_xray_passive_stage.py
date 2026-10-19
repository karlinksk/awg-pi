#!/usr/bin/env python3
"""Non-privileged tests for the strictly passive test-Pi Xray staging gate."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/"scripts/awg-xray-passive-stage-testpi.sh"

class StageGateTests(unittest.TestCase):
    def test_safe_command_and_snapshot_rollback(self):
        s=STAGE.read_text()
        self.assertIn("XRAY_STAGE_PREFLIGHT=PASS",s)
        self.assertIn("RENDERER_DEFAULT_CHANGED",s)
        self.assertIn("systemctl is-active --quiet awg-mihomo.service",s)
        self.assertIn("git -C \"$ROOT\" status --porcelain",s)
        self.assertIn("install -m 0755",s)
        self.assertIn("BACKUP_ROOT=/var/backups/awg-gateway",s)
        self.assertIn("trap finish EXIT",s)
        self.assertIn("rollback || true",s)
        self.assertIn("STAGING=0",s)
        self.assertNotIn("systemctl restart",s)
        self.assertNotIn("systemctl enable --now",s)
        self.assertNotIn("awg-transit-routing disable",s)
        self.assertNotIn("node select-auto",s)

    def test_bash_syntax(self):
        p=subprocess.run(["bash","-n",str(STAGE)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_not_run_without_root(self):
        import os
        if os.geteuid()==0:self.skipTest("root-only negative case")
        p=subprocess.run(["bash",str(STAGE),"--check"],capture_output=True,text=True,timeout=8)
        self.assertNotEqual(p.returncode,0)
        self.assertIn("XRAY_STAGE_ERROR=ROOT_REQUIRED",p.stderr)

if __name__=="__main__":unittest.main()
