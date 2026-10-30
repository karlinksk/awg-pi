#!/usr/bin/env python3
"""TRANSIT mode status: plain Russian, exact state mapping, no VPN writes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

MENU=(Path(__file__).resolve().parents[1]/"src/awg-menu").read_text()
def fn(name):
    a=MENU.index(name+"(){")
    b=MENU.index("\n}\n",a)+2
    return MENU[a:b]+"\n"

GOOD="""Operating mode: MikroTik Transit / Backup VPN
Mode ID: transit
Transit guard: SAFE
Transit policy rule: ACTIVE
Transit VPN table: READY
"""

class TransitStatusUI(unittest.TestCase):
    def render(self,raw):
        proc=subprocess.run(
            ["bash","-Eeuo","pipefail","-c",fn("transit_mode_status_text")+
             '\ntransit_mode_status_text "$RAW"\n'],
            env={**os.environ,"RAW":raw},capture_output=True,text=True,timeout=5)
        self.assertEqual(proc.returncode,0,proc.stderr)
        return proc.stdout

    def test_safe_active_ready_exact_approved_screen(self):
        self.assertEqual(self.render(GOOD).splitlines(),[
            "Режим работы: Транзитный VPN для MikroTik","",
            "Защита от прямого выхода при сбое VPN: настроена",
            "Правило маршрутизации: действует",
            "VPN-маршруты: готовы"])

    def test_lockdown_inactive_notready_have_no_false_pass(self):
        raw=GOOD.replace("SAFE","LOCKDOWN").replace("ACTIVE","INACTIVE").replace("READY","NOT_READY")
        output=self.render(raw)
        self.assertIn("Защита от прямого выхода при сбое VPN: блокировка действует, VPN-путь не готов",output)
        self.assertIn("Правило маршрутизации: не действует",output)
        self.assertIn("VPN-маршруты: не готовы",output)
        self.assertNotIn("VPN-маршруты: готовы",output)

    def test_unsafe_does_not_claim_configured(self):
        output=self.render(GOOD.replace("SAFE","UNSAFE"))
        self.assertIn("Защита от прямого выхода при сбое VPN: не обеспечена — требуется проверка",output)
        self.assertNotIn("при сбое VPN: настроена",output)

    def test_missing_duplicate_unknown_states_are_unverified(self):
        for value in (GOOD.replace("Transit guard: SAFE\n",""),
                      GOOD.replace("Transit guard: SAFE","Transit guard: unrecognized"),
                      GOOD+"Transit guard: SAFE\n"):
            with self.subTest(value=value):
                self.assertIn("Защита от прямого выхода при сбое VPN: не удалось проверить",
                              self.render(value))
        for key,value in (("Transit policy rule: ACTIVE\n","Правило маршрутизации: не удалось проверить"),
                          ("Transit VPN table: READY\n","VPN-маршруты: не удалось проверить")):
            self.assertIn(value,self.render(GOOD.replace(key,"")))

    def test_other_or_unknown_mode_never_show_ready(self):
        for raw in (GOOD.replace("Mode ID: transit","Mode ID: selective"),
                    GOOD.replace("Mode ID: transit\n",""),
                    GOOD+"Mode ID: transit\n",""):
            with self.subTest(raw=raw):
                output=self.render(raw)
                self.assertIn("Режим работы: не удалось подтвердить транзитный режим",output)
                self.assertIn("VPN-маршруты: не удалось проверить",output)
                self.assertNotIn("VPN-маршруты: готовы",output)

    def test_extra_or_malicious_fields_not_rendered(self):
        output=self.render(GOOD+"SECRET_TOKEN=never-print\n")
        self.assertNotIn("SECRET_TOKEN",output)
        self.assertNotIn("never-print",output)
        self.assertNotIn("Mode ID:",output)
        self.assertNotIn("Результат: ВЫПОЛНЕНО",output)
        self.assertNotIn("Операция:",output)

    def test_screen_read_failure_and_success_only_display_human_text(self):
        shell=fn("transit_mode_status_text")+fn("transit_mode_status_screen")
        with tempfile.TemporaryDirectory(prefix="transit-status-") as tmp:
            root=Path(tmp); helper=root/"route"
            helper.write_text("#!/bin/sh\n[ \"$FAIL\" != 1 ] || { echo 'secret=wrong'; exit 3; }\nprintf '%s\\n' \"$RAW\"\n")
            helper.chmod(0o700)
            for fail in ("0","1"):
                with self.subTest(fail=fail):
                    cmd='BACKTITLE=test\nTMP="$OUTPUT"\nAWG_ROUTE="$HELPER"\n' + \
                        'dialog(){ cp "$TMP" "$DISPLAY"; }\n'+shell+'\ntransit_mode_status_screen\n'
                    r=subprocess.run(["bash","-Eeuo","pipefail","-c",cmd],
                        env={**os.environ,"FAIL":fail,"RAW":GOOD,"HELPER":str(helper),
                             "OUTPUT":str(root/"view"),"DISPLAY":str(root/"display")},
                        capture_output=True,text=True,timeout=5)
                    self.assertEqual(r.returncode,0,r.stderr)
                    text=(root/"display").read_text()
                    self.assertNotIn("secret=wrong",text)
                    self.assertNotIn("Результат:",text)
                    self.assertNotIn("Операция:",text)
                    if fail=="0": self.assertIn("VPN-маршруты: готовы",text)
                    else: self.assertIn("VPN-маршруты: не удалось проверить",text)

    def test_menu_dispatch_does_not_change_transport_or_cli(self):
        block=MENU.split("vpn_menu(){",1)[1].split("dns_menu(){",1)[0]
        self.assertIn("1) transit_mode_status_screen ;;",block)
        self.assertNotIn('capture_ru "$AWG_ROUTE" mode status',block)
        screen=fn("transit_mode_status_screen")
        self.assertIn('"$AWG_ROUTE" mode status',screen)
        for forbidden in ("systemctl restart"," mode transit","nft add","ip route add"):
            self.assertNotIn(forbidden,screen)
        self.assertIn("2)\n          restart_active_transport || true\n          ;;", block)
        self.assertIn('1 "Включить VPN-политику"',block)

if __name__=="__main__":
    unittest.main()
