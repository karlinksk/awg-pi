#!/usr/bin/env python3
"""New Xray renderer on upgrade is NOT a live running Mihomo controller alias."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
class UpgradeBridge(unittest.TestCase):
    def test_running_mihomo_does_not_implicitly_restart_on_upgrade(self):
        source=(ROOT/"install.sh").read_text()
        self.assertIn("XRAY_MANUAL_SWITCH=REQUIRES_CONTROLLED_MIHOMO_CONFIG_RELOAD",source)
        self.assertIn("_xray_live_alias=",source)
        self.assertIn("if (( UPGRADE_EXISTING == 1 ))",source)
        self.assertIn("127.0.0.1:9090/proxies/AWG-MIHOMO",source)
        self.assertIn("не выполняйте Xray manual",source)
        self.assertNotIn("systemctl restart awg-mihomo.service",source)
    def test_routing_and_recovery_are_not_claimed_by_renderer_upgrade(self):
        source=(ROOT/"src/awg-mihomo-config").read_text()
        self.assertIn("default-selected:",source)
        self.assertIn("AWG-XRAY-VLESS-LOCAL",source)
        manual=(ROOT/"src/awg-xray-manual-switch.py").read_text()
        self.assertIn("XRAY_BRIDGE_NOT_IN_RUNNING_CONFIG",manual)
if __name__=="__main__":unittest.main()
