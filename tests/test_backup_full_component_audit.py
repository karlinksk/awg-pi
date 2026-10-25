"""Rootless, synthetic tests for read-only gateway backup verifier."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "gateway_backup_verifier", ROOT / "scripts/awg-backup-verify.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

class FullComponentAuditTests(unittest.TestCase):
    def make(self, d, *, missing=None, missing_payload=False):
        archive = Path(d) / "gateway-state.tgz"
        required = mod.REQUIRED - set(missing or [])
        with tarfile.open(archive, "w:gz") as tf:
            for item in sorted(required):
                info = tarfile.TarInfo(item)
                info.type = tarfile.DIRTYPE
                info.mode = 0o700
                tf.addfile(info)
            if not missing_payload:
                for name in ("var/lib/awg-pbr/hot-pool/continuity/metadata.json",
                             "var/lib/awg-pbr/stage18-runtime/manifest.sha256"):
                    payload = b"fixture-only"
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    tf.addfile(info, io.BytesIO(payload))
        (Path(d) / "hot-pool-timer-state").write_text("enabled\n")
        archive.chmod(0o600)
        Path(d).chmod(0o700)
        return archive

    def show(self, archive):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mod.verify(archive, enforce_owner=False)
        return code, out.getvalue()

    def test_full_component_and_timer_pass(self):
        with tempfile.TemporaryDirectory() as d:
            archive = self.make(d)
            code, output = self.show(archive)
            self.assertEqual(code, 0, output)
            self.assertIn("BACKUP_REQUIRED=31/31", output)
            self.assertIn("BACKUP_CACHE_PAYLOAD=PASS", output)
            self.assertIn("BACKUP_HOT_POOL_TIMER_STATE=PASS", output)
            self.assertIn("BACKUP_COMPLETE_COMPONENT_CHECK=PASS", output)

    def test_missing_hot_pool_binary_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            archive = self.make(d, missing={"usr/local/sbin/awg-mihomo-hot-pool"})
            code, out = self.show(archive)
            self.assertNotEqual(code, 0)
            self.assertIn("MISSING_REQUIRED_PATH=usr/local/sbin/awg-mihomo-hot-pool", out)

    def test_missing_media_cache_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            archive = self.make(d, missing_payload=True)
            code, out = self.show(archive)
            self.assertNotEqual(code, 0)
            self.assertIn("BACKUP_CACHE_PAYLOAD=FAIL", out)

    def test_missing_timer_state_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            archive = self.make(d)
            (Path(d) / "hot-pool-timer-state").unlink()
            code, out = self.show(archive)
            self.assertNotEqual(code, 0)
            self.assertIn("BACKUP_HOT_POOL_TIMER_STATE=FAIL", out)

    def test_corrupt_gzip_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            archive = self.make(d)
            contents = archive.read_bytes()
            archive.write_bytes(contents[:max(1, len(contents) // 2)])
            code, out = self.show(archive)
            self.assertNotEqual(code, 0)
            self.assertIn("BACKUP_ARCHIVE_STREAM=FAIL", out)

    def test_every_present_installer_manifest_path_is_compared(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("etc/awg-pbr", "usr/local/sbin/awg-route"):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture")
            missing, errors, total = mod.inventory(
                {"etc/awg-pbr"}, ROOT / "src/awg-update", live_root=root)
            self.assertEqual(errors, [])
            self.assertEqual(total, 2)
            self.assertEqual(missing, ["usr/local/sbin/awg-route"])

    def test_manifest_source_rejected_when_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "unknown"
            source.write_text("not a backup manifest")
            missing, errors, count = mod.inventory(set(), source)
            self.assertEqual(missing, [])
            self.assertEqual(errors, ["MANIFEST_SOURCE_INVALID"])
            self.assertEqual(count, 0)

    def test_rootless_fixture_without_changing_system(self):
        with tempfile.TemporaryDirectory() as d:
            archive = self.make(d)
            summary = mod.evaluate(archive, enforce_owner=False)
            self.assertFalse(summary["missing"])
            self.assertFalse(summary["subtrees"])
            self.assertFalse(summary["error"])
            self.assertEqual(summary["files"], 2)
            self.assertEqual(summary["bytes"], len(b"fixture-only")*2)

if __name__ == "__main__":
    unittest.main()
