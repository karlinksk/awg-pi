#!/usr/bin/env python3
"""Installation preparation must not modify the active Pi without a snapshot."""
import subprocess
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/awg-v13-xray-testpi-preflight.sh"

class TestXrayPiPreflight(unittest.TestCase):
    def test_shell_syntax_and_two_explicit_modes(self):
        p=subprocess.run(["bash","-n",str(SCRIPT)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        source=SCRIPT.read_text()
        self.assertIn("action=\"$1\"",source)
        self.assertIn("action\" == --check || \"$action\" == --snapshot",source)
        self.assertIn("BACKUP=NOT_PERFORMED",source)
        self.assertIn("BACKUP=VERIFIED",source)
        self.assertIn("UPGRADE=NOT_STARTED",source)
        self.assertNotIn("bash install.sh",source)
        self.assertNotIn("awg-transport select",source)
        self.assertNotIn("systemctl restart",source)
        self.assertNotIn("systemctl stop",source)
    def test_pinned_test_pi_only(self):
        source=SCRIPT.read_text()
        self.assertIn("hostname -s",source)
        self.assertIn("awg-upgrade",source)
        self.assertIn("SOURCE_COMMIT=$current",source)
        self.assertIn('[[ "$current" == "$expected" ]]',source)
        self.assertIn("GATEWAY_BACKUP=VERIFIED",source)
        self.assertIn("tar -tzf",source)
        self.assertIn("preinstall-state.txt",source)
    def test_preflight_rejects_invalid_commit_without_privileges(self):
        result=subprocess.run(["bash",str(SCRIPT),"--check","bad-commit"],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2)
        self.assertNotIn("BACKUP=VERIFIED",result.stdout)
if __name__=="__main__":unittest.main()
