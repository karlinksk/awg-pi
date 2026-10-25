#!/usr/bin/env python3
"""Installer-first, opt-in menu and offline-only unified status wiring."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CatalogPackaging(unittest.TestCase):
 def test_clean_and_upgrade_versioned_install(self):
  s=(ROOT/"install.sh").read_text()
  self.assertIn("install_project_python_helper src/awg-mihomo-unified-nodes.py /usr/local/sbin/awg-mihomo-unified-nodes",s)
  self.assertNotIn("systemctl enable --now awg-mihomo-unified-nodes",s)
  self.assertNotIn("systemctl start awg-mihomo-unified-nodes",s)
  self.assertIn("No VPN onboarding during clean install",s)
 def test_menu_is_explicit_safe_network_probe(self):
  s=(ROOT/"src/awg-menu").read_text()
  section=s.split("mihomo_xray_vless_menu(){",1)[1].split("\n}\n",1)[0]
  self.assertIn("awg-mihomo-unified-nodes list",section)
  self.assertIn("awg-mihomo-unified-nodes probe",section)
  self.assertIn('confirm "Проверка Xray"',section)
  self.assertNotIn("awg-mihomo-configure node select-auto",section)
  self.assertNotIn("awg-transport select",section)
  self.assertNotIn("awg-mihomo-prepare",section)
 def test_backup_and_restore_include_helper_and_not_runtime_secrets(self):
  s=(ROOT/"src/awg-update").read_text()
  self.assertIn("    usr/local/sbin/awg-mihomo-unified-nodes \\",s)
  self.assertIn("    /usr/local/sbin/awg-mihomo-unified-nodes \\",s)
  self.assertIn("    var/lib/awg-pbr/xray-vless \\",s)
  self.assertNotIn("run/awg-pbr/xray-vless/config.json",s)
 def test_not_ready_no_fixed_count_or_live_routes(self):
  s=(ROOT/"src/awg-mihomo-unified-nodes.py").read_text()
  self.assertIn('print("UNIFIED_READY_GATE=OFF")',s)
  self.assertIn("MAX_PROBE=10",s)
  self.assertIn("indices=eligible[:MAX_PROBE]",s)
  self.assertNotIn('"systemctl","restart"',s)
  self.assertNotIn('"ip","route","replace"',s)
if __name__=="__main__":unittest.main()
