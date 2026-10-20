#!/usr/bin/env python3
"""Offline regression for installer policy preservation and AWG-first cold fallback.

No root, production routing, VPN services, secrets, browser or media required.
The test exercises the actual source files, not copied production configuration.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / "install.sh").read_text()
SELECTOR = ROOT / "src/awg-selection-monitor"
COMMON = ROOT / "src/awg-common"


class InstallerFailoverContract(unittest.TestCase):
    def test_operator_policy_files_preserved_on_upgrade(self):
        for filename in (
            "selection.env", "node-policy.mode", "node-policy.nodes",
            "ready-auto.mode",
        ):
            self.assertIn('"' + ("$PBR_DIR/" if filename == "selection.env"
                                  else "$PBR_DIR/transports/mihomo/") + filename + '"',
                          INSTALL)
        self.assertIn('if (( UPGRADE_EXISTING == 1 )); then\n  for _policy_file', INSTALL)
        self.assertIn('if (( UPGRADE_EXISTING == 1 )); then\n  for _policy_index', INSTALL)
        self.assertIn('[[ "$_policy_sha" == "${UPGRADE_POLICY_HASHES[_policy_index]}" ]]', INSTALL)
        self.assertLess(INSTALL.index('UPGRADE_POLICY_HASHES=()'),
                        INSTALL.index('# 1. Preflight'))
        self.assertGreater(INSTALL.index('for _policy_index'),
                           INSTALL.index('systemctl restart awg-selection-monitor.service'))

    def test_clean_install_keeps_agreed_default_not_awg_first(self):
        self.assertIn('if (( UPGRADE_EXISTING == 0 )); then\n  "$SELECTION_CLI" mode auto mihomo awg', INSTALL)
        self.assertIn('"$MIHOMO_NODE_POLICY_CLI" ready-auto disable', INSTALL)
        self.assertNotIn('"$SELECTION_CLI" mode auto awg mihomo', INSTALL)
        self.assertLess(INSTALL.index('install_project_helper src/awg-selection-monitor'),
                        INSTALL.index('systemctl enable awg-pbr-setup.service'))

    def test_actual_fingerprint_absent_present_and_contents(self):
        body = re.search(r"(?ms)^upgrade_policy_fingerprint\(\)\{\n.*?^\}", INSTALL)
        self.assertIsNotNone(body)
        with tempfile.TemporaryDirectory(prefix="awg-policy-fp-") as td:
            policy = Path(td) / "selection.env"
            def fingerprint():
                cmd = body.group(0) + '\nupgrade_policy_fingerprint "$1"'
                return subprocess.run(
                    ["bash", "-c", cmd, "test", str(policy)],
                    capture_output=True, text=True, timeout=4,
                )
            self.assertEqual(fingerprint().stdout.strip(), "ABSENT")
            policy.write_text("SELECTION_MODE=auto\nSELECTION_ORDER=awg,mihomo\n")
            original = hashlib.sha256(policy.read_bytes()).hexdigest()
            self.assertEqual(fingerprint().stdout.strip(), original)
            policy.write_text("SELECTION_MODE=auto\nSELECTION_ORDER=mihomo,awg\n")
            self.assertNotEqual(fingerprint().stdout.strip(), original)

    def test_install_stages_selector_and_transit_before_starting_monitor(self):
        files = [
            'install_project_helper src/awg-selection "$SELECTION_CLI"',
            'install_project_helper src/awg-selection-monitor "$SELECTION_MONITOR"',
            'install_project_helper src/awg-transport "$TRANSPORT_CLI"',
            'install_project_helper src/awg-transit-nft',
            'install_project_helper src/awg-transit-routing',
        ]
        for item in files:
            self.assertIn(item, INSTALL)
            self.assertLess(INSTALL.index(item),
                            INSTALL.index('systemctl restart awg-selection-monitor.service'))
        self.assertIn('awg-selection-monitor.service', INSTALL)
        self.assertIn('if [[ "$candidate" == awg &&', SELECTOR.read_text())

    def test_real_auto_selector_awg_first_cold_mihomo_and_stickiness(self):
        with tempfile.TemporaryDirectory(prefix="awg-auto-transit-") as tmp:
            t = Path(tmp)
            (t / "bin").mkdir()
            (t / "run").mkdir()
            transport = t / "transport"
            transport.write_text("awg\n")
            (t / "mode").write_text("transit\n")
            (t / "selection.env").write_text(
                "SELECTION_MODE=auto\nSELECTION_PRIMARY=''\n"
                "SELECTION_ORDER=awg,mihomo\n"
            )
            mock = t / "bin" / "transport"
            mock.write_text("""#!/usr/bin/env bash
set -Eeuo pipefail
case "${1:-}" in
  check)
    if [[ "${2:-}" == awg ]]; then
      [[ "${MOCK_AWG_OK:-1}" == 1 ]]
    else
      [[ -f "${MOCK_MIHOMO_WARM}" ]]
    fi ;;
  select)
    printf 'select:%s\\n' "$2" >>"${MOCK_ACTION_LOG}"
    [[ "$2" == mihomo ]] || exit 1
    : >"${MOCK_MIHOMO_WARM}"
    printf '%s\\n' mihomo >"${AWG_TRANSPORT_FILE}" ;;
  *) exit 2 ;;
esac
""")
            mock.chmod(0o700)
            node = t / "bin" / "node-policy"
            node.write_text("#!/bin/sh\nexit 1\n")
            node.chmod(0o700)
            actions = t / "actions"
            actions.write_text("")
            env = dict(os.environ,
                AWG_COMMON_FILE=str(COMMON),
                AWG_MODE_FILE=str(t / "mode"),
                AWG_TRANSPORT_FILE=str(transport),
                AWG_SELECTION_FILE=str(t / "selection.env"),
                AWG_TRANSPORT_CLI=str(mock),
                MIHOMO_NODE_POLICY_CLI=str(node),
                AWG_SELECTION_STATE_DIR=str(t / "run"),
                AWG_SELECTION_FAILURES=str(t / "run" / "failures"),
                AWG_LOCK_FILE=str(t / "run" / "lock"),
                LOGGER_BIN="/bin/true",
                AWG_SELECTION_ONCE="1",
                AWG_AUTO_AWG_CONFIG=str(t / "no-awg"),
                MOCK_MIHOMO_WARM=str(t / "warm"),
                MOCK_ACTION_LOG=str(actions),
            )
            # The first healthy cycle cannot switch just for performance.
            env["MOCK_AWG_OK"] = "1"
            def cycle():
                return subprocess.run(["bash", str(SELECTOR)], env=env,
                                      capture_output=True, text=True, timeout=7)
            self.assertEqual(cycle().returncode, 0)
            self.assertEqual(actions.read_text(), "")
            # Three independent failed cycles start even a cold Mihomo standby.
            env["MOCK_AWG_OK"] = "0"
            self.assertEqual(cycle().returncode, 0)
            self.assertEqual(cycle().returncode, 0)
            self.assertEqual(actions.read_text(), "")
            third = cycle()
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertIn("FAILOVER=awg->mihomo", third.stdout)
            self.assertEqual(transport.read_text().strip(), "mihomo")
            self.assertEqual(actions.read_text().strip(), "select:mihomo")
            # A recovered AWG never steals traffic from healthy Mihomo.
            env["MOCK_AWG_OK"] = "1"
            self.assertEqual(cycle().returncode, 0)
            self.assertEqual(actions.read_text().strip(), "select:mihomo")


if __name__ == "__main__":
    unittest.main()
