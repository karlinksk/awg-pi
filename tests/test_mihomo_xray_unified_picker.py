#!/usr/bin/env python3
"""Read-only, engine-specific output for the user-facing unified node picker."""
import importlib.util
import sys
import subprocess
from pathlib import Path
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
PICKER=ROOT/"src/awg-mihomo-node-picker.py"
VIEW=ROOT/"src/awg-mihomo-results-view.py"
spec=importlib.util.spec_from_file_location("node_picker",PICKER)
picker=importlib.util.module_from_spec(spec);sys.modules[spec.name]=picker
spec.loader.exec_module(picker)
vs=importlib.util.spec_from_file_location("source_view",VIEW)
view=importlib.util.module_from_spec(vs);sys.modules[vs.name]=view
vs.loader.exec_module(view)

mihomo={"index":1,"name":"Germany Hysteria2","type":"hysteria2",
        "server":"hys.example","port":2097,"healthy":True,
        "delay_ms":440,"country_code":"DE"}
xray={"index":2,"name":"Finland VLESS","type":"vless",
      "server":"xray.example","port":443,"healthy":False,"error":"http-504"}
profiles=[{k:v for k,v in row.items() if k in ("name","type","server","port")}
          for row in (mihomo,xray)]
inventory=[
    {"index":1,"name":"Germany Hysteria2","engine":"MIHOMO","basic_network":"UNTESTED"},
    {"index":2,"name":"Finland VLESS","engine":"XRAY","basic_network":"NETWORK_OK"}
]

