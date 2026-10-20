#!/usr/bin/env python3
"""Read-only regression for preinstall and already-installed test-Pi picker."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/"scripts/awg-xray-unified-picker-stage-testpi.py"
spec=importlib.util.spec_from_file_location("picker_stage",P)
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)

class PickerStaging(unittest.TestCase):
    def test_installed_menu_read_only_patch_preflight(self):
        source=mod.SOURCE.read_text()
        if mod.PICKER.exists():
            self.assertEqual(
                hashlib.sha256(mod.PICKER.read_bytes()).digest(),
                hashlib.sha256(mod.SOURCE_PICKER.read_bytes()).digest())
            installed=mod.INSTALLED.read_text()
            for name in (*mod.SELECTED,mod.NEW_MENU):
                # This test validates the historical staging procedure. Later
                # installer UI revisions must not match the old live Pi bytewise.
                self.assertTrue(mod.function(installed,name))
                self.assertTrue(mod.function(source,name))
            self.assertIn('MIHOMO_NODE_PICKER=',installed)
            return
        old,new=mod.check()
        self.assertNotEqual(old,new)
        original=old.decode()
        current=new.decode()
        self.assertIn('MIHOMO_NODE_PICKER=',current)
        self.assertEqual(current.count("mihomo_xray_vless_menu(){"),1)
        self.assertIn('if [[ "$engine" == XRAY ]]; then',current)
        self.assertIn('awg-xray-vless select "$index"',current)
        self.assertIn('node select-auto "$node_name"',current)
        self.assertIn('systemctl is-active --quiet awg-xray-vless.service',current)
        for name in ("vpn_menu","selection_policy_menu","dns_menu",
                     "operating_mode_menu","system_menu"):
            self.assertEqual(mod.function(original,name),mod.function(current,name))

    def test_refuse_unreviewed_old_or_replay(self):
        # A source that is already installed must not be patched a second time.
        with self.assertRaisesRegex(RuntimeError,"OLD_FUNCTION_ALREADY_NEW"):
            mod.patch(mod.SOURCE.read_text(),mod.SOURCE.read_text())
        with self.assertRaises((RuntimeError,ValueError)):
            mod.patch("bad",mod.SOURCE.read_text())

    def test_installer_and_backup_covered(self):
        installer=(ROOT/"install.sh").read_text()
        update=(ROOT/"src/awg-update").read_text()
        self.assertIn('install_project_python_helper src/awg-mihomo-node-picker.py /usr/local/sbin/awg-mihomo-node-picker',installer)
        self.assertIn('usr/local/sbin/awg-mihomo-node-picker',update)
        self.assertIn('/usr/local/sbin/awg-mihomo-node-picker',update)

    def test_readonly_stage_test(self):
        r=subprocess.run([sys.executable,"-B",str(P),"--check"],
                         capture_output=True,text=True,timeout=15)
        if mod.PICKER.exists():
            # Safe one-shot installer refuses overwrite; this is expected.
            self.assertNotEqual(r.returncode,0)
            self.assertIn("XRAY_PICKER_STAGE_ERROR=PRECHECK_OR_INSTALL_FAILED",r.stdout)
        else:
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertIn("XRAY_PICKER_STAGE_PREFLIGHT=PASS",r.stdout)
            self.assertIn("XRAY_PICKER_STAGE_INSTALLED=NO",r.stdout)

if __name__=="__main__":
    unittest.main()
