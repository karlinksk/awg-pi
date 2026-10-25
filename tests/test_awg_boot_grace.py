#!/usr/bin/env python3
"""Cold-boot AWG handshake grace without changing ordinary AUTO failover.

Uses the actual monitor source with isolated files and mock commands. No root,
VPN network calls, system services or live routing.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "src" / "awg-selection-monitor"
COMMON = ROOT / "src" / "awg-common"


class AWGColdBoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="awg-boot-grace-")
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        (self.p / "run").mkdir()
        (self.p / "awg0").mkdir()
        (self.p / "active").write_text("awg\n")
        (self.p / "uptime").write_text("61.9 390\n")
        (self.p / "selection.env").write_text("SELECTION_MODE=auto\nSELECTION_ORDER=awg,mihomo\n")
        (self.p / "actions").write_text("")
        (self.p / "profile").write_text("mock config\n")
        transport = self.p / "transport"
        transport.write_text("""#!/usr/bin/env bash
set -Eeuo pipefail
case "$1" in
  get) cat "$AWG_TRANSPORT_FILE";;
  check) if [[ "$2" == awg ]]; then
           [[ "$MOCK_AWG_OK" == 1 ]]
         else
           [[ "$MOCK_MIHOMO_OK" == 1 ]]
         fi;;
  network-check) [[ "$MOCK_MIHOMO_OK" == 1 ]];;
  select) echo "$2" >>"$MOCK_ACTIONS"
          if [[ "$2" == awg ]]; then
            [[ "$MOCK_AWG_OK" == 1 ]] || exit 1
          else
            [[ "$MOCK_MIHOMO_OK" == 1 ]] || exit 1
          fi
          echo "$2" >"$AWG_TRANSPORT_FILE";;
  *) exit 2;;
esac
""")
        transport.chmod(0o755)
        ctl = self.p / "systemctl"
        ctl.write_text('#!/bin/sh\n[ "$MOCK_UNIT_OK" = 1 ]\n')
        ctl.chmod(0o755)
        node = self.p / "node"
        node.write_text("#!/bin/sh\nexit 1\n")
        node.chmod(0o755)
        self.env = {
            **os.environ,
            "AWG_COMMON_FILE": str(COMMON),
            "AWG_TRANSPORT_FILE": str(self.p / "active"),
            "AWG_SELECTION_FILE": str(self.p / "selection.env"),
            "AWG_TRANSPORT_CLI": str(transport),
            "MIHOMO_NODE_POLICY_CLI": str(node),
            "AWG_SELECTION_STATE_DIR": str(self.p / "run"),
            "AWG_SELECTION_FAILURES": str(self.p / "run" / "failures"),
            "AWG_LOCK_FILE": str(self.p / "maintenance.lock"),
            "AWG_SELECTION_ONCE": "1",
            "AWG_SELECTION_FAILURE_THRESHOLD": "3",
            "AWG_SELECTION_AWG_BOOT_GRACE_SECONDS": "120",
            "AWG_SELECTION_UPTIME_FILE": str(self.p / "uptime"),
            "AWG_SELECTION_AWG_IFACE_DIR": str(self.p / "awg0"),
            "AWG_SELECTION_SYSTEMCTL_BIN": str(ctl),
            "AWG_AUTO_AWG_CONFIG": str(self.p / "profile"),
            "LOGGER_BIN": "/bin/true",
            "MOCK_ACTIONS": str(self.p / "actions"),
            "MOCK_AWG_OK": "0",
            "MOCK_MIHOMO_OK": "1",
            "MOCK_UNIT_OK": "1",
        }

    def cycle(self):
        r = subprocess.run(["bash", str(MONITOR)], env=self.env,
                           capture_output=True, text=True, timeout=8)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_ntp_jump_handshake_false_negative_ignored_during_boot(self):
        for _ in range(3):
            self.assertNotIn("FAILOVER", self.cycle())
        self.assertEqual((self.p / "active").read_text(), "awg\n")
        self.assertEqual((self.p / "actions").read_text(), "")
        self.assertEqual((self.p / "run" / "failures").read_text().strip(), "0")

    def test_bounded_expiration_keeps_real_failover(self):
        (self.p / "uptime").write_text("120.1 500\n")
        for _ in range(2):
            self.assertNotIn("FAILOVER", self.cycle())
        self.assertIn("FAILOVER=awg->mihomo", self.cycle())
        self.assertEqual((self.p / "actions").read_text(), "mihomo\n")

    def test_missing_awg_interface_not_masked(self):
        (self.p / "awg0").rmdir()
        for _ in range(2):
            self.cycle()
        self.assertIn("FAILOVER=awg->mihomo", self.cycle())

    def test_failed_awg_service_not_masked(self):
        self.env["MOCK_UNIT_OK"] = "0"
        for _ in range(2):
            self.cycle()
        self.assertIn("FAILOVER=awg->mihomo", self.cycle())

    def test_mihomo_failure_unchanged_during_awg_boot_grace(self):
        (self.p / "active").write_text("mihomo\n")
        self.env["MOCK_AWG_OK"] = "1"
        self.env["MOCK_MIHOMO_OK"] = "0"
        for _ in range(2):
            self.cycle()
        self.assertIn("FAILOVER=mihomo->awg", self.cycle())

    def test_healthy_awg_and_manual_mode(self):
        self.env["MOCK_AWG_OK"] = "1"
        self.cycle()
        self.assertEqual((self.p / "run" / "failures").read_text().strip(), "0")
        self.env["MOCK_AWG_OK"] = "0"
        (self.p / "selection.env").write_text("SELECTION_MODE=manual\n")
        for _ in range(3):
            self.cycle()
        self.assertEqual((self.p / "actions").read_text(), "")
        self.assertEqual((self.p / "run" / "failures").read_text().strip(), "0")

    def test_invalid_uptime_never_suppresses_fallback(self):
        (self.p / "uptime").write_text("invalid\n")
        for _ in range(2):
            self.cycle()
        self.assertIn("FAILOVER=awg->mihomo", self.cycle())


if __name__ == "__main__":
    unittest.main()
