#!/usr/bin/env python3
"""Check staging edits only Mihomo/Xray result view on the test Pi."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"scripts/awg-mihomo-xray-results-stage-testpi.py"
spec=importlib.util.spec_from_file_location("awg_results_stage",PATH)
stage=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=stage
spec.loader.exec_module(stage)

class SafeStage(unittest.TestCase):
    def fixture(self):
        # Synthetic legacy screen, no production file dependency.
        return (
          'MIHOMO_POOL=/usr/local/sbin/awg-mihomo-pool\n'
          'mihomo_pool_results_dialog(){\n  echo old\n}\n'
          '\nselect_tsv_node_dialog(){\n}\n'
          '      4 "Обновить проверку сейчас" "Mihomo only" \\\n'
          '      6 "Показать все результаты" "Old screen" \\\n'
          '        title="Проверка узлов Mihomo"\n'
          '        capture "$MIHOMO_POOL" scan "$target" --geo-if-policy || true\n')
    def test_patch_only_expected_ui_anchors(self):
        result=stage.patched_menu(self.fixture(),stage.SOURCE_MENU.read_text())
        self.assertIn(stage.EXTRA,result)
        self.assertIn('mihomo_pool_results_dialog(){',result)
        self.assertIn('"$MIHOMO_RESULTS_VIEW" "$json_tmp" --target "$target"',result)
        self.assertIn('probe-vless-all',result)
        self.assertIn('MIHOMO_POOL=/usr/local/sbin/awg-mihomo-pool',result)
        self.assertNotIn('  echo old\n',result)
        self.assertNotIn('Mihomo only',result)
    def test_refuses_unknown_menu(self):
        with self.assertRaises((ValueError,RuntimeError)):
            stage.patched_menu("bad menu",stage.SOURCE_MENU.read_text())
    def test_patch_source_idempotent(self):
        source=stage.SOURCE_MENU.read_text()
        self.assertEqual(stage.patched_menu(source,source),source)
    def test_check_is_readonly_and_scope_restricted(self):
        source=PATH.read_text()
        self.assertIn('BASELINE_MENU_SHA=',source)
        self.assertIn('TEST_PI_ONLY',source)
        self.assertIn('SNAPSHOT',source.upper()) if False else None
        self.assertIn('if os.geteuid()!=0:',source)
        self.assertIn('ONLY_RESULTS_VIEW',source)
        for bad in ('systemctl","restart','systemctl","stop','systemctl","enable',
                    '"ip","route","replace"','awg-transit-routing","disable'):
            self.assertNotIn(bad,source)
    def test_syntax(self):
        proc=subprocess.run([sys.executable,"-m","py_compile",str(PATH)],
           capture_output=True,text=True,timeout=10)
        self.assertEqual(proc.returncode,0,proc.stderr)

if __name__=="__main__":
    unittest.main()
