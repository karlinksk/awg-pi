"""Offline tests for sampled endpoint selection (never contact endpoints)."""
import importlib.util
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / "research" / "mihomo-endpoint-reprobe.py"
spec = importlib.util.spec_from_file_location("reprobe", FILE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SampleTests(unittest.TestCase):
    def test_unique_endpoints_and_balanced_baselines(self):
        source, state = [], []
        for proto in m.PROTOCOLS:
            for j in range(7):
                host = f"{proto}-{j}.example.invalid"
                source.append({"name": f"x{j}", "type": proto, "server": host, "port": 443})
                state.append({"type": proto, "server": host, "port": 443, "healthy": j == 0})
        selected = m.choose(source, state)
        self.assertEqual(len(selected), 25)
        endpoints = {(n["host"], n["port"]) for n in selected}
        self.assertEqual(len(endpoints), 25)
        for proto in m.PROTOCOLS:
            self.assertEqual(sum(x["kind"] == proto and x["baseline"] == "failed" for x in selected), 4)
            self.assertEqual(sum(x["kind"] == proto and x["baseline"] == "healthy" for x in selected), 1)

    def test_no_false_direct_for_private_ip(self):
        s, _ = m.endpoint_preflight({"host": "127.0.0.1", "port": 443})
        self.assertEqual(s, "non_public_endpoint")

    def test_invalid_endpoint_excluded(self):
        source = [{"type": "vless", "server": "example.invalid", "port": 70000}]
        state = [{"type": "vless", "server": "example.invalid", "port": 70000, "healthy": False}]
        self.assertEqual(m.choose(source, state), [])


if __name__ == "__main__":
    unittest.main()
