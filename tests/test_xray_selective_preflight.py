#!/usr/bin/env python3
"""Safe contracts for Selective root-only passive Xray scanner."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"scripts/awg-xray-selective-auto-preflight.py"
spec=importlib.util.spec_from_file_location("xray_selective_preflight",PATH)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

class Preflight(unittest.TestCase):
    def test_inventory_prints_aggregates_not_names(self):
        lines=["UNIFIED_PROVIDER_COUNT=3",
               'NODE=1 ENGINE=MIHOMO PROTOCOL=hysteria2 TRANSPORT=udp BASIC_NETWORK=NETWORK_OK NAME="real name"',
               'NODE=2 ENGINE=XRAY PROTOCOL=vless TRANSPORT=xhttp BASIC_NETWORK=NETWORK_OK NAME="Secret Profile"',
               'NODE=3 ENGINE=XRAY PROTOCOL=vless TRANSPORT=grpc BASIC_NETWORK=NETWORK_FAIL NAME="Profile 3"']
        self.assertEqual(m.count_network(lines),{
            ("MIHOMO","NETWORK_OK"):1,("XRAY","NETWORK_OK"):1,("XRAY","NETWORK_FAIL"):1})
    def test_no_live_mutators_in_passive_script(self):
        source=PATH.read_text()
        for forbidden in ("systemctl restart","systemctl stop","awg-transport select",
                          "ip route replace","awg-xray-live-backend apply",
                          "nft add", "nft flush", "awg-mode-switch"):
            self.assertNotIn(forbidden,source)
        self.assertIn('("100","101")',source)
        self.assertIn('if fingerprint()!=baseline',source)
        self.assertIn('probe-vless-all',source)
    def test_fingerprint_rejects_non_testpi_before_any_scan(self):
        with mock.patch.object(m.os,"geteuid",return_value=1000):
            with self.assertRaisesRegex(RuntimeError,"TEST_PI_ROOT_ONLY"):
                m.fingerprint()
    def test_fingerprint_requires_selective_auto(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            mode=Path(d)/"mode";mode.write_text("transit")
            with (mock.patch.object(m.os,"geteuid",return_value=0),
                  mock.patch.object(m.socket,"gethostname",return_value="awg-upgrade"),
                  mock.patch.object(m,"MODE",mode)):
                with self.assertRaisesRegex(RuntimeError,"NOT_SELECTIVE"):
                    m.fingerprint()
    def test_scan_never_runs_without_good_preflight(self):
        with mock.patch.object(m,"fingerprint",side_effect=RuntimeError("NOT_SELECTIVE")):
            with mock.patch.object(m,"run") as command:
                with mock.patch.object(sys,"argv",["script","--scan"]):
                    with self.assertRaisesRegex(RuntimeError,"NOT_SELECTIVE"):
                        m.main()
                command.assert_not_called()
    def test_check_mode_only_reports_and_never_scans(self):
        with (mock.patch.object(m,"fingerprint",return_value=("aa","bb")),
              mock.patch.object(m,"safe_report"),
              mock.patch.object(m,"run") as command,
              mock.patch.object(sys,"argv",["script","--check"])):
            m.main()
            command.assert_not_called()

if __name__=="__main__":
    unittest.main()
