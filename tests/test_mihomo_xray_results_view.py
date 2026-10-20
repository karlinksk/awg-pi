#!/usr/bin/env python3
"""Rootless regression tests for Mihomo/Xray UI evidence separation."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import json

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"src/awg-mihomo-results-view.py"
spec=importlib.util.spec_from_file_location("awg_engine_aware_results",SRC)
view=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=view
spec.loader.exec_module(view)

HYS={"name":"Germany Hysteria2","type":"hysteria2",
     "server":"example1.invalid","port":2097,"healthy":True,
     "delay_ms":440,"index":1,"country_code":""}
VLESS={"name":"Netherlands 1","type":"vless",
       "server":"example2.invalid","port":443,"healthy":False,
       "error":"http-503","delay_ms":None,"index":2}
PROFILES=[
    {"name":"Germany Hysteria2","type":"hysteria2",
     "server":"example1.invalid","port":2097},
    {"name":"Netherlands 1","type":"vless",
     "server":"example2.invalid","port":443}
]
INVENTORY=[
    {"index":1,"name":"Germany Hysteria2","engine":"MIHOMO",
     "basic_network":"NETWORK_OK"},
    {"index":2,"name":"Netherlands 1","engine":"XRAY",
     "basic_network":"NETWORK_OK"},
]

class ResultUI(unittest.TestCase):
    def test_old_hysteria_and_new_xray_are_separate(self):
        text=view.render([HYS,VLESS],PROFILES,INVENTORY)
        self.assertIn("Hysteria2",text)
        self.assertIn("Mihomo",text)
        self.assertIn("работает",text)
        self.assertIn("Xray",text)
        self.assertIn("HTTPS OK",text)
        self.assertIn("Причина: Mihomo: http-503",text)
        self.assertNotIn("READY OK",text)
        self.assertIn("НЕ READY / TUN / LAN",text)

    def test_does_not_relabel_failed_mihomo_as_healthy(self):
        text=view.render([HYS,VLESS],[],[])
        self.assertIn("недоступен",text)
        self.assertNotIn("HTTPS OK",text)
        self.assertIn("данных текущего профиля нет",text)

    def test_xray_unchecked_never_pass(self):
        inv=[INVENTORY[0],{**INVENTORY[1],"basic_network":"UNTESTED"}]
        text=view.render([HYS,VLESS],PROFILES,inv)
        self.assertIn("не проверен",text)
        self.assertNotIn("HTTPS OK",text)

    def test_xray_network_fail_never_pass(self):
        inv=[INVENTORY[0],{**INVENTORY[1],"basic_network":"NETWORK_FAIL"}]
        self.assertIn("сеть ошибка",view.render([VLESS],PROFILES,inv))
        self.assertNotIn("HTTPS OK",view.render([VLESS],PROFILES,inv))

    def test_http_unknown_does_not_mean_network_ok(self):
        inv=[INVENTORY[0],{**INVENTORY[1],"basic_network":"UNKNOWN_HTTP"}]
        self.assertIn("HTTP ?",view.render([VLESS],PROFILES,inv))
        self.assertNotIn("HTTPS OK",view.render([VLESS],PROFILES,inv))

    def test_provider_churn_identity_matches_exact_endpoint(self):
        renamed=[PROFILES[0],{**PROFILES[1],"server":"new-server.invalid"}]
        self.assertIsNone(view.find_xray_evidence(VLESS,renamed,INVENTORY))
        self.assertNotIn("HTTPS OK",view.render([VLESS],renamed,INVENTORY))
        self.assertIsNone(view.find_xray_evidence(VLESS,PROFILES[:-1],INVENTORY))

    def test_duplicate_profile_names_are_never_verifiable(self):
        dup=[PROFILES[0],PROFILES[1],{**PROFILES[1],"port":8443}]
        inventory=[INVENTORY[0],INVENTORY[1],{**INVENTORY[1],"index":3}]
        self.assertIsNone(view.find_xray_evidence(VLESS,dup,inventory))
        self.assertIsNone(view.find_xray_evidence({**VLESS,"duplicate_name":True},PROFILES,INVENTORY))

    def test_sorted_mihomo_rows_do_not_change_identity(self):
        text=view.render([VLESS,HYS],PROFILES,INVENTORY)
        self.assertIn("HTTPS OK",text)
        self.assertIn("работает",text)

    def test_candidate_is_not_bound_to_live_evidence(self):
        text=view.render([VLESS],PROFILES,INVENTORY,target="candidate")
        self.assertNotIn("HTTPS OK",text)
        self.assertIn("недоступен",text)

    def test_engine_name_mismatch_cannot_claim_xray(self):
        inv=[INVENTORY[0],{**INVENTORY[1],"engine":"MIHOMO"}]
        self.assertNotIn("HTTPS OK",view.render([VLESS],PROFILES,inv))

    def test_menu_calls_helper_and_explicit_xray_probe(self):
        script=(ROOT/"src/awg-menu").read_text()
        self.assertIn('MIHOMO_RESULTS_VIEW=/usr/local/sbin/awg-mihomo-results-view',script)
        self.assertIn('"$MIHOMO_RESULTS_VIEW" "$json_tmp" --target "$target"',script)
        self.assertIn('"$MIHOMO_UNIFIED" probe-vless-all',script)
        self.assertIn('if [[ "$target" == live',script)
        self.assertNotIn('python3 - "$json_tmp" >"$TMP" <<',script)

    def test_clean_install_and_backup_include_view_helper(self):
        install=(ROOT/"install.sh").read_text()
        backup=(ROOT/"src/awg-update").read_text()
        self.assertIn('install_project_python_helper src/awg-mihomo-results-view.py /usr/local/sbin/awg-mihomo-results-view',install)
        self.assertIn('usr/local/sbin/awg-mihomo-results-view',backup)
        self.assertIn('/usr/local/sbin/awg-mihomo-results-view',backup)

    def test_code_never_mutates_state(self):
        script=SRC.read_text()
        for term in ('systemctl restart','node select-auto','awg-xray-live-backend',
                     'awb-transit-routing disable','ip route replace',
                     'probe-vless-all', 'provider.env', 'NETWORK_OK" if'):
            self.assertNotIn(term,script)
        self.assertIn('find_xray_evidence',script)

    def test_bash_python_syntax(self):
        proc=subprocess.run(['bash','-n',str(ROOT/'src/awg-menu')],
                            capture_output=True,text=True,timeout=9)
        self.assertEqual(proc.returncode,0,proc.stderr)
        proc=subprocess.run([sys.executable,'-m','py_compile',str(SRC)],
                            capture_output=True,text=True,timeout=9)
        self.assertEqual(proc.returncode,0,proc.stderr)

if __name__=="__main__":unittest.main()
