"""Pure unit tests of the AWG DPI namespace research harness (no sudo/network)."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "research" / "awg-dpi-netns-sandbox.py"
spec = importlib.util.spec_from_file_location("awg_dpi_netns_sandbox", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SandboxPureTests(unittest.TestCase):
    def test_marker_identity_check(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "owner"
            marker.mkdir()
            (marker / "owner").write_text("unexpected owner\n")
            with patch.object(m, "MARKER", marker):
                self.assertFalse(m.owned())
                (marker / "owner").write_text(f"{m.NS}\n{m.IF}\n{m.PARENT}\n")
                self.assertTrue(m.owned())

    def test_reject_unowned_namespace(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(m, "MARKER", Path(d) / "absent"):
                with patch.object(m, "ns_exists", return_value=True):
                    with patch.object(m, "host_interface_exists", return_value=False):
                        with self.assertRaisesRegex(RuntimeError, "unsafe_leftover"):
                            m.cleanup()

    def test_known_dhcp_lease_stays_inside_namespace(self):
        invoked = []
        def fake_call(args, **kw):
            invoked.append(args)
            if "udhcpc" in args:
                return subprocess.CompletedProcess(
                    args, 0, "", "udhcpc: lease of 192.168.112.25 obtained from "
                                "192.168.112.1, lease time 1800\n")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(m, "call", side_effect=fake_call):
            address = m.dhcp()
        self.assertEqual(address, "192.168.112.25")
        self.assertTrue(all(args[:3] == ["ip", "-n", m.NS] for args in invoked[1:]))
        self.assertIn("default", invoked[-1])

    def test_dhcp_rejects_production_address(self):
        def fake_call(args, **kw):
            return subprocess.CompletedProcess(
                args, 0, "", "udhcpc: lease of 192.168.112.34 obtained from "
                            "192.168.112.1, lease time 1800")
        with patch.object(m, "call", side_effect=fake_call):
            with self.assertRaisesRegex(RuntimeError, "wrong_lease"):
                m.dhcp()

    def test_dhcp_rejects_wrong_server(self):
        def fake_call(args, **kw):
            return subprocess.CompletedProcess(
                args, 0, "", "udhcpc: lease of 192.168.112.25 obtained from "
                            "192.168.112.99, lease time 1800")
        with patch.object(m, "call", side_effect=fake_call):
            with self.assertRaisesRegex(RuntimeError, "unexpected_dhcp_server"):
                m.dhcp()


if __name__ == "__main__":
    unittest.main()
