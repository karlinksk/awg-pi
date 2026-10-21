#!/usr/bin/env python3
"""Desktop Commander must appear ONLY in System menu, not domain list."""
from pathlib import Path
import unittest
import subprocess
ROOT=Path(__file__).resolve().parents[1]
class DcMenuPlacement(unittest.TestCase):
    def test_system_menu_visible_entry_and_handler(self):
        s=(ROOT/"src/awg-menu").read_text()
        system=s.split("system_menu(){",1)[1].split("\nwhile true; do\n  refresh_backtitle",1)[0]
        self.assertIn('9 "Desktop Commander — удалённый доступ"',system)
        self.assertIn('9) desktop_commander_menu ;;',system)
        self.assertIn('8 "Статистика трафика"',system)
        self.assertIn('0 "Назад"',system)
    def test_no_domain_menu_leak_and_continued_lines(self):
        s=(ROOT/"src/awg-menu").read_text()
        domain=s.split("domain_menu(){",1)[1].split("system_menu(){",1)[0]
        self.assertNotIn('9 "Desktop Commander — удалённый доступ"',domain)
        self.assertEqual(s.count('9 "Desktop Commander — удалённый доступ"'),1)
        for line in s.splitlines():
            if '9 "Desktop Commander — удалённый доступ"' in line:
                self.assertTrue(line.rstrip().endswith("\\"),line)
    def test_policy_menu_dialog_has_valid_continuations(self):
        s=(ROOT/"src/awg-menu").read_text()
        section=s.split("mihomo_node_policy_menu(){",1)[1].split("\\nmihomo_candidate_auto_apply(){",1)[0]
        line=next(x for x in section.splitlines() if '8 "Xray VLESS в AUTO:' in x)
        self.assertTrue(line.endswith(chr(92)), line)
        self.assertFalse(line.endswith(chr(92)*2), line)
        self.assertIn('0 "Назад"',section)
    def test_bash_syntax(self):
        p=subprocess.run(["bash","-n",str(ROOT/"src/awg-menu")],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
if __name__=="__main__": unittest.main()
