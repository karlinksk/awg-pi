#!/usr/bin/env python3
"""Rootless security regression for opt-in Desktop Commander diagnostics."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "src" / "awg-dc-admin.py"
ACCESS = ROOT / "src" / "awg-dc-admin-access"
INSTALL = ROOT / "install.sh"


def module():
    # Does not call the helper's __main__ entry point.
    spec = importlib.util.spec_from_file_location("awg_dc_admin_test", ADMIN)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


class DCLimitedAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = module()

    def test_root_required(self):
        with mock.patch.object(self.helper.os, "geteuid", return_value=1000):
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(self.helper.main(["status"]), 2)
        self.assertIn("ROOT_REQUIRED", errors.getvalue())

    def test_strict_argv_allowlist_no_shell_or_chaining(self):
        with mock.patch.object(self.helper.os, "geteuid", return_value=0):
            for argv in ([], ["reboot"], ["status", "extra"], ["stage18;id"],
                         ["network", "--table", "main"], ["services", "/etc/shadow"]):
                with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(self.helper.main(argv), 2)
        self.assertEqual(set(self.helper.HANDLERS), {
            "status", "stage18", "services", "network", "versions",
        })

    def test_subprocess_hardening(self):
        fake = subprocess.CompletedProcess(["/usr/bin/systemctl"], 0, "active\n", "")
        with mock.patch.object(self.helper.subprocess, "run", return_value=fake) as call:
            self.assertEqual(self.helper.command(["/usr/bin/systemctl", "is-active", "ssh.service"]), "active")
        self.assertEqual(call.call_args.kwargs["env"], self.helper.ENV)
        self.assertNotIn("shell", call.call_args.kwargs)
        self.assertIsNotNone(call.call_args.kwargs["timeout"])

    def test_output_sanitized(self):
        bad = subprocess.CompletedProcess(["bin"], 0, "\x1b[31mPASS\x1b[0m\n", "")
        with mock.patch.object(self.helper.subprocess, "run", return_value=bad):
            self.assertNotIn("\x1b", self.helper.command(["/usr/bin/systemctl"]))

    def test_stage18_rejects_missing_cache_without_credential_leak(self):
        with mock.patch.object(self.helper, "CACHE", Path("/nonexistent/awg-dc-stage18")):
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(self.helper.stage18(), 1)
        self.assertEqual(stdout.getvalue().strip(), "AWG_DC_ADMIN_STAGE18=FAIL")

    def test_status_does_not_dump_profile_content(self):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(self.helper.status(), 0)
        self.assertIn("AWG_DC_ADMIN_SCOPE=READ_ONLY", stdout.getvalue())
        self.assertNotIn("PrivateKey", stdout.getvalue())
        self.assertNotIn("provider.env", stdout.getvalue())

    def test_policy_script_syntax_and_gate_conditions(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(ACCESS)], capture_output=True).returncode, 0)
        src = ACCESS.read_text()
        self.assertIn("PAIRING_REQUIRED", src)
        self.assertIn("/usr/sbin/visudo -cf", src)
        self.assertIn("FOREIGN_POLICY_REFUSED", src)
        self.assertIn("mv -nT", src)
        self.assertIn("chmod 0440", src)
        self.assertIn("ALL=(root) NOPASSWD:", src)
        for action in ("status", "services", "network", "versions", "stage18"):
            self.assertIn(action, src)
        self.assertNotIn("NOPASSWD: ALL", src)
        self.assertNotIn("/bin/bash", src)

    def test_sudo_global_timestamp_not_reusable_by_dc(self):
        src = ACCESS.read_text()
        self.assertIn("Defaults:%s timestamp_type=tty, timestamp_timeout=0", src)
        self.assertIn("runuser -u \"$USER_NAME\" -- /usr/bin/sudo -K", src)
        self.assertIn("LEGACY_TIMESTAMP_UNSAFE", src)
        self.assertIn("policy_text_v1", src)
        self.assertIn("POLICY_CHANGED_DURING_UPGRADE", src)
        self.assertIn("known_policy || fail FOREIGN_POLICY_REFUSED", src)

    def test_real_sudoers_policy_syntax(self):
        import os
        import tempfile
        src = ACCESS.read_text()
        start = src.index("policy_text_v1(){")
        end = src.index('[[ ! -L "$POLICY" ]]')
        definitions = src[start:end]
        prelude = (
            "MARKER='# AWG-PI-DC-ADMIN READONLY V2'\n"
            "LEGACY_MARKER='# AWG-PI-DC-ADMIN READONLY V1'\n"
            "HELPER=/usr/local/sbin/awg-dc-admin\n"
            "USER_NAME=karlinks\n"
        )
        for fn, legacy in (("policy_text", False), ("policy_text_v1", True)):
            with self.subTest(policy=fn):
                result = subprocess.run(
                    ["bash", "-c", prelude + definitions + "\n" + fn],
                    capture_output=True, text=True, check=True,
                )
                self.assertIn("NOPASSWD:", result.stdout)
                if legacy:
                    self.assertNotIn("timestamp_timeout=0", result.stdout)
                else:
                    self.assertIn("Defaults:karlinks timestamp_type=tty, timestamp_timeout=0", result.stdout)
                with tempfile.TemporaryDirectory() as tmpdir:
                    filename = Path(tmpdir) / "sudoers-check"
                    filename.write_text(result.stdout)
                    checked = subprocess.run(
                        ["/usr/sbin/visudo", "-cf", str(filename)],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_installer_only_installs_no_activation(self):
        src = INSTALL.read_text()
        self.assertIn("install_project_python_helper src/awg-dc-admin.py", src)
        self.assertIn("install_project_helper src/awg-dc-admin-access", src)
        self.assertNotIn("awg-dc-admin-access enable", src)
        self.assertNotIn("set_config_value", src)
        self.assertEqual(subprocess.run(["bash", "-n", str(INSTALL)], capture_output=True).returncode, 0)

    def test_release_contract_paths_are_constant(self):
        txt = ADMIN.read_text()
        self.assertIn("stage18-runtime", txt)
        self.assertIn("sha256", txt)
        self.assertNotIn("subprocess.call(", txt)
        self.assertNotIn("os.system(", txt)
        self.assertNotIn("shell=True", txt)
        self.assertNotIn("eval(", txt)
        self.assertNotIn("exec(", txt)


if __name__ == "__main__":
    unittest.main()
