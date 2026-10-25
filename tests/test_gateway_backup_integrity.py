"""Fail-closed gateway backup tests: synthetic filesystem, never the real host.

Extracts exactly the versioned backup_gateway() shell function. Only inside this
test process, switches its tar root to a scratch directory and omits root chown.
The upstream source/installed host are not modified.
"""
import os
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPDATE = (ROOT / "src/awg-update").read_text()
BACKUP = "backup_gateway(){\n" + UPDATE.split("backup_gateway(){\n", 1)[1].split(
    "\nrestore_gateway(){", 1)[0]
assert "tar -C / -czf" in BACKUP
assert "install -d -o root -g root -m 0700" in BACKUP

MOCK_BACKUP = (
    BACKUP
    .replace('tar -C / -czf', 'tar -C "$MOCK_ROOT" -czf')
    .replace('install -d -o root -g root -m 0700',
             'install -d -m 0700')
    .replace('[[ ! -e "/$target" ]]', '[[ ! -e "$MOCK_ROOT/$target" ]]')
    .replace('[[ -e "/$target" || -L "/$target" ]]',
             '[[ -e "$MOCK_ROOT/$target" || -L "$MOCK_ROOT/$target" ]]')
)
MOCK_FUNCTIONS = r"""
systemctl(){ printf 'disabled\n'; return 1; }
tar(){
  if [[ "$MOCK_TAR_FAIL" == 1 && "$1" == -C ]]; then
    return 2
  fi
  if [[ "$MOCK_VERIFY_FAIL" == 1 && "$1" == -tzf ]]; then
    return 2
  fi
  command tar "$@"
}
"""

class GatewayBackupIntegrity(unittest.TestCase):
    def invoke(self, *, missing_required=False, missing_optional=False,
               unreadable=False, tar_fail=False, verify_fail=False):
        with tempfile.TemporaryDirectory(prefix="awg-test-backup-") as temp:
            root = Path(temp) / "fixture"
            backup_dir = Path(temp) / "private-backup"
            required = [root / "etc/awg-pbr", root / "usr/local/sbin/awg-route",
                        root / "usr/local/sbin/awg-update"]
            required[0].mkdir(parents=True)
            for file in required[1:]:
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("#!/bin/sh\nexit 0\n")
            (required[0] / "mode").write_text("selective\n")
            optional = root / "etc/amnezia/amneziawg/awg0.conf"
            if not missing_optional:
                optional.parent.mkdir(parents=True)
                optional.write_text("PRIVATE_SENTINEL\n")
            if missing_required:
                required[2].unlink()
            if unreadable and optional.exists():
                optional.chmod(0)
            env = dict(os.environ, MOCK_ROOT=str(root), MOCK_OUT=str(backup_dir),
                       MOCK_TAR_FAIL=str(int(tar_fail)),
                       MOCK_VERIFY_FAIL=str(int(verify_fail)))
            command = ("set -Eeuo pipefail\n" + MOCK_FUNCTIONS + "\n"
                       + MOCK_BACKUP + "\nbackup_gateway \"$MOCK_OUT\"\n")
            p = subprocess.run(["bash", "-c", command], env=env,
                               text=True, capture_output=True, timeout=12)
            archive = backup_dir / "gateway-state.tgz"
            archive_exists = archive.is_file()
            members = []
            if archive_exists:
                with tarfile.open(archive, "r:gz") as f:
                    members = f.getnames()
            mode = stat.S_IMODE(archive.stat().st_mode) if archive_exists else None
            directory_mode = stat.S_IMODE(backup_dir.stat().st_mode) if backup_dir.exists() else None
            return p, members, archive_exists, mode, directory_mode, list(
                backup_dir.glob(".gateway-state.*")) if backup_dir.exists() else []

    def test_valid_backup_has_required_content_and_private_permissions(self):
        p, members, exists, mode, dir_mode, tempfiles = self.invoke()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(exists)
        self.assertEqual(mode, 0o600)
        self.assertEqual(dir_mode, 0o700)
        self.assertIn("etc/awg-pbr/mode", members)
        self.assertIn("usr/local/sbin/awg-route", members)
        self.assertIn("usr/local/sbin/awg-update", members)
        self.assertIn("etc/amnezia/amneziawg/awg0.conf", members)
        self.assertEqual(tempfiles, [])
        self.assertIn("GATEWAY_BACKUP=VERIFIED", p.stdout)
        self.assertNotIn("PRIVATE_SENTINEL", p.stdout + p.stderr)

    def test_missing_optional_profile_still_allows_mihomo_only_host(self):
        p, members, exists, _, _, _ = self.invoke(missing_optional=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(exists)
        self.assertNotIn("etc/amnezia/amneziawg/awg0.conf", members)

    def test_missing_required_fails_closed_before_archiving(self):
        p, _, exists, _, _, _ = self.invoke(missing_required=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(exists)
        self.assertIn("GATEWAY_BACKUP_ERROR=REQUIRED_PATH_MISSING", p.stderr)

    def test_tar_creation_error_cannot_publish_backup(self):
        p, _, exists, _, _, leftover = self.invoke(tar_fail=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(exists)
        self.assertEqual(leftover, [])
        self.assertIn("GATEWAY_BACKUP_ERROR=ARCHIVE_CREATE_FAILED", p.stderr)

    def test_archive_integrity_error_cannot_publish_backup(self):
        p, _, exists, _, _, leftover = self.invoke(verify_fail=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(exists)
        self.assertEqual(leftover, [])
        self.assertIn("GATEWAY_BACKUP_ERROR=ARCHIVE_INTEGRITY_FAILED", p.stderr)

    def test_unreadable_present_profile_is_not_silently_skipped(self):
        if os.geteuid() == 0:
            self.skipTest("requires unprivileged runner for unreadable-file assertion")
        p, _, exists, _, _, _ = self.invoke(unreadable=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(exists)
        self.assertIn("GATEWAY_BACKUP_ERROR=ARCHIVE_CREATE_FAILED", p.stderr)

    def test_no_ignored_read_failures_or_silent_tar_errors(self):
        self.assertNotIn("--ignore-failed-read", BACKUP)
        self.assertNotIn("2>/dev/null || true\n  chmod 600", BACKUP)
        self.assertIn("GATEWAY_BACKUP_ERROR=ARCHIVE_CREATE_FAILED", BACKUP)
        self.assertIn('mv -fT -- "$archive_tmp" "$dir/gateway-state.tgz"', BACKUP)
        self.assertIn("GATEWAY_BACKUP=VERIFIED", BACKUP)

    def test_optional_xray_adapter_in_backup_and_rollback(self):
        for name in ("etc/systemd/system/awg-xray-vless.service","var/lib/awg-pbr/xray-vless","usr/local/bin/awg-xray-vless-core","usr/local/sbin/awg-xray-install","usr/local/sbin/awg-xray-vless"):
            self.assertIn(name, BACKUP)
        self.assertIn("awg-xray-vless.service", UPDATE)
        self.assertIn("rm -rf /etc/awg-pbr /var/lib/awg-pbr/xray-vless", UPDATE)

    def test_explicit_backup_command_does_not_invoke_upgrade(self):
        self.assertIn("  backup)\n", UPDATE)
        self.assertIn('manual_backup="$(mktemp -d', UPDATE)
        self.assertIn('if backup_gateway "$manual_backup"; then', UPDATE)
        self.assertIn('GATEWAY_BACKUP_ARCHIVE=', UPDATE)

if __name__ == "__main__":
    unittest.main()
