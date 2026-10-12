#!/usr/bin/env python3
"""Stage19 one-command wrapper: offline fail-closed bootstrap verification."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/"scripts/awg-stage19-safe-start.sh"
BOOT=ROOT/"scripts/awg-media-runtime-ram.sh"
RUN=ROOT/"scripts/awg-stage19-run-once.sh"

class Stage19SafeStart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script=P.read_text()
        cls.bootstrap=BOOT.read_text()
        cls.root=RUN.read_text()

    def test_non_root_bootstrap_before_sudo(self):
        script=self.script
        self.assertIn('RUN_WRAPPER_WITHOUT_SUDO',script)
        self.assertIn('bash "$BOOTSTRAP"',script)
        self.assertIn('exec sudo bash "$RUNNER"',script)
        self.assertLess(script.index('bash "$BOOTSTRAP"'),
                        script.index('exec sudo bash "$RUNNER"'))
        self.assertIn('MUST_NOT_RUN_AS_ROOT',self.bootstrap)
        self.assertNotIn('sudo bash "$BOOTSTRAP"',script)

    def test_pinned_hashes_match_privileged_driver(self):
        for which in ("NODE_SHA","YTDLP_SHA"):
            pattern=r"(?m)^"+which+r"=([0-9a-f]{64})$"
            wrapper=re.search(pattern,self.script)
            driver=re.search(pattern,self.root)
            self.assertIsNotNone(wrapper)
            self.assertIsNotNone(driver)
            self.assertEqual(wrapper.group(1),driver.group(1))
        self.assertIn('RAM_NODE_SHA256_INVALID',self.script)
        self.assertIn('RAM_YTDLP_SHA256_INVALID',self.script)

    def test_existing_ram_revalidated_and_symlinks_refused(self):
        self.assertIn('RAM_RUNTIME_RECHECK',self.script)
        self.assertIn('RAM_RUNTIME_PARTIAL_REFUSED',self.script)
        self.assertIn('! -L "$RAM"',self.script)
        self.assertIn('! -L "$RAM/bin/$item"',self.script)
        self.assertIn('"$RAM/bin/node" --version',self.script)

    def test_no_sudoers_service_or_routing_changes(self):
        self.assertIn('GIT_OPTIONAL_LOCKS=0',self.script)
        self.assertIn('AUDITED_SOURCE_MODIFIED',self.script)
        self.assertNotIn('ip route add',self.script)
        self.assertNotIn('ip rule add',self.script)
        self.assertNotIn('systemctl enable',self.script)
        self.assertNotIn('/etc/sudoers',self.script)
        self.assertIn('trap trap_cleanup EXIT',self.root)
        self.assertIn('TABLE100_UNCHANGED',self.root)

    def test_stage19_only_selected_candidate(self):
        self.assertIn('PORTS=(17891)',self.root)
        self.assertIn('NAMES=(shadowsocks-27307)',self.root)
        self.assertIn('--target shadowsocks-27307',self.root)
        self.assertIn('STAGE19_ROOT_ONE_SHOT_STARTING',self.script)

if __name__=="__main__":unittest.main()
