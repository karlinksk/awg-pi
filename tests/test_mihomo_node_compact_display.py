#!/usr/bin/env python3
"""Rootless compact SSH row contract: fields, narrow UI, no false TUN PASS."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
MENU=(ROOT/"src/awg-menu").read_text()

def function(name):
    first=MENU.index(name+"(){")
    last=MENU.index("\n}\n",first)+2
    return MENU[first:last]+"\n"

FUNCTIONS=(function("mihomo_display_node_name")+
           function("mihomo_clip_node_label")+
           function("select_tsv_node_dialog"))

DATA=(
    "1\tNetherlands 1\tVLESS/xHTTP\t151.247.25.173:443\t-\tXRAY_HTTPS\t??\t-\n"
    "2\tGermany 2 Hysteria2\tHY2\tde3.example:443\t-\tMIHOMO_OK\tDE\t549ms\n"
    "3\tFinland HY2\tHY2\tfi.example:443\t-\tMIHOMO_FAIL\tFI\t-\n"
)

class CompactNodeUI(unittest.TestCase):
    def render(self,listing=DATA):
        with tempfile.TemporaryDirectory(prefix="awg-node-ui-") as td:
            capture=Path(td)/"capture"
            source=Path(td)/"list.tsv"
            source.write_text(listing)
            shell=FUNCTIONS+"""
dialog() {
  printf '%s\\0' "$@" > "$AWG_UI_CAPTURE"
  return 1
}
MIHOMO_UNIFIED=false
select_tsv_node_dialog "Точка выхода" "Выберите ноду." "$(cat "$AWG_UI_LIST")" no manual
"""
            r=subprocess.run(["bash","-c",shell],capture_output=True,text=True,
                  env={**os.environ,"AWG_UI_CAPTURE":str(capture),
                       "AWG_UI_LIST":str(source)},timeout=6)
            self.assertEqual(r.returncode,1,r.stderr)
            args=[x.decode() for x in capture.read_bytes().split(b"\0") if x]
            at=args.index("--menu")
            items=args[at+5:]
            self.assertEqual(len(items)%3,0)
            return args,[(items[i],items[i+1],items[i+2]) for i in range(0,len(items),3)]

    def test_catalog_rows_one_field_one_meaning(self):
        args,items=self.render()
        self.assertIn("Сервер = адрес подключения",args[args.index("--menu")+1])
        names={i:label for i,label,helptext in items}
        self.assertIn("Netherlands 1 | Xray | VLESS/xHTTP | 151.247.25.173:443 | — | OK",names["1"])
        self.assertIn("Germany 2 Hysteria2 | Mihomo | HY2 | de3.example:443 | 549мс | OK",names["2"])
        self.assertIn("Finland HY2 | Mihomo | HY2 | fi.example:443 | — | FAIL",names["3"])
        for index,label,helptext in items:
            if index.startswith("__"):continue
            self.assertEqual(label.count(" | "),5)
            self.assertNotIn("(НЕ IP выхода)",label)
            self.assertNotIn("(не TUN)",label)
            self.assertIn("Сервер подключения:",helptext)
            self.assertIn("не гарантия TUN/LAN",helptext)

    def test_name_shorten_preserves_full_lookup_in_help(self):
        full="NL "+("Amsterdam-"*9)
        listing=DATA.replace("Netherlands 1",full)
        args,items=self.render(listing)
        row=[x for x in items if x[0]=="1"][0]
        self.assertIn("… | Xray |",row[1])
        self.assertIn(full,row[2])
        self.assertTrue(any("Показано: 3 из 3" in arg for arg in args))

    def test_status_is_never_implicitly_tun_ready(self):
        _,items=self.render()
        self.assertNotIn("TUN OK"," ".join(i[1] for i in items))
        self.assertNotIn("LAN OK"," ".join(i[1] for i in items))

if __name__=="__main__":
    unittest.main()
