#!/usr/bin/env python3
"""High-contrast status rendering in result textboxes; source/logs unchanged."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/"src/awg-menu").read_text()

def extract(name):
    a=SRC.index(name+"(){")
    b=SRC.index("\n}\n",a)+2
    return SRC[a:b]+"\n"

SHELL=extract("awg_readable_status_text")+"\n"+extract("show_operation_result")

class ReadableStatuses(unittest.TestCase):
    def test_literal_success_labels_are_normalized_in_view_only(self):
        sample=("Router ping:\nOK 192.168.112.1\n"
                "Direct DNS: yes\nDirect public IPv4: 37.195.130.195\n"
                "dnsmasq query: OK\n"
                "NODE_BASIC_NETWORK=NETWORK_OK\n"
                "Provider node = TOKYO\nFailure: FAIL\n")
        with tempfile.TemporaryDirectory(prefix="awg-status-contrast-") as td:
            src=Path(td)/"raw"
            src.write_text(sample)
            p=subprocess.run(["bash","-c",extract("awg_readable_status_text")+
                              '\nawg_readable_status_text "$1"',"_",str(src)],
                             capture_output=True,text=True,timeout=5,check=True)
            rendered=p.stdout
            self.assertIn("ИСПРАВНО 192.168.112.1",rendered)
            self.assertIn("Direct DNS: ДА",rendered)
            self.assertIn("dnsmasq query: ИСПРАВНО",rendered)
            self.assertIn("NODE_BASIC_NETWORK=NETWORK_OK",rendered)
            self.assertIn("TOKYO",rendered)
            self.assertIn("Failure: FAIL",rendered)
            self.assertEqual(src.read_text(),sample)

    def test_operation_keeps_original_raw_file_and_cleans_view(self):
        with tempfile.TemporaryDirectory(prefix="awg-display-safe-") as td:
            root=Path(td)
            raw=root/"original"
            out=root/"view"
            path=root/"view_path"
            mode=root/"mode"
            raw.write_text("Router ping:\nOK 192.168.112.1\nDirect DNS: yes\n")
            mock=root/"dialog"
            mock.write_text('#!/bin/sh\nwhile [ "$#" -gt 0 ]; do\n  if [ "$1" = "--textbox" ]; then\n    shift\n    printf "%s" "$1" > "$VIEW_PATH"\n    stat -c %a "$1" > "$VIEW_MODE"\n    cat "$1" > "$VIEW_COPY"\n    exit 0\n  fi\n  shift\ndone\nexit 2\n')
            mock.chmod(0o700)
            env=dict(os.environ,PATH=str(root)+":"+os.environ["PATH"],
                     VIEW_PATH=str(path),VIEW_MODE=str(mode),VIEW_COPY=str(out))
            command=(SHELL+'\nTMP="$1"\nBACKTITLE=AWG\n'
                     'show_operation_result 0 "Диагностика"\n')
            result=subprocess.run(["bash","-c",command,"_",str(raw)],
                                  env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn("Router ping:\nOK 192.168.112.1",raw.read_text())
            self.assertIn("ИСПРАВНО 192.168.112.1",out.read_text())
            self.assertNotIn("Direct DNS: yes",out.read_text())
            self.assertIn("Direct DNS: ДА",out.read_text())
            self.assertEqual(mode.read_text().strip(),"600")
            self.assertFalse(Path(path.read_text()).exists())
            self.assertIn("Результат: ВЫПОЛНЕНО",raw.read_text())

if __name__=="__main__":
    unittest.main()
