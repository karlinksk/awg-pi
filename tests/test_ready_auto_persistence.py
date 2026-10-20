#!/usr/bin/env python3
"""Persistent READY-first Hot Pool onboarding without a live switch."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "src/awg-mihomo-node-policy"
INSTALL = ROOT / "install.sh"
MONITOR = ROOT / "src/awg-selection-monitor"


class ReadyAutoPersistence(unittest.TestCase):
    def test_fresh_installer_defaults_ready_priority_off(self):
        s = INSTALL.read_text()
        self.assertIn('"$MIHOMO_NODE_POLICY_CLI" ready-auto disable >/dev/null', s)
        self.assertLess(s.index('install_project_helper src/awg-mihomo-ready-postcheck-tun'),
                        s.index('"$MIHOMO_NODE_POLICY_CLI" ready-auto disable'))
        self.assertIn('if (( UPGRADE_EXISTING == 0 )); then', s)

    def test_bounded_service_check_is_only_on_candidate_failover(self):
        s = POLICY.read_text()
        self.assertIn("MIHOMO_SERVICE_GATE_MODE=balanced", s)
        self.assertIn('if [[ "$MIHOMO_READY_AUTO_CANARY" == 1', s)
        self.assertIn('candidate="$("$MIHOMO_HOT_POOL_CLI"', s)
        self.assertIn('"$MIHOMO_READY_POSTCHECK_BIN" "$candidate"', s)
        self.assertIn('service_candidate_allowed "$candidate"', s)
        self.assertIn('excludes+=("$candidate")', s)
        self.assertIn('READY_AUTO=RETRY_NEXT_READY', s)
        self.assertIn('quiesce_failed_mihomo', s)
        self.assertNotIn('"$MIHOMO_CONFIGURE" node select-auto "$current"', s)
        self.assertIn('MIHOMO_NODE_FAILOVER=', s)
        # Active transport health monitoring should not begin treating random
        # Cloudflare 403 or HTTP-only YouTube checks as actual outages.
        self.assertNotIn('MIHOMO_READY_AUTO_CANARY=1', MONITOR.read_text())

    def test_cli_enable_disable_is_persistent_and_non_disruptive(self):
        with tempfile.TemporaryDirectory(prefix="ready-policy-") as directory:
            p = Path(directory)
            ready = p / "private" / "ready-auto.mode"
            node = p / "private" / "node-policy.mode"
            node.parent.mkdir(mode=0o700)
            node.write_text("auto\n")
            env = {
                "MIHOMO_NODE_POLICY_MODE_FILE": str(node),
                "MIHOMO_READY_AUTO_MODE_FILE": str(ready),
                "MIHOMO_NODE_NAME_FILE": str(p / "missing-node"),
                "MIHOMO_POOL_CLI": "/bin/true",
                "MIHOMO_HOT_POOL_CLI": "/bin/true",
                "MIHOMO_READY_GUARD_BIN": "/bin/true",
                "MIHOMO_READY_POSTCHECK_BIN": "/bin/true",
                "MIHOMO_SERVICE_QUICKCHECK_BIN": "/bin/true",
                "MIHOMO_NETWORK_GATE_BIN": "/bin/true",
                "MIHOMO_SERVICE_GATE_MODE_FILE": str(p / "missing-gate"),
            }

            # Mocked, isolated run: no real sudo or Pi runtime access.
            script = POLICY.read_text()
            root_guard = '[[ ${EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"'
            self.assertEqual(script.count(root_guard), 1)
            fixture = p / "node-policy-rootless"
            fixture.write_text(script.replace(root_guard, ": # isolated rootless test"))
            def run(*args: str, override: dict[str, str] | None = None):
                pairs = dict(env)
                pairs.update(override or {})
                return subprocess.run(
                    ["bash", str(fixture), *args],
                    env=dict(os.environ, **pairs),
                    text=True, capture_output=True, timeout=5,
                )

            def read_private() -> str:
                return ready.read_text()

            self.assertIn("MIHOMO_READY_AUTO=disabled", run("ready-auto", "status").stdout)
            enabled = run("ready-auto", "enable")
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            self.assertEqual(read_private(), "1\n")
            self.assertEqual(ready.stat().st_mode & 0o777, 0o600)
            status = run("status")
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("Hot Pool READY priority: enabled", status.stdout)
            self.assertIn("Service eligibility gate: balanced", status.stdout)
            self.assertIn("Hot Pool READY-priority AUTO", status.stdout)
            disabled = run("ready-auto", "disable")
            self.assertEqual(disabled.returncode, 0, disabled.stderr)
            self.assertEqual(read_private(), "0\n")
            status = run("status")
            self.assertIn("Hot Pool READY priority: disabled", status.stdout)
            self.assertIn("Service eligibility gate: off", status.stdout)
            self.assertIn("health-pool AUTO", status.stdout)

            refused = run("ready-auto", "enable",
                          override={"MIHOMO_READY_POSTCHECK_BIN": str(p / "missing")})
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("READY_AUTO=REJECTED_MISSING_GUARD", refused.stderr)
            self.assertEqual(read_private(), "0\n")


if __name__ == "__main__":
    unittest.main()
