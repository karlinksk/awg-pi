#!/usr/bin/env python3
"""Offline systemd Health Monitor stop/recovery contract tests.

Runs actual source code with fake ip/transport helpers in a temporary directory.
No real systemd, nftables, VPN devices, or network calls.
"""

import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HEALTH_SCRIPT = ROOT / "src/awg-pbr-health"
INSTALLER = ROOT / "install.sh"


def installer_block(source, target):
    # Read the exact heredoc shipped by the installer, not a test-only copy.
    pattern = r'cat >"\$' + target + r'" <<\x27EOF\x27\n(.*?)\nEOF'
    match = re.search(pattern, source, flags=re.S)
    if match is None:
        raise AssertionError(f"Installer heredoc {target} not found")
    return match.group(1) + "\n"


class HealthSystemdRecovery(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="awg-health-systemd-")
        self.tmp = Path(self.work.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.state = self.tmp / "state"
        self.state.mkdir()
        self.rule = self.tmp / "rule"
        self.guard = self.tmp / "transit-guard"
        self.log = self.tmp / "ip.log"
        self.transit_log = self.tmp / "transit.log"
        self.mode = self.tmp / "mode"
        self.vpn_enabled = self.tmp / "vpn-enabled"
        self.health_ok = self.tmp / "transport-health"
        self.env_file = self.tmp / "env"
        self.common = self.tmp / "common.sh"
        self.helper = self.tmp / "awg-pbr-failopen"
        self.proc = None

        self.mode.write_text("selective\n")
        self.vpn_enabled.write_text("1\n")
        self.health_ok.write_text("up\n")
        self.log.write_text("")
        self.transit_log.write_text("")
        self.env_file.write_text("""VPN_IF='awg0'
VPN_MARK='0x100'
HEALTH_MARK='0x101'
VPN_TABLE='100'
HEALTH_TABLE='101'
HEALTH_INTERVAL='0.1'
HANDSHAKE_MAX_AGE='180'
""")
        self.common.write_text("""awg_mode_get(){ cat "$AWG_MODE_FILE"; }
awg_transport_get(){ printf 'mihomo\n'; }
awg_transport_device(){ [[ "$1" == mihomo ]] && printf 'mihomo0\n'; }
""")
        self.executable("ip", """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$MOCK_IP_LOG"
case "$*" in
  'link show mihomo0') ;;
  '-4 route replace default dev mihomo0 table 101'|'-4 route replace default dev mihomo0 table 100') ;;
  '-4 rule show')
    [[ ! -f "$MOCK_RULE" ]] || echo '100: from all fwmark 0x100 lookup 100'
    ;;
  '-4 rule add priority 90 fwmark 0x101 lookup 101') ;;
  '-4 rule add priority 100 fwmark 0x100 lookup 100') : > "$MOCK_RULE" ;;
  '-4 rule del priority 100 fwmark 0x100 lookup 100')
    if [[ -f "$MOCK_RULE" ]]; then rm -f "$MOCK_RULE"; else exit 2; fi
    ;;
  *) echo "Unexpected mock ip: $*" >&2; exit 90 ;;
esac
""")
        self.executable("transport-check", """#!/usr/bin/env bash
[[ "$*" == 'check mihomo' ]] || exit 2
[[ "$(cat "$MOCK_HEALTH_FILE")" == up ]]
""")
        self.executable("transit-routing", """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$MOCK_TRANSIT_LOG"
case "$*" in
  apply) : > "$MOCK_RULE"; : > "$MOCK_GUARD" ;;
  disable) rm -f "$MOCK_RULE" ;;  # Guard remains active in mock
  *) exit 3 ;;
esac
""")
        self.executable("logger", "#!/usr/bin/env bash\nexit 0\n")

        installer = INSTALLER.read_text()
        service = installer_block(installer, "HEALTH_SERVICE")
        self.assertIn("ExecStart=/usr/local/sbin/awg-pbr-health", service)
        self.assertIn("ExecStopPost=/usr/local/sbin/awg-pbr-failopen", service)
        self.assertIn("Restart=always", service)

        # Execute the actual installer helper, redirecting only three absolute
        # paths to isolated fixtures; fake ip is ahead of PATH.
        helper = installer_block(installer, "FAILOPEN_SCRIPT")
        for old, new in (
            ("source /etc/awg-pbr/env", f"source {self.env_file}"),
            ("mkdir -p /run/awg-pbr", f"mkdir -p {self.state}"),
            ("echo down >/run/awg-pbr/health.state",
             f"echo down >{self.state / 'health.state'}"),
        ):
            self.assertIn(old, helper)
            helper = helper.replace(old, new)
        self.helper.write_text(helper)
        self.helper.chmod(0o700)

        self.env = os.environ.copy()
        self.env.update({
            "AWG_ENV_FILE": str(self.env_file),
            "AWG_COMMON_FILE": str(self.common),
            "AWG_MODE_FILE": str(self.mode),
            "AWG_TRANSPORT_FILE": str(self.tmp / "transport"),
            "AWG_VPN_ENABLED_FILE": str(self.vpn_enabled),
            "AWG_STATE_DIR": str(self.state),
            "AWG_TRANSIT_ROUTING": str(self.bin / "transit-routing"),
            "AWG_TRANSPORT_CLI": str(self.bin / "transport-check"),
            "MIHOMO_TUN_IF": "mihomo0",
            "IP_BIN": str(self.bin / "ip"),
            "LOGGER_BIN": str(self.bin / "logger"),
            "MOCK_RULE": str(self.rule),
            "MOCK_GUARD": str(self.guard),
            "MOCK_IP_LOG": str(self.log),
            "MOCK_TRANSIT_LOG": str(self.transit_log),
            "MOCK_HEALTH_FILE": str(self.health_ok),
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
        })

    def executable(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o700)

    def tearDown(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.communicate(timeout=5)
        self.work.cleanup()

    def health_once(self):
        subprocess.run(
            ["bash", str(HEALTH_SCRIPT)],
            env=dict(self.env, AWG_HEALTH_ONCE="1"),
            check=True, timeout=6, capture_output=True, text=True,
        )

    def start_monitor(self):
        self.proc = subprocess.Popen(
            ["bash", str(HEALTH_SCRIPT)],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.state / "health.state"
            if state.exists() and state.read_text().strip() == "up" and self.rule.exists():
                return
            if self.proc.poll() is not None:
                out, err = self.proc.communicate(timeout=2)
                self.fail(f"Health process exited early: {out} {err}")
            time.sleep(0.03)
        self.fail("Health process never became healthy")

    def stop_monitor(self, sig):
        self.proc.send_signal(sig)
        self.proc.communicate(timeout=5)
        self.proc = None

    def poststop(self):
        subprocess.run(
            ["bash", str(self.helper)], env=self.env,
            check=True, timeout=5, capture_output=True, text=True,
        )

    def assert_up(self):
        self.assertTrue(self.rule.exists())
        self.assertEqual((self.state / "health.state").read_text().strip(), "up")

    def assert_down(self):
        self.assertFalse(self.rule.exists())
        self.assertEqual((self.state / "health.state").read_text().strip(), "down")

    def test_selective_sigterm_poststop_recovers(self):
        self.start_monitor()
        self.assert_up()
        self.stop_monitor(signal.SIGTERM)
        self.assert_down()  # EXIT trap
        self.poststop()  # Idempotent installer ExecStopPost
        self.assert_down()
        self.health_once()
        self.assert_up()

    def test_selective_sigkill_poststop_recovers(self):
        self.start_monitor()
        self.assert_up()
        self.stop_monitor(signal.SIGKILL)  # No EXIT trap
        self.assertTrue(self.rule.exists())
        self.poststop()
        self.assert_down()
        self.health_once()
        self.assert_up()

    def test_selective_unhealthy_restart_stays_failopen(self):
        self.start_monitor()
        self.stop_monitor(signal.SIGKILL)
        self.poststop()
        self.health_ok.write_text("down\n")
        self.health_once()
        self.assert_down()

    def test_transit_stop_recovery_guard_contract(self):
        self.mode.write_text("transit\n")
        self.start_monitor()
        self.assert_up()
        self.assertTrue(self.guard.exists())
        self.stop_monitor(signal.SIGTERM)
        self.assert_down()
        self.assertTrue(self.guard.exists())
        self.assertIn("disable", self.transit_log.read_text())
        self.poststop()
        self.assert_down()
        self.assertTrue(self.guard.exists())
        self.health_once()
        self.assert_up()
        self.assertIn("apply", self.transit_log.read_text())


if __name__ == "__main__":
    unittest.main()
