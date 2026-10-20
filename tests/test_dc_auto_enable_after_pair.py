#!/usr/bin/env python3
"""Consent and persistence contract for optional Desktop Commander pairing."""
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
class DesktopCommanderPairing(unittest.TestCase):
    def test_shell_syntax(self):
        for path in (ROOT/"src/awg-dc", ROOT/"install.sh"):
            p=subprocess.run(["bash","-n",str(path)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
    def test_interactive_pair_autostart_only_after_local_session(self):
        s=(ROOT/"src/awg-dc").read_text()
        self.assertIn("trap post_pair_enable EXIT",s)
        self.assertIn("if session_ok; then",s)
        self.assertIn('sudo /usr/local/bin/awg-dc enable "$DC_USER"',s)
        self.assertIn("AWG_DC_AUTOSTART=NOT_CHANGED_NO_VERIFIED_PAIRING",s)
        self.assertIn("    (run_agent)",s)
        self.assertIn("(( EUID != 0 )) || fail PAIR_AS_NONROOT_USER",s)
    def test_clean_install_does_not_autopair_or_enable_without_consent(self):
        installer=(ROOT/"install.sh").read_text()
        self.assertIn('install_project_helper src/awg-dc "$DC_CLI"',installer)
        self.assertIn("install_project_unit units/awg-dc-remote@.service",installer)
        self.assertNotIn('"$DC_CLI" pair',installer)
        self.assertNotIn('"$DC_CLI" enable',installer)
    def test_nonroot_service_requires_saved_pairing(self):
        unit=(ROOT/"units/awg-dc-remote@.service").read_text()
        self.assertIn("User=%i",unit)
        self.assertIn("ConditionPathExists=/home/%i/.desktop-commander-device/device.json",unit)
if __name__=="__main__": unittest.main()
