#!/usr/bin/env python3
"""Isolated TUN canary contract; no production routing or real hardware in CI."""
import ast
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
CANARY=ROOT/"scripts"/"awg-mihomo-xray-isolated-tun-canary.py"
class IsolatedTunContract(unittest.TestCase):
    def setUp(self):
        self.source=CANARY.read_text()
    def test_syntax_and_manual_only(self):
        ast.parse(self.source,filename=str(CANARY))
        self.assertIn('sys.argv[1]!="--confirm-isolated"',self.source)
        self.assertIn('AWG_ISOLATED_EXPECT_HOST',self.source)
        self.assertIn('expected!=output(["hostname"])',self.source)
    def test_separate_tun_never_mihomo0(self):
        self.assertIn('TUN="awgxtun0"',self.source)
        self.assertIn('auto-route":False',self.source)
        self.assertIn('auto-redirect":False',self.source)
        self.assertIn('profile":{"store-selected":False',self.source)
        self.assertIn('TUN_PACKETS=',self.source)
        self.assertIn('interface_bytes()>before',self.source)
    def test_no_global_route_or_active_service_changes(self):
        for disallowed in (
            '["ip","route","add"',
            '["ip","route","replace"',
            '["ip","rule","add"',
            '["systemctl","stop","awg-mihomo.service"',
            '["systemctl","restart","awg-mihomo.service"',
            '["systemctl","stop","awg-selection-monitor.service"',
            '"awg-transport","select"',
            '"awg-route","mode","transit"',
        ):
            self.assertNotIn(disallowed,self.source)
        self.assertIn("before100==after100 and before101==after101",self.source)
        self.assertIn("beforepolicy==afterpolicy",self.source)
    def test_protects_private_credential_files(self):
        self.assertIn('dir="/dev/shm"',self.source)
        self.assertIn('root.chmod(0o700)',self.source)
        self.assertIn('(root/"mihomo.yaml").chmod(0o600)',self.source)
        self.assertIn('adapter.atomic_json(root/"xray.json",xcfg)',self.source)
        self.assertIn('stop(mihomo);stop(xray)',self.source)
    def test_versioned_installer_and_backup(self):
        installer=(ROOT/"install.sh").read_text()
        update=(ROOT/"src/awg-update").read_text()
        self.assertIn("install_project_python_helper scripts/awg-mihomo-xray-isolated-tun-canary.py",installer)
        self.assertIn("usr/local/sbin/awg-mihomo-xray-isolated-tun-canary",update)
        self.assertNotIn("systemctl enable --now awg-mihomo-xray-isolated-tun-canary",installer)
if __name__=="__main__":unittest.main()
