#!/usr/bin/env python3
"""Rootless Telegram header UI checks; never starts network or system services."""
import os
from pathlib import Path
import subprocess
import unittest

SRC=(Path(__file__).resolve().parents[1]/"src/awg-menu").read_text()
def body(name):
    a=SRC.index(name+"(){")
    b=SRC.index("\n}\n",a)+2
    return SRC[a:b]+"\n"

EVENTS=("VPN_LOST","VPN_RESTORED","BOOT","DAILY_REPORT","NODE_SWITCH","TRANSPORT_SWITCH")
LABELS=("отказ VPN","восстановление VPN","запуск Raspberry Pi",
        "ежедневная сводка","смена ноды","смена транспорта")
def status(bot="yes",chosen=EVENTS):
    return "\n".join(["NOTIFY_CONFIGURED="+bot,"NOTIFY_PENDING=8",
                      "NOTIFY_LAST_ROUTE=awg0","SECRET=never-print"]+
                     ["NOTIFY_PREF_"+k+"="+("on" if k in chosen else "off") for k in EVENTS])

class TelegramMenuHeader(unittest.TestCase):
    def render(self,raw,delivery="включена"):
        script=body("notify_menu_header")+'\nnotify_menu_header "$RAW" "$DELIVERY"\n'
        return subprocess.run(["bash","-Eeuo","pipefail","-c",script],
                              env={**os.environ,"RAW":raw,"DELIVERY":delivery},
                              capture_output=True,text=True,timeout=5)

    def test_full_selection_only_human_status(self):
        r=self.render(status())
        self.assertEqual(r.returncode,0,r.stderr)
        lines=r.stdout.splitlines()
        self.assertEqual(lines[0],"Бот: настроен")
        self.assertEqual(lines[1],"Доставка: включена")
        self.assertTrue(lines[2].startswith("Уведомления: "))
        for name in LABELS: self.assertIn(name,lines[2])
        for hidden in ("NOTIFY_","Watch:","Сводка:","awg0","never-print","галоч"):
            self.assertNotIn(hidden,r.stdout)

    def test_subset_with_disabled_delivery_and_unconfigured_bot(self):
        r=self.render(status("no",("BOOT","TRANSPORT_SWITCH")),"выключена")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(r.stdout.splitlines(),[
          "Бот: не настроен","Доставка: выключена",
          "Уведомления: запуск Raspberry Pi, смена транспорта"])

    def test_nothing_selected(self):
        r=self.render(status(chosen=()))
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("Уведомления: не выбраны",r.stdout)

    def test_missing_data_does_not_claim_off(self):
        for raw in ("","NOTIFY_CONFIGURED=yes\nNOTIFY_PREF_BOOT=on"):
            with self.subTest(raw=raw):
                r=self.render(raw)
                self.assertEqual(r.returncode,0,r.stderr)
                self.assertIn("Уведомления: не удалось проверить",r.stdout)
                if not raw: self.assertIn("Бот: не удалось проверить",r.stdout)

    def test_telegram_text_without_checkbox_commentary(self):
        section=SRC.split("notify_types_menu(){",1)[1].split(
          "awg_menu_restart_for_appearance(){",1)[0]
        self.assertNotIn("галоч",section.lower())
        self.assertIn('4 "Типы уведомлений"',section)
        self.assertIn("--separate-output --checklist",section)
        self.assertIn("notify_sync_daily_schedule",section)
        self.assertNotIn("NOTIFY_LAST_ROUTE",section)
        self.assertNotIn("NOTIFY_PENDING",section)

if __name__=="__main__":
    unittest.main()
