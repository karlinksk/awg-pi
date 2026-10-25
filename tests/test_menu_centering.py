#!/usr/bin/env python3
"""Menu centering without fake selectable entries, on real PTYs."""
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
MENU=(ROOT/"src/awg-menu").read_text()

def body(name):
    a=MENU.index(name+"(){")
    b=MENU.index("\n}\n",a)+2
    return MENU[a:b]+"\n"

WRAPPER=body("dialog")
BREADCRUMB=body("awg_dialog_breadcrumb_title")

class CenteredMenus(unittest.TestCase):
    def mock_run(self,rows,cols,count,prompt="Выберите действие.",height=27,menu_height=15):
        with tempfile.TemporaryDirectory(prefix="awg-centered-") as td:
            root=Path(td)
            mock=root/"dialog"
            captured=root/"argv"
            mock.write_text('#!/bin/sh\nprintf "%s\\0" "$@" > "$AWG_MENU_CAPTURE"\n')
            mock.chmod(0o700)
            options=" ".join(
                '"%d" "Action-%02d" "Help-%02d"'%(n,n,n)
                for n in range(1,count+1))
            master,slave=pty.openpty()
            try:
                fcntl.ioctl(slave,termios.TIOCSWINSZ,
                            struct.pack("HHHH",rows,cols,0,0))
                def ctty():
                    os.setsid()
                    fcntl.ioctl(slave,termios.TIOCSCTTY,0)
                shell=(BREADCRUMB+WRAPPER+
                    '\nmenu_probe(){ dialog --backtitle AWG --title "Система" --item-help '
                    '--menu "$PROMPT" %d 104 %d %s; }\nmenu_probe\n'
                    %(height,menu_height,options))
                env=dict(os.environ,LC_ALL="C.UTF-8",
                         PATH=str(root)+":"+os.environ["PATH"],
                         AWG_MENU_CAPTURE=str(captured),PROMPT=prompt)
                result=subprocess.run(["bash","-c",shell],env=env,
                    stdin=slave,stdout=slave,stderr=slave,
                    preexec_fn=ctty,timeout=5)
                self.assertEqual(result.returncode,0)
                return [x.decode() for x in captured.read_bytes().split(b"\0") if x]
            finally:
                os.close(master)
                os.close(slave)

    @staticmethod
    def shape(args):
        at=args.index("--menu")
        return tuple(map(int,args[at+2:at+5]))

    def test_short_menu_compact_and_centered(self):
        args=self.mock_run(36,132,10)
        h,w,m=self.shape(args)
        self.assertEqual((h,w,m),(17,104,10))
        self.assertEqual(args[-3:],["10","Action-10","Help-10"])
        self.assertEqual(args[args.index("--title")+1],"Главная › Система")

    def test_long_catalog_still_scrolls_and_has_no_fake_items(self):
        args=self.mock_run(36,132,50)
        h,w,m=self.shape(args)
        self.assertEqual((h,w,m),(22,104,15))
        self.assertEqual(len(args[args.index("--menu")+5:]),50*3)
        self.assertEqual(args[-3:],["50","Action-50","Help-50"])

    def test_tiny_ssh_protects_wrapped_prompt(self):
        text="Подписка и фильтры. "*12
        args=self.mock_run(22,70,10,prompt=text)
        h,w,m=self.shape(args)
        self.assertLessEqual(h,20)
        self.assertLessEqual(w,68)
        self.assertGreaterEqual(m,3)
        self.assertEqual(len(args[args.index("--menu")+5:]),30)

    def test_original_large_summary_gets_height_budget(self):
        prompt="\n".join(["Строка состояния шлюза"]*12)
        args=self.mock_run(36,132,11,prompt)
        h,w,m=self.shape(args)
        self.assertGreaterEqual(h,25)
        self.assertEqual(m,10)  # 11 entries scroll within the available height.

    @unittest.skipUnless(subprocess.run(["sh","-c","command -v dialog >/dev/null"],
                         capture_output=True).returncode==0,
                         "Debian dialog not installed")
    def test_native_dialog_real_terminal_rows_are_centered(self):
        # This also independently validates the ncurses drawing geometry.
        pid,fd=pty.fork()
        if pid==0:
            fcntl.ioctl(0,termios.TIOCSWINSZ,
                        struct.pack("HHHH",34,132,0,0))
            os.environ["TERM"]="xterm-256color"
            options=" ".join('"'+str(n)+'" "Choice%02d" "help"'%n
                             for n in range(1,10))
            script=(BREADCRUMB+WRAPPER+
                '\nrun(){ dialog --title "Центр" --item-help --menu '
                '"Выберите" 26 100 15 '+options+'; }\nrun\n')
            os.execlp("bash","bash","-c",script)
        fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack("HHHH",34,132,0,0))
        data=bytearray()
        try:
            start=time.monotonic()
            while time.monotonic()-start<2:
                ready,_,_=select.select([fd],[],[],.1)
                if ready:
                    try:data.extend(os.read(fd,16000))
                    except OSError:break
                if b"Choice09" in data:break
        finally:
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:os.waitpid(pid,0)
            except ChildProcessError:pass
            os.close(fd)
        screen=data.decode("utf-8",errors="replace")
        locations=[]
        for choice in ("Choice01","Choice09"):
            pos=screen.find(choice)
            self.assertGreaterEqual(pos,0,choice)
            cursors=re.findall(r"\x1b\[([0-9;]*)([Hf])",screen[:pos])
            self.assertTrue(cursors)
            locations.append(int(cursors[-1][0].split(";")[0]))
        self.assertEqual(locations[1]-locations[0],8)
        self.assertLessEqual(abs(sum(locations)/2-17),2)

if __name__=="__main__":
    unittest.main()
