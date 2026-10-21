#!/usr/bin/env python3
"""Menu wiring test for Hot Pool/ordinary AUTO strategy; no root or real dialog."""
import os,subprocess,tempfile,unittest
from pathlib import Path
source=(Path(__file__).resolve().parents[1]/"src"/"awg-menu").read_text()
def extract(name):
 start=source.index(name+"(){")
 end=source.index("\n}\n",start)+2
 return source[start:end]
class MenuStrategyTests(unittest.TestCase):
 def test_menu_command_wiring(self):
  sub=extract("mihomo_auto_strategy_menu")
  self.assertIn('"$MIHOMO_NODE_POLICY" auto-strategy status',sub)
  self.assertIn('"$MIHOMO_NODE_POLICY" auto-strategy ready',sub)
  self.assertIn('"$MIHOMO_NODE_POLICY" auto-strategy classic',sub)
  self.assertIn('confirm "Обычный AUTO"',sub)
  top=extract("mihomo_node_policy_menu")
  self.assertIn('5 "Способ AUTO: Hot Pool / обычный"',top)
  self.assertIn('5) mihomo_auto_strategy_menu',top)
  self.assertIn('4) mihomo_node_auto_menu',top)
  self.assertNotIn('mihomo_node_menu',top)
  self.assertNotIn('standby-repair',top)
  advanced=extract("mihomo_advanced_menu")
  self.assertIn('5) mihomo_standby_repair_menu',advanced)
  self.assertIn('capture "$MIHOMO_NODE_POLICY" standby-repair',extract("mihomo_standby_repair_menu"))
 def test_dialog_choices_call_exact_policy(self):
  for choice,expected in (("1","status"),("2","ready"),("3","classic"),("0","")):
   with self.subTest(choice=choice),tempfile.TemporaryDirectory() as t:
    base=Path(t)
    script=base/"fake-policy"
    script.write_text("#!/bin/bash\nprintf '%s\\n' \"$*\" >>\"$TEST_CALLS\"\n")
    script.chmod(0o700)
    block=extract("mihomo_auto_strategy_menu")
    shell=r'''set -Eeuo pipefail
MIHOMO_NODE_POLICY="$TEST_POLICY"
BACKTITLE="test"
title=""
FIRST_DIALOG=0
dialog(){ if [[ -e "$TEST_SEEN" ]]; then return 1; fi; touch "$TEST_SEEN"; echo "$TEST_CHOICE" >&2; }
confirm(){ return 0; }
capture(){ "$@"; }
'''+block+'\nmihomo_auto_strategy_menu\n'
    r=subprocess.run(["bash","-c",shell],env={**os.environ,
      "TEST_POLICY":str(script),"TEST_CHOICE":choice,"TEST_CALLS":str(base/"calls"),"TEST_SEEN":str(base/"seen")},
      capture_output=True,text=True,timeout=1)
    self.assertEqual(r.returncode,0,r.stderr)
    calls=(base/"calls").read_text().strip() if (base/"calls").exists() else ""
    self.assertEqual(calls,"auto-strategy "+expected if expected else "")
 def test_menu_offline_no_transport_calls(self):
  block=extract("mihomo_auto_strategy_menu")
  self.assertNotIn("awg-transport select",block)
  self.assertNotIn("systemctl",block)
  self.assertNotIn("awg-mihomo-configure",block)
if __name__=="__main__":unittest.main()
