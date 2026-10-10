"""Unit tests for the passive Mihomo DPI audit (no network or privileged files)."""
import importlib.util
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "awg-mihomo-dpi-audit.py"
spec = importlib.util.spec_from_file_location("dpi_audit", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SnapshotAuditTests(unittest.TestCase):
    def test_ambiguous_error_not_called_dpi(self):
        for error in ("TimeoutError", "URLError", "SSLError"):
            self.assertEqual(module.failure_reason({"healthy": False, "error": error}),
                             "undifferentiated_probe_exception")

    def test_duplicates_are_aggregated_per_endpoint(self):
        data = {"scanned_at": 100, "nodes": [
            {"type": "vless", "server": "a", "port": 443, "healthy": True},
            {"type": "vless", "server": "a", "port": 443, "healthy": False, "error": "TimeoutError"},
            {"type": "trojan", "server": "b", "port": 443, "healthy": False, "error": "no-delay"},
            {"type": "ss", "server": "c", "port": 53, "healthy": True},
        ]}
        result = module.summarize(data, now=150)
        self.assertEqual((result["healthy_profiles"], result["failed_profiles"]), (2, 2))
        self.assertEqual(result["unique_host_ports"], 3)
        self.assertEqual(result["endpoints_mixed"], 1)
        self.assertEqual(result["endpoints_all_failed"], 1)
        self.assertEqual(result["endpoints_all_healthy"], 1)
        self.assertEqual(result["snapshot_age_seconds"], 50)
        self.assertEqual(result["dpi_confirmed"], 0)

    def test_sensitive_metadata_not_in_summary(self):
        data = {"nodes": [{
            "name": "DO-NOT-PRINT",
            "server": "secret-server.example",
            "port": 443,
            "password": "secret",
            "healthy": False,
            "error": "URLError",
        }]}
        report = json.dumps(module.summarize(data))
        for sensitive in ("DO-NOT-PRINT", "secret-server", "password"):
            self.assertNotIn(sensitive, report)

    def test_invalid_input_fails(self):
        with self.assertRaises(ValueError):
            module.summarize({"nodes": "not-a-list"})

    def test_http_errors_are_local_controller_errors(self):
        node = {"healthy": False, "error": "http-504"}
        self.assertEqual(module.failure_reason(node), "mihomo_api_http_error")


if __name__ == "__main__":
    unittest.main()
