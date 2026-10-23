"""Mocked tests: repair private Telegram pairing without token disclosure."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / "scripts" / "awg-notify-pair-repair.py"
spec = importlib.util.spec_from_file_location("awg_notify_pair_repair", PATH)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class RepairTests(unittest.TestCase):
    token = "12345678:" + "A" * 35

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awg-pair-repair-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "telegram.json"
        self.path.write_text(json.dumps({"token": self.token, "chat_id": "1"}))
        self.path.chmod(0o600)

    def test_private_challenge_exact_only(self):
        updates = [
            {"message": {"text": "/pair challenge", "chat": {"id": 123, "type": "group"},
                         "from": {"id": 123}}},
            {"message": {"text": "/pair fake", "chat": {"id": 456, "type": "private"},
                         "from": {"id": 456}}},
            {"message": {"text": "/pair challenge", "chat": {"id": 789, "type": "private"},
                         "from": {"id": 111}}},
            {"message": {"text": "/pair challenge", "chat": {"id": 12345, "type": "private"},
                         "from": {"id": 12345}}},
        ]
        self.assertEqual(repair.find_private_challenge(updates, "challenge"), 12345)
        self.assertIsNone(repair.find_private_challenge(updates, "other"), None)

    def test_multiple_challenge_users_rejected(self):
        updates = [
            {"message": {"text": "/pair c", "chat": {"id": uid, "type": "private"},
                         "from": {"id": uid}}}
            for uid in (111, 222)]
        with self.assertRaises(ValueError):
            repair.find_private_challenge(updates, "c")

    def test_secure_atomic_replacement(self):
        repair.save_verified_chat(self.token, "1", 123456,
                                  self.path, owner_uid=os.getuid())
        obj = json.loads(self.path.read_text())
        self.assertEqual(obj, {"token": self.token, "chat_id": "123456"})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.path.with_name("telegram.json.pair-new").exists())

    def test_refuses_concurrent_change(self):
        with self.assertRaises(ValueError):
            repair.save_verified_chat(self.token, "100", 123,
                                      self.path, owner_uid=os.getuid())
        self.assertEqual(json.loads(self.path.read_text())["chat_id"], "1")

    def test_refuses_unsafe_secret(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            repair.save_verified_chat(self.token, "1", 123,
                                      self.path, owner_uid=os.getuid())

    def test_refuses_nonprivate_or_negative(self):
        for cid in (-1, 0, "12", True):
            with self.assertRaises(ValueError):
                repair.save_verified_chat(self.token, "1", cid,
                                          self.path, owner_uid=os.getuid())

    def test_curl_token_only_stdin(self):
        def fake_run(argv, **kwargs):
            self.assertNotIn(self.token, " ".join(argv))
            self.assertIn(self.token, kwargs["input"])
            self.assertIn("if!mihomo0", argv)
            self.assertNotIn("offset", kwargs["input"])
            return mock.Mock(returncode=0, stdout='{"ok":true,"result":[]}\n200')
        with mock.patch.object(repair.subprocess, "run", side_effect=fake_run):
            self.assertEqual(repair.telegram_request(self.token, "mihomo0", "getUpdates"),
                             ([], 200))

    def test_invalid_method_rejected(self):
        with self.assertRaises(ValueError):
            repair.telegram_request(self.token, "awg0", "deleteWebhook")
        with self.assertRaises(ValueError):
            repair.telegram_request(self.token, "eth99", "getMe")


if __name__ == "__main__":
    unittest.main()
