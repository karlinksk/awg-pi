#!/usr/bin/env python3
"""Passive production canary and rollback remain independent of selection."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"scripts/awg-mihomo-balanced-canary.sh"

class CanarySafety(unittest.TestCase):
    def test_root_is_required_to_apply_and_restore(self):
        data=SRC.read_text()
        self.assertIn('require_root',data)
        self.assertIn('apply)',data)
        self.assertIn('restore)',data)

    def test_no_node_selection_or_router_modification(self):
        data=SRC.read_text()
        for phrase in ('node select-auto','transport-select awg',
                       'transport-select mihomo','nft add','nft flush',
                       'ip route replace','/tool fetch'):
            self.assertNotIn(phrase,data)

    def test_gate_must_remain_off_for_passive_install(self):
        data=SRC.read_text()
        self.assertGreaterEqual(data.count('service gate must be OFF'),1)
        self.assertIn('CANARY_GATE=OFF',data)
        self.assertIn('CANARY_TIMER=NOT_ENABLED',data)

    def test_backup_before_install_and_restore_exists(self):
        data=SRC.read_text()
        self.assertLess(data.index('cp -p -- "${TARGET[i]}"'),data.index('install -m "${FILE_MODE[i]}"'))
        self.assertIn('restore_files(){',data)
        self.assertIn('trap rollback_if_needed EXIT',data)
        self.assertIn("trap 'exit 143' TERM HUP",data)
        self.assertIn('CANARY_RESTORE=COMPLETE',data)

    def test_no_autoenable_on_apply(self):
        s=SRC.read_text()
        apply=s.split("  apply)",1)[1].split("  restore)",1)[0]
        self.assertNotIn("systemctl enable",apply)
        self.assertNotIn("systemctl restart",apply)
        self.assertIn("systemctl daemon-reload",apply)

    def test_only_declared_services_and_units_installed(self):
        s=SRC.read_text()
        for name in ('awg-mihomo-smart','awg-mihomo-service-check.py',
                     'awg-mihomo-video-decode.py','awg-mihomo-network-eligibility.py',
                     'awg-mihomo-node-policy','awg-selection-monitor',
                     'awg-mihomo-stage18-ram-runtime'):
            self.assertIn(name,s)
        self.assertNotIn('awg-mihomo-pool-refresh.timer',s)
        self.assertNotIn('awg-quick@awg0.service',s)

    def test_temporary_files_protected(self):
        s=SRC.read_text()
        self.assertIn('umask 077',s)
        self.assertIn('mkdir -m 700 "$dir"',s)
        self.assertIn('chmod 600 "$dir/manifest"',s)
        self.assertIn('[[ ! -L "${TARGET[i]}" ]]',s)

if __name__=="__main__": unittest.main()
