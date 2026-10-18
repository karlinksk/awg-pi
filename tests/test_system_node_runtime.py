"""Shared system-wide Node.js policy, verified with Stage18 SHA256 pin."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / "install.sh").read_text()
SCRIPT = ROOT / "scripts/awg-system-node.sh"
SYSTEM = SCRIPT.read_text()
STAGE18 = (ROOT / "scripts/awg-mihomo-stage18-ram-runtime.sh").read_text()
DC = (ROOT / "src/awg-dc").read_text()
DC_SERVICE = (ROOT / "units/awg-dc-remote@.service").read_text()


class SystemNodeRuntime(unittest.TestCase):
    def test_syntax(self):
        for file in (ROOT / "install.sh", SCRIPT, ROOT / "src/awg-dc"):
            p = subprocess.run(["bash", "-n", str(file)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)

    def test_exact_node_version_and_sha_match_stage18(self):
        self.assertIn("PIN_VERSION=v22.16.0", SYSTEM)
        self.assertIn("PIN_SHA=fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5", SYSTEM)
        self.assertIn("NODE_SHA=fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5", STAGE18)
        self.assertIn("v22.16.0", STAGE18)
        self.assertIn("SOURCE=/var/lib/awg-pbr/stage18-runtime/node", SYSTEM)
        self.assertIn('hash_ok "$SOURCE" || fail STAGE18_PINNED_NODE_CACHE_INVALID', SYSTEM)
        self.assertIn("typeof WebSocket", SYSTEM)

    def test_global_node_path_is_verified_and_debian_apt_retained(self):
        self.assertIn("LINK=/usr/local/bin/node", SYSTEM)
        self.assertIn("RUNTIME_DIR=/usr/local/lib/awg-pi/node", SYSTEM)
        self.assertIn("env PATH=/usr/local/bin:/usr/bin:/bin node -e", SYSTEM)
        self.assertIn("DEBIAN_APT_NODE_PRESERVED=YES", SYSTEM)
        self.assertNotIn("mv -fT -- \"$BIN\" /usr/bin/node", SYSTEM)
        self.assertNotIn("apt-get remove nodejs", SYSTEM)
        self.assertIn("UNMANAGED_SYSTEM_NODE_LINK", SYSTEM)
        self.assertIn("UNTRUSTED_RUNTIME_DIRECTORY", SYSTEM)

    def test_fresh_installs_get_node_upgrade_has_explicit_opt_in(self):
        self.assertIn('install_project_helper scripts/awg-system-node.sh "$SYSTEM_NODE_SCRIPT"', INSTALL)
        self.assertIn('"$SYSTEM_NODE_SCRIPT" apply || die', INSTALL)
        self.assertIn('AWG_SYSTEM_NODE_UPGRADE:-0', INSTALL)
        self.assertIn('if (( UPGRADE_EXISTING == 0 )); then', INSTALL)
        self.assertIn('elif "$SYSTEM_NODE_SCRIPT" status >/dev/null', INSTALL)
        self.assertLess(
            INSTALL.index('/usr/local/sbin/awg-mihomo-stage18-ram-runtime prefetch'),
            INSTALL.index('if (( UPGRADE_EXISTING == 0 )); then\n  "$SYSTEM_NODE_SCRIPT" apply'),
        )
        self.assertIn('bash -n "$SYSTEM_NODE_SCRIPT"', INSTALL)

    def test_system_node_upgrade_opt_in_reachable_when_not_fresh(self):
        # Execute only the Node policy block with a mock helper. No root,
        # network, package manager, or system runtime is touched.
        first = INSTALL.index("# Fresh Debian 13 ships Node.js")
        last = INSTALL.index(
            "install_project_python_helper src/awg-mihomo-service-eligibility.py",
            first,
        )
        node_policy = INSTALL[first:last]
        with tempfile.TemporaryDirectory(prefix="awg-node-install-test-") as tmp:
            helper = Path(tmp) / "mock-node"
            log = Path(tmp) / "calls"
            helper.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  apply) printf 'APPLY\\n' >> \"$MOCK_NODE_LOG\" ;;\n"
                "  status) exit 0 ;;\n"
                "  *) exit 6 ;;\n"
                "esac\n"
            )
            helper.chmod(0o755)
            script = (
                "set -Eeuo pipefail\n"
                "SYSTEM_NODE_SCRIPT=\"$MOCK_NODE_HELPER\"\n"
                "ok(){ :; }\nwarn(){ :; }\ndie(){ exit 7; }\n"
                + node_policy
            )
            for fresh, opt_in, expected in (
                ("0", "0", ["APPLY"]),
                ("1", "1", ["APPLY"]),
                ("1", "0", []),
            ):
                log.write_text("")
                env = {
                    **os.environ,
                    "MOCK_NODE_HELPER": str(helper),
                    "MOCK_NODE_LOG": str(log),
                    "UPGRADE_EXISTING": fresh,
                    "AWG_SYSTEM_NODE_UPGRADE": opt_in,
                }
                result = subprocess.run(
                    ["bash", "-c", script],
                    env=env, text=True, capture_output=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(log.read_text().splitlines(), expected)

    def test_dc_system_node_preferred_and_old_upgrade_fallback(self):
        self.assertIn('system_node_ok(){', DC)
        self.assertIn('if system_node_ok; then\n    exec npx "${npm_args[@]}" "$DC_PACKAGE" remote', DC)
        self.assertIn('exec npm exec "${npm_args[@]}" --package="$DC_NODE_PACKAGE"', DC)
        self.assertIn('ExecStart=/usr/local/bin/awg-dc agent', DC_SERVICE)
        self.assertIn('User=%i', DC_SERVICE)
        self.assertNotIn('User=root', DC_SERVICE)

    def test_status_command_does_not_install(self):
        p = subprocess.run(["bash", str(SCRIPT), "status"], capture_output=True, text=True, timeout=5)
        self.assertIn("SYSTEM_NODE_", p.stdout + p.stderr)
        self.assertNotIn("apt-get", SYSTEM)
        self.assertNotIn("systemctl restart", SYSTEM)


if __name__ == "__main__":
    unittest.main()
