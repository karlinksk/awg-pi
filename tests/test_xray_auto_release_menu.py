#!/usr/bin/env python3
"""Candidate install policy smoke tests: Xray AUTO is portable and opt-in."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class XrayAutoReleaseMenu(unittest.TestCase):
    def test_install_defaults_and_preservation(self):
        s=(ROOT/"install.sh").read_text()
        self.assertIn('transports/mihomo/xray-auto.mode',s)
        self.assertIn('if [[ ! -e "$_XRAY_AUTO_MODE" ]]',s)
        self.assertIn('install_project_helper src/awg-menu /usr/local/sbin/awg-menu',s)
        self.assertIn('install_project_python_helper src/awg-xray-live-backend.py',s)
    def test_menu_has_visible_opt_in(self):
        s=(ROOT/"src/awg-menu").read_text()
        self.assertIn("mihomo_xray_auto_menu(){",s)
        self.assertIn('"$MIHOMO_NODE_POLICY" xray-auto enable',s)
        self.assertIn('"$MIHOMO_NODE_POLICY" xray-auto disable',s)
        self.assertIn('8) mihomo_xray_auto_menu ;;',s)
    def test_portable_authorization_not_only_test_hostname(self):
        backend=(ROOT/"src/awg-xray-live-backend.py").read_text()
        policy=(ROOT/"src/awg-mihomo-node-policy").read_text()
        self.assertIn('def xray_auto_authorized():',backend)
        self.assertIn('XRAY_AUTO_MODE.read_text().strip()=="1"',backend)
        self.assertIn('MIHOMO_XRAY_AUTO_MODE_FILE=',policy)
        self.assertIn('  xray-auto)',policy)
        self.assertIn('XRAY_AUTO_REQUIRES_CONFIGURED_AWG_BACKUP',policy)
        self.assertIn('XRAY_AUTO_REQUIRES_READY_OFF',policy)
if __name__=="__main__": unittest.main()
