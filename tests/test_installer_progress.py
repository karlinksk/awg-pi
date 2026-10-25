#!/usr/bin/env python3
"""Rootless installer progress contract: no network or gateway mutation."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"install.sh").read_text()
BEGIN="install_stage_with_heartbeat(){"
END="\n}\n"

class InstallerProgress(unittest.TestCase):
    def test_stage18_progress_is_part_of_fresh_install(self):
        self.assertIn('install_stage_with_heartbeat "Stage18: Node.js и yt-dlp" /usr/local/sbin/awg-mihomo-stage18-ram-runtime prefetch',SOURCE)
        self.assertIn('if (( UPGRADE_EXISTING == 0 )); then\n  STAGE="установка видеодекодера Stage18"',SOURCE)
        self.assertIn("статус обновляется каждые 10 с",SOURCE)

    def run_helper(self,exitcode):
        start=SOURCE.index(BEGIN)
        end=SOURCE.index(END,start)+len(END)
        func=SOURCE[start:end]
        program="\n".join((
            "set -Eeuo pipefail",
            'log(){ printf "%s\\n" "$*"; }',
            'ok(){ printf "%s\\n" "$*"; }',
            'err(){ printf "%s\\n" "$*" >&2; }',
            func,
            f"install_stage_with_heartbeat TEST /bin/sh -c 'exit {exitcode}'"
        ))
        return subprocess.run(["bash","-c",program],capture_output=True,text=True,timeout=6)

    def test_success_status(self):
        result=self.run_helper(0)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("TEST: завершено",result.stdout)

    def test_failure_status_propagates(self):
        result=self.run_helper(7)
        self.assertEqual(result.returncode,7,result.stderr)
        self.assertIn("код 7",result.stderr)

if __name__=="__main__":
    unittest.main()
