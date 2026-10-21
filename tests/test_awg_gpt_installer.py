#!/usr/bin/env python3
"""Clean-install gate for the deliberately restricted administrative helper."""
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
class AdminHelperInstall(unittest.TestCase):
    def test_helper_installed_by_fresh_and_upgrade_path(self):
        s=(ROOT/"install.sh").read_text()
        self.assertIn('GPT_CLI="/usr/local/sbin/awg-gpt"',s)
        self.assertIn('install_project_helper src/awg-gpt "$GPT_CLI"',s)
        self.assertIn('visudo -cf /etc/sudoers.d/awg-gpt-menu.tmp',s)
        self.assertIn('NOPASSWD: /usr/local/sbin/awg-gpt menu-update',s)
    def test_helper_only_allows_verified_menu_update(self):
        s=(ROOT/"src/awg-gpt").read_text()
        self.assertIn('menu-update)',s)
        self.assertIn('sha256sum -c -',s)
        self.assertIn('bash -n "$tmp"',s)
        self.assertIn('cp -a /usr/local/sbin/awg-menu',s)
        self.assertNotIn('eval ',s)
        self.assertNotIn('bash -c',s)
    def test_shell_syntax(self):
        for path in (ROOT/"src/awg-gpt",ROOT/"install.sh"):
            p=subprocess.run(["bash","-n",str(path)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
if __name__=="__main__": unittest.main()
