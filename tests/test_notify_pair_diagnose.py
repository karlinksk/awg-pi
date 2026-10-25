"""Pure mocked tests for privacy-preserving AWG Notify pairing diagnostic."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / "scripts" / "awg-notify-pair-diagnose.py"
spec = importlib.util.spec_from_file_location("awg_pair_diagnose", PATH)
diagnose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnose)


class PairDiagnosticsTests(unittest.TestCase):
    token = "12345678:" + "A" * 35

    def request(self, method, response, http=200):
        def fake_run(argv, **kwargs):
            cmd = " ".join(argv)
            self.assertNotIn(self.token, cmd)
            self.assertIn(self.token, kwargs["input"])
            self.assertIn(method, kwargs["input"])
            self.assertIn("if!mihomo0", argv)
            if method == "getUpdates":
                self.assertIn("limit=100", kwargs["input"])
                self.assertNotIn("offset=", kwargs["input"])
            return mock.Mock(returncode=0, stdout=response + "\n" + str(http))
        with mock.patch.object(diagnose.subprocess, "run", side_effect=fake_run):
            return diagnose.call_api(self.token, "mihomo0", method)

    def test_get_updates_reports_only_aggregates(self):
        body = ('{"ok":true,"result":['
                '{"message":{"chat":{"id":123,"type":"private"},"text":"/pair SECRET"}}]}')
        result = self.request("getUpdates", body)
        self.assertEqual(result["updates"], 1)
        self.assertEqual(result["private_pair_commands"], 1)
        self.assertNotIn("SECRET", str(result))
        self.assertNotIn("123", str(result))

    def test_webhook_detection_without_url_leak(self):
        body = '{"ok":true,"result":{"url":"https://example.com/private-hook"}}'
        result = self.request("getWebhookInfo", body)
        self.assertTrue(result["webhook_configured"])
        self.assertNotIn("example.com", str(result))

    def test_telegram_unauthorized_is_sanitized(self):
        body = '{"ok":false,"error_code":401,"description":"Sensitive secret text"}'
        result = self.request("getMe", body, http=401)
        self.assertEqual(result, {"result":"API_REJECTED","http":401,"error_code":401})
        self.assertNotIn("Sensitive", str(result))

    def test_transport_failure_no_raw_stderr(self):
        with mock.patch.object(diagnose.subprocess, "run",
                               return_value=mock.Mock(returncode=28, stdout="",
                                                      stderr="token123-private")):
            self.assertEqual(diagnose.call_api(self.token, "awg0", "getMe"),
                             {"result":"NO_CONNECTION"})

    def test_bad_methods_and_routes_rejected(self):
        with self.assertRaises(ValueError):
            diagnose.call_api(self.token, "eth99", "getMe")
        with self.assertRaises(ValueError):
            diagnose.call_api(self.token, "awg0", "deleteWebhook")


if __name__ == "__main__":
    unittest.main()