class UnifiedPicker(unittest.TestCase):
    def rows(self,pool=None,source=None,proofs=None,protocol="all",region="all"):
        with mock.patch.object(picker,"load_view",return_value=view):
            return picker.entries(pool or [mihomo,xray],
                source if source is not None else profiles,
                proofs if proofs is not None else inventory,protocol,region)

    def test_thirteen_subscription_profiles_are_visible_not_all_ready(self):
        # A read-only catalog is a provider inventory, not a READY/FAILOVER list.
        sources=[];snap=[];scan=[]
        for i in range(1,14):
            xray=i<=6
            source={"index":i,"name":f"Node-{i}",
                    "type":"vless" if xray else "hysteria2",
                    "server":f"host{i}.example","port":443}
            sources.append({k:v for k,v in source.items() if k!="index"})
            scan.append({**source,"healthy":bool(i<=6 or i<=10),
                         "country_code":"DE" if i>6 else "??"})
            snap.append({"index":i,"name":source["name"],
                         "engine":"XRAY" if xray else "MIHOMO",
                         "basic_network":"NETWORK_OK" if xray else
                             "NETWORK_OK" if i<=10 else "NETWORK_FAIL"})
        with mock.patch.object(picker,"load_view",return_value=view),\
             mock.patch.object(view,"find_xray_evidence",
                 side_effect=lambda row,source,inventory:
                     "NETWORK_OK" if row["type"]=="vless" else None):
            rows=picker.entries(scan,sources,snap)
        self.assertEqual(len(rows),13)
        self.assertEqual([int(r.split("\t")[0]) for r in rows],list(range(1,14)))
        self.assertEqual(sum("\tXRAY_HTTPS\t" in r for r in rows),6)
        self.assertEqual(sum("\tMIHOMO_OK\t" in r for r in rows),4)
        self.assertEqual(sum("\tMIHOMO_FAIL\t" in r for r in rows),3)
        bash_parsed=self.parse_with_real_bash(rows)
        self.assertEqual(len(bash_parsed),13)
        self.assertEqual(sum(v[2]=="XRAY_HTTPS" for v in bash_parsed),6)
        self.assertEqual(sum(v[2]=="MIHOMO_OK" for v in bash_parsed),4)
        self.assertEqual(sum(v[2]=="MIHOMO_FAIL" for v in bash_parsed),3)
        with mock.patch.object(picker,"load_view",return_value=view):
            self.assertEqual(len(picker.entries([],[],[])),0)

    def test_mihomo_and_xray_visible_in_one_list(self):
        data=self.rows()
        self.assertEqual(len(data),2)
        self.assertIn("MIHOMO_OK",data[0])
        self.assertIn("XRAY_HTTPS",data[1])
        self.assertIn("Finland VLESS",data[1])

    def test_xray_profiles_visible_before_network_probe(self):
        # Visibility does not mean a live TUN activation is authorized.
        for status in ("UNTESTED","NETWORK_FAIL","UNKNOWN_HTTP","UNKNOWN_ERROR"):
            with self.subTest(status=status):
                inv=[inventory[0],{**inventory[1],"basic_network":status}]
                data=self.rows(proofs=inv)
                self.assertEqual(len(data),2)
                self.assertIn("Finland VLESS",data[1])
                self.assertIn("XRAY_"+status,data[1])
                self.assertNotIn("XRAY_HTTPS",data[1])

    def test_xray_present_even_when_missing_from_mihomo_scan(self):
        data=self.rows(pool=[mihomo])
        self.assertEqual(len(data),2)
        self.assertIn("Finland VLESS",data[1])
        self.assertIn("XRAY_HTTPS",data[1])

    def test_stale_pool_does_not_suppress_current_xray(self):
        stale={**xray,"server":"old.example","healthy":False}
        data=self.rows(pool=[mihomo,stale])
        self.assertEqual(len(data),2)
        self.assertIn("Finland VLESS",data[1])
        self.assertIn("XRAY_HTTPS",data[1])

    def test_duplicate_names_and_provider_churn_never_selected(self):
        duplicate=[profiles[0],profiles[1],{**profiles[1],"port":8443}]
        self.assertEqual(len(self.rows(source=duplicate,proofs=inventory+[
            {**inventory[1],"index":3}])),3)
        self.assertEqual(sum("DUPLICATE" in x for x in self.rows(
            source=duplicate,proofs=inventory+[{**inventory[1],"index":3}])),2)
        rotated=[profiles[0],{**profiles[1],"server":"new.example"}]
        # A rotated current profile stays visible but loses old HTTPS evidence.\n        data=self.rows(source=rotated,proofs=[inventory[0],{**inventory[1],"basic_network":"UNTESTED"}])\n        self.assertEqual(len(data),2)\n        self.assertIn("XRAY_UNTESTED",data[1])

    def test_protocol_filter_preserved(self):
        self.assertEqual(len(self.rows(protocol="vless")),1)
        self.assertIn("XRAY_HTTPS",self.rows(protocol="vless")[0])
        self.assertEqual(len(self.rows(protocol="hysteria2")),1)

    @staticmethod
    def parse_with_real_bash(records):
        # Bash IFS treats TAB as whitespace: an empty field disappears.
        # Regression ensures eight TSV columns survive a real shell read.
        script=(r"""while IFS=$'\t' read -r idx name kind endpoint dup health country delay; do
  printf '%s|%s|%s|%s|%s\n' "$idx" "$dup" "$health" "$country" "$delay"
done""")
        p=subprocess.run(["bash","-c",script],
                         input="\n".join(records)+"\n",
                         capture_output=True,text=True,timeout=4,check=True)
        return [line.split("|") for line in p.stdout.splitlines()]

    def test_tsv_has_nonempty_duplicate_column_for_real_bash_reader(self):
        parsed=self.parse_with_real_bash(self.rows())
        self.assertEqual(parsed,[
            ["1","-","MIHOMO_OK","DE","440ms"],
            ["2","-","XRAY_HTTPS","??","-"]])
        staged=self.parse_with_real_bash(self.rows(source=[],proofs=[]))
        self.assertEqual([x[2] for x in staged],
                         ["MIHOMO_OK","MIHOMO_FAIL"])
        dup=[profiles[0],profiles[1],{**profiles[1],"port":8443}]
        inv=inventory+[{**inventory[1],"index":3}]
        parsed_dups=self.parse_with_real_bash(self.rows(source=dup,proofs=inv))
        self.assertEqual(len(parsed_dups),3)
        self.assertEqual([x[1] for x in parsed_dups],
                         ["-","DUPLICATE","DUPLICATE"])
        self.assertEqual([x[2] for x in parsed_dups],
                         ["MIHOMO_OK","DUPLICATE","DUPLICATE"])

    def test_europe_filter_does_not_infer_xray_country(self):
        # The provider's 'Finland' name alone is not verified GeoIP evidence.
        self.assertEqual(len(self.rows(region="europe")),1)
        self.assertIn("MIHOMO_OK",self.rows(region="europe")[0])

    def test_mihomo_healthy_without_xray_inventory_fallback(self):
        rows=self.rows(source=[],proofs=[])
        self.assertEqual(len(rows),2)
        self.assertIn("MIHOMO_OK",rows[0])
        self.assertIn("MIHOMO_FAIL",rows[1])

    def test_unknown_engine_cannot_become_selectable(self):
        inv=[{**inventory[0],"engine":"UNSUPPORTED"},inventory[1]]
        self.assertEqual(len(self.rows(proofs=inv)),2)
        self.assertIn("UNSUPPORTED",self.rows(proofs=inv)[0])

    def test_fixed_editor_uses_same_inventory_but_gates_unsafe_choice(self):
        menu=(ROOT/"src/awg-menu").read_text()
        fixed=menu.split("mihomo_node_chain_editor(){",1)[1].split("\n}\n",1)[0]
        dialog=menu.split("select_tsv_node_dialog(){",1)[1].split("\n}\n",1)[0]
        self.assertIn('"$MIHOMO_NODE_PICKER" "$node_json" --target live --protocol all --region all',fixed)
        self.assertIn('"$listing" no fixed',fixed)
        self.assertIn('if [[ "$scope" == fixed && "$node_health" != MIHOMO_OK ]]',dialog)
        self.assertIn('if [[ "$node_health" == UNSUPPORTED || "$node_health" == DUPLICATE ]]',dialog)
        self.assertIn('MIHOMO_FAIL',dialog)
        self.assertIn('XRAY_HTTPS',dialog)
        self.assertIn('Показано: $count из $shown_total',dialog)
    def test_malicious_name_newline_cannot_corrupt_picker(self):
        bad={**xray,"name":"Finland\tVLESS"}
        source=[profiles[0],{**profiles[1],"name":"Finland\tVLESS"}]
        inv=[inventory[0],{**inventory[1],"name":"Finland\tVLESS"}]
        self.assertEqual(len(self.rows(pool=[mihomo,bad],source=source,proofs=inv)),1)

    def test_menu_routes_xray_away_from_mihomo_select_auto(self):
        menu=(ROOT/"src/awg-menu").read_text()
        self.assertIn('MIHOMO_NODE_PICKER=/usr/local/sbin/awg-mihomo-node-picker',menu)
        self.assertIn('if [[ "$engine" == XRAY ]]; then',menu)
        self.assertIn('"$XRAY_MANUAL_SWITCH" apply "$index"',menu)
        self.assertIn('"$XRAY_MANUAL_SWITCH" preview "$index"',menu)
        self.assertIn('[[ "$engine" == MIHOMO ]] ||',menu)
        self.assertIn('confirm "Переключение на Xray"',menu)
        self.assertIn('MIHOMO_POOL_PICKED_NODE',menu)
        self.assertIn('independent Xray OpenAI network gate remains valid',menu)
        self.assertIn('Reality VLESS may be unusable',menu)

    def test_stale_xray_proof_auto_refresh_is_bounded(self):
        code=(ROOT/"src/awg-menu").read_text()
        self.assertIn('XRAY_MANUAL_ERROR=XRAY_FRESH_NETWORK_PROOF_REQUIRED',code)
        self.assertIn('"$MIHOMO_UNIFIED" probe "$index"',code)
        self.assertIn('title="Обновление доказательства Xray HTTPS"',code)
        self.assertIn('Подписка изменилась; активная нода не переключалась.',code)

    def test_direct_live_picker_and_optional_advanced_menu(self):
        code=(ROOT/"src/awg-menu").read_text()
        self.assertIn('mihomo_pool_pick live "Точка выхода Mihomo / Xray"',code)
        self.assertIn('доступны отдельным пунктом списка." direct',code)
        self.assertIn('if [[ "$direct" == yes && "$target" == live ]]',code)
        self.assertIn('items+=("__advanced__"',code)
        self.assertIn('__advanced__) return 42',code)
        self.assertIn('if (( pick_rc == 42 ))',code)

    def test_menu_distinguishes_server_address_from_egress(self):
        menu=(ROOT/"src/awg-menu").read_text()
        self.assertIn('сервер: $endpoint (НЕ IP выхода)',menu)
        self.assertIn('"$MIHOMO_UNIFIED" probe "$index"',menu)
        self.assertNotIn('confirm "Проверить Xray VLESS"',menu)
        self.assertIn("mihomo_live_egress_ip()",menu)
        self.assertIn("--interface mihomo0",menu)
        self.assertIn("Публичный IP выхода через mihomo0",menu)

    def test_not_installed_into_auto_selection(self):
        source=PICKER.read_text()
        for word in ("systemctl", "node select-auto", "awg-transit-routing",
                     "MIHOMO_READY_AUTO=1","READY_PASS"):
            self.assertNotIn(word,source)

if __name__=="__main__":unittest.main()
