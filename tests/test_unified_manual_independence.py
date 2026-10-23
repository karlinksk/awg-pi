#!/usr/bin/env python3
"""Manual 4-way engine switching remains independent of automatic failover."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
MENU=(ROOT/"src/awg-menu").read_text()
MANUAL=(ROOT/"src/awg-xray-manual-switch.py").read_text()
POLICY=(ROOT/"src/awg-mihomo-node-policy").read_text()

class ManualIndependence(unittest.TestCase):
    def test_same_unified_picker_manual_from_both_engines(self):
        body=MENU.split("mihomo_node_menu(){",1)[1].split("\n}\n",1)[0]
        self.assertIn('mihomo_pool_pick live "Точка выхода Mihomo / Xray"',body)
        self.assertIn('engine="$(sed -n',body)
        self.assertIn('if [[ "$engine" == XRAY ]]; then',body)
        self.assertIn('"$XRAY_MANUAL_SWITCH" apply "$index"',body)
        self.assertIn('"$XRAY_MANUAL_SWITCH" native-apply "$node_name"',body)
        self.assertNotIn('failover_unified ',body)
        self.assertNotIn('xray_bridge_present',body)

    def test_manual_requires_fresh_exact_preflight_not_cached_ok(self):
        self.assertIn('preflight_mihomo(name,info)',MANUAL)
        self.assertIn('preflight_xray(index,info)',MANUAL)
        self.assertIn('def inspect_native(name)',MANUAL)
        self.assertIn('def native_return(name)',MANUAL)
        self.assertIn('def apply(index)',MANUAL)
        self.assertIn('def choose(node)',MANUAL)
        self.assertIn('native_tun_proof()',MANUAL)

    def test_auto_failover_changes_neither_user_policy_nor_manual_actions(self):
        auto=POLICY.split('failover_unified(){',1)[1].split("\n}\n",1)[0]
        for forbidden in ('set_auto','set_fixed','set_manual',
                          'manual_selection_apply','atomic_mode',
                          'atomic_order','native-apply','native-preview'):
            self.assertNotIn(forbidden,auto)
        self.assertNotIn('MIHOMO_XRAY_NATIVE_RECOVERY_CLI" apply',auto)
        self.assertIn('MIHOMO_NODE_POLICY=UNCHANGED',MANUAL)

    def test_manual_native_return_clears_owned_xray_dropin(self):
        body=MANUAL.split("def native_return(name):",1)[1].split("\ndef save_snap(",1)[0]
        self.assertIn('BOOT.unlink(missing_ok=True)',body)
        self.assertIn('SELECTED.unlink(missing_ok=True)',body)
        self.assertIn('cmd("systemctl","daemon-reload")',body)
        new=MANUAL.split("def dead_xray_xray(index):",1)[1].split("\nclass DeadXrayPreflight",1)[0]
        self.assertIn('native_env("MIHOMO_XRAY_VLESS_BRIDGE","auto")',new)
        self.assertIn("AWG_XRAY_MANUAL=1",new)
        self.assertIn('Environment="MIHOMO_XRAY_VLESS_BRIDGE=1"',new)

if __name__=="__main__":
    unittest.main()
