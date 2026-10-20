#!/usr/bin/env python3
"""Isolated regression: a failed live Mihomo node must not restart during READY recovery."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

CONFIG = Path(__file__).resolve().parents[1] / "src" / "awg-mihomo-configure"


class FailedNodeRecoveryRollback(unittest.TestCase):
    def run_rollback(self, recovery: str):
        # Exercise the actual production rollback function with mock systemctl
        # and stubbed file snapshots. Nothing touches VPN, root or systemd.
        source = CONFIG.read_text()
        marker = "  rollback_node(){"
        self.assertEqual(source.count(marker), 1)
        body = source.split(marker, 1)[1].split(
            "\n  }\n  trap rollback_node ERR", 1
        )[0]
        with tempfile.TemporaryDirectory(prefix="awg-recovery-rollback-") as tmp:
            root = Path(tmp)
            log = root / "events"
            binpath = root / "systemctl"
            binpath.write_text(
                '#!/bin/sh\nprintf "systemctl:%s\\n" "$*" >> "$EVENT_LOG"\n'
            )
            binpath.chmod(0o700)
            snap = root / "snapshot"
            snap.mkdir()
            script = """
restore_path(){ printf 'restore:%s\\n' "$2" >> "$EVENT_LOG"; }
restore_unit_state(){
  printf 'restore_unit_state:%s\\n' "$*" >> "$EVENT_LOG"
}
MIHOMO_SERVICE=awg-mihomo.service
MIHOMO_ENV_FILE=/unused/env
MIHOMO_ENDPOINT_IP_FILE=/unused/ip
MIHOMO_EXPECTED_EGRESS_IP_FILE=/unused/expected
MIHOMO_NODE_NAME_FILE=/unused/node
MIHOMO_CONFIG_FILE=/unused/config
service_enabled=1
service_active=1
health_was_active=0
current=mihomo
snapshot="$SNAPSHOT"
SYSTEMCTL_BIN="$SYSTEMCTL_MOCK"
rollback_node(){
""" + body + """
}
false
rollback_node
"""
            env = dict(
                os.environ,
                EVENT_LOG=str(log),
                SNAPSHOT=str(snap),
                SYSTEMCTL_MOCK=str(binpath),
                MIHOMO_NODE_FAILOVER_RECOVERY=recovery,
            )
            r = subprocess.run(
                ["bash", "-c", script],
                env=env, capture_output=True, text=True, timeout=5,
            )
            return r, log.read_text()

    def test_failed_node_not_restarted_in_auto_recovery(self):
        result, events = self.run_rollback("1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("systemctl:enable awg-mihomo.service", events)
        self.assertIn("systemctl:stop awg-mihomo.service", events)
        self.assertNotIn("restore_unit_state:", events)
        self.assertNotIn("systemctl:start awg-mihomo.service", events)

    def test_normal_manual_rollback_remains_unchanged(self):
        result, events = self.run_rollback("0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("restore_unit_state:awg-mihomo.service 1 1", events)


if __name__ == "__main__":
    unittest.main()
