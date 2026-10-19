#!/usr/bin/env python3
"""Offline test: optional Xray local SOCKS5 is selectable only when explicit opt-in."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"src"/"awg-mihomo-config"
INSTALL=ROOT/"install.sh"

class TestXrayConfig(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory()
  self.addCleanup(t.cleanup)
  self.root=Path(t.name)
  self.provider=self.root/"subscription.yaml"
  self.provider.write_text(yaml.safe_dump({"proxies":[{
   "name":"LIVE-NODE","type":"ss","server":"198.51.100.25","port":443,
   "cipher":"aes-128-gcm","password":"synthetic"}]}))
  self.selected=self.root/"selected.json";self.selected.write_text('{"sha256":"synthetic"}')
  self.xray=self.root/"xray";self.xray.write_text("#!/bin/sh\n");self.xray.chmod(0o700)
  self.env=os.environ.copy()
  self.env.update(
   MIHOMO_ENV_FILE=str(self.root/"no-env"),
   MIHOMO_PROVIDER_FILE=str(self.provider),
   MIHOMO_NODE_FILTER="LIVE-NODE",
   MIHOMO_ENDPOINT_IP="198.51.100.25",
   MIHOMO_XRAY_SELECTED=str(self.selected),MIHOMO_XRAY_CORE=str(self.xray))
 def config(self,option):
  result=subprocess.run(["bash",str(CONFIG)],capture_output=True,text=True,
                        env={**self.env,"MIHOMO_XRAY_VLESS_BRIDGE":option},timeout=6)
  return result
 def test_default_output_unchanged(self):
  result=self.config("0")
  self.assertEqual(result.returncode,0,result.stderr)
  d=yaml.safe_load(result.stdout)
  self.assertNotIn("proxies",d)
  self.assertEqual(d["proxy-groups"][0]["use"],["subscription"])
  self.assertNotIn("proxies",d["proxy-groups"][0])
 def test_explicit_optin_bridge(self):
  r=self.config("1")
  self.assertEqual(r.returncode,0,r.stderr)
  d=yaml.safe_load(r.stdout)
  p=d["proxies"][0]
  self.assertEqual(p["type"],"socks5")
  self.assertEqual(p["server"],"127.0.0.1")
  self.assertEqual(p["port"],17892)
  self.assertFalse(p["udp"])
  self.assertIn(p["name"],d["proxy-groups"][0]["proxies"])
  self.assertEqual(d["proxy-groups"][0]["use"],["subscription"])
  self.assertEqual(d["tun"]["auto-route"],False)
 def test_absent_adapter_cannot_enable(self):
  self.selected.unlink()
  self.assertNotEqual(self.config("1").returncode,0)
  self.assertEqual(self.config("0").returncode,0)
 def test_invalid_mode_rejected(self):
  self.assertNotEqual(self.config("enabled").returncode,0)
 def test_menu_is_operator_optin_only(self):
  menu=(ROOT/"src/awg-menu").read_text()
  self.assertIn("mihomo_xray_vless_menu(){",menu)
  self.assertIn("Xray VLESS (эксперимент)",menu)
  self.assertIn("awg-xray-vless select",menu)
  func=menu.split("mihomo_xray_vless_menu(){",1)[1].split("\n}\n",1)[0]
  self.assertNotIn("awg-transport select",func)
  self.assertNotIn("awg-mihomo-prepare",func)

 def test_installer_off_by_default(self):
  source=INSTALL.read_text()
  self.assertIn("install_project_python_helper src/awg-xray-vless.py",source)
  self.assertIn("install_project_helper src/awg-xray-install",source)
  self.assertIn("install_project_unit units/awg-xray-vless.service",source)
  self.assertIn("/usr/local/sbin/awg-xray-install ensure",source)
  self.assertNotIn("systemctl enable --now awg-xray-vless.service",source)
  self.assertNotIn("systemctl start awg-xray-vless.service",source)
  unit=(ROOT/"units/awg-xray-vless.service").read_text()
  self.assertIn("ExecStartPre=/usr/local/sbin/awg-xray-vless render",unit)
  self.assertIn("ProtectSystem=strict",unit)
  self.assertIn("ConditionPathExists=/var/lib/awg-pbr/xray-vless/selected.json",unit)
  self.assertIn("ReadWritePaths=/run/awg-pbr",unit)
if __name__=="__main__":unittest.main()
