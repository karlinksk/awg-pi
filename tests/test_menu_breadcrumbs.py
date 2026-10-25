#!/usr/bin/env python3
"""Breadcrumbs stay within native dialog titles: rootless PTY regression."""
from pathlib import Path
import fcntl
import os
import pty
import struct
import subprocess
import tempfile
import termios
import unittest

ROOT=Path(__file__).resolve().parents[1]
MENU=(ROOT/"src/awg-menu").read_text()

def func(name):
    i=MENU.index(name+"(){")
    j=MENU.index("\n}\n",i)+2
    return MENU[i:j]+"\n"

CORE=func("awg_dialog_breadcrumb_title")
WRAPPER=func("dialog")

def execute_breadcrumb(title,width,callers):
    args=["bash","-c",CORE+'\nawg_dialog_breadcrumb_title "$1" "$2" "${@:3}"',
          "test",title,str(width),*callers]
    return subprocess.run(args,capture_output=True,text=True,timeout=5,
                          env=dict(os.environ,LC_ALL="C.UTF-8"),check=True).stdout

class Breadcrumbs(unittest.TestCase):
    def test_hierarchy_and_main_exception(self):
        self.assertEqual(
            execute_breadcrumb("AUTO — пул узлов",76,[
                "mihomo_node_auto_menu","mihomo_node_policy_menu",
                "mihomo_menu","vpn_menu"]),
            "Главная › VPN › Mihomo › Резервирование узлов Mihomo › AUTO")
        self.assertEqual(
            execute_breadcrumb("Резервирование узлов Mihomo",76,[
                "mihomo_node_policy_menu","mihomo_menu","vpn_menu"]),
            "Главная › VPN › Mihomo › Резервирование узлов Mihomo")
        self.assertEqual(
            execute_breadcrumb("Главное меню — [TRANSIT]",76,["vpn_menu"]),
            "Главное меню — [TRANSIT]")
        self.assertEqual(
            execute_breadcrumb("Проверка соединения",76,["unknown_func"]),
            "Главная › Проверка соединения")

    def test_unified_node_picker_has_no_phantom_catalog_or_duplicate_title(self):
        full = execute_breadcrumb("Точка выхода Mihomo / Xray", 110, [
            "select_tsv_node_dialog", "mihomo_pool_pick", "mihomo_node_menu",
            "mihomo_menu", "vpn_menu"])
        self.assertEqual(full, "Главная › VPN › Mihomo › Точка выхода Mihomo / Xray")
        self.assertNotIn("Каталог", full)
        self.assertEqual(full.count("Точка выхода"), 1)

    def test_mihomo_additional_settings_do_not_repeat_title(self):
        title = execute_breadcrumb("Дополнительные настройки", 110, [
            "mihomo_advanced_menu", "mihomo_menu", "vpn_menu"])
        self.assertEqual(
            title, "Главная › VPN › Mihomo › Дополнительные настройки")
        self.assertNotIn("Восстановление", title)

    def test_compact_titles_preserve_current_section(self):
        s=execute_breadcrumb("Длинная проверка безопасного подключения",43,[
            "mihomo_xray_auto_menu","mihomo_node_auto_menu",
            "mihomo_node_policy_menu","mihomo_menu","vpn_menu"])
        self.assertTrue(s.startswith("Главная › … › "),s)
        self.assertLessEqual(len(s),43)
        self.assertTrue(s.endswith("…") or "проверка" in s,s)

    def run_mock(self,title,kind,rows=33,cols=100):
        with tempfile.TemporaryDirectory(prefix="awg-crumb-") as td:
            mock=Path(td)/"dialog"
            output=Path(td)/"capture"
            mock.write_text('#!/bin/sh\nprintf "%s\\0" "$@" > "$AWG_CRUMB_CAPTURE"\n')
            mock.chmod(0o700)
            master,slave=pty.openpty()
            try:
                fcntl.ioctl(slave,termios.TIOCSWINSZ,
                            struct.pack("HHHH",rows,cols,0,0))
                def tty():
                    os.setsid()
                    fcntl.ioctl(slave,termios.TIOCSCTTY,0)
                if kind=="menu":
                    widget='--item-help --menu "Выбор" 28 116 15 1 "Mihomo" "Подсказка"'
                elif kind=="yesno":
                    widget='--yesno "Подтверждение" 10 75'
                elif kind=="inputbox":
                    widget='--inputbox "Введите значение" 11 80 "тест"'
                else:
                    widget='--textbox /tmp/test-contents 25 95'
                shell=(CORE+"\n"+WRAPPER+"""
vpn_menu(){ mihomo_menu; }
mihomo_menu(){ mihomo_node_policy_menu; }
mihomo_node_policy_menu(){
  dialog --backtitle test --title "$TITLE" """+widget+"""
}
vpn_menu
""")
                if title.startswith("Главное меню"):
                    shell=(CORE+"\n"+WRAPPER+
                        'dialog --title "$TITLE" '+widget+'\n')
                proc=subprocess.run(["bash","-c",shell],env={
                    **os.environ,"PATH":str(Path(td))+":"+os.environ["PATH"],
                    "AWG_CRUMB_CAPTURE":str(output),"TITLE":title,
                    "LC_ALL":"C.UTF-8"},
                    stdin=slave,stdout=slave,stderr=slave,
                    preexec_fn=tty,timeout=7)
                self.assertEqual(proc.returncode,0)
                return [x.decode() for x in output.read_bytes().split(b"\x00") if x]
            finally:
                os.close(master)
                os.close(slave)

    def test_wrapper_menu_confirm_input_and_textbox(self):
        for widget in ["menu","yesno","inputbox","textbox"]:
            with self.subTest(widget=widget):
                args=self.run_mock("Проверка ноды",widget)
                self.assertIn("--title",args)
                title=args[args.index("--title")+1]
                self.assertEqual(title,
                  "Главная › VPN › Mihomo › Резервирование узлов Mihomo › Проверка ноды")
                self.assertEqual(args[args.index("--backtitle")+1],"test")
                self.assertIn("--"+widget,args)

    def test_stdout_form_with_piped_stdout_still_has_breadcrumbs(self):
        with tempfile.TemporaryDirectory(prefix="awg-form-") as td:
            mock=Path(td)/"dialog"
            output=Path(td)/"args"
            mock.write_text('#!/bin/sh\nprintf "%s\\0" "$@" > "$AWG_CRUMB_CAPTURE"\n')
            mock.chmod(0o700)
            master,slave=pty.openpty()
            try:
                fcntl.ioctl(slave,termios.TIOCSWINSZ,
                            struct.pack("HHHH",30,100,0,0))
                def tty():
                    os.setsid()
                    fcntl.ioctl(slave,termios.TIOCSCTTY,0)
                shell=(CORE+"\n"+WRAPPER+"""
vpn_menu(){ mihomo_menu; }
mihomo_menu(){ dialog --stdout --title "Вставить профиль" --editbox /tmp/no-input 18 82; }
vpn_menu
""")
                proc=subprocess.run(["bash","-c",shell],
                    env=dict(os.environ,PATH=str(Path(td))+":"+os.environ["PATH"],
                             AWG_CRUMB_CAPTURE=str(output),LC_ALL="C.UTF-8"),
                    stdin=slave,stdout=subprocess.PIPE,stderr=slave,
                    preexec_fn=tty,timeout=7)
                self.assertEqual(proc.returncode,0)
                args=[x.decode() for x in output.read_bytes().split(b"\x00") if x]
                self.assertIn("--stdout",args)
                self.assertEqual(args[args.index("--title")+1],
                                 "Главная › VPN › Mihomo › Вставить профиль")
            finally:
                os.close(master)
                os.close(slave)

    def test_small_terminal_stays_bounded(self):
        a=self.run_mock("Настройка автоматического восстановления Mihomo",
                        "menu",22,70)
        at=a.index("--menu")
        self.assertLessEqual(int(a[at+2]),20)
        self.assertLessEqual(int(a[at+3]),68)
        title=a[a.index("--title")+1]
        self.assertTrue(title.startswith("Главная › "),title)
        self.assertLessEqual(len(title),int(a[at+3])-7)

    def test_main_has_no_breadcrumb(self):
        a=self.run_mock("Главное меню — [TRANSIT]","menu")
        self.assertEqual(a[a.index("--title")+1],"Главное меню — [TRANSIT]")

if __name__=="__main__":
    unittest.main()
