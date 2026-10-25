"""Local readiness never masquerades as external HTTPS success."""
import importlib.util,sys,unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("manual_runtime",ROOT/"src/awg-xray-manual-switch.py")
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
class Runtime(unittest.TestCase):
    def test_ready_uses_only_local_interface_and_controller(self):
        with mock.patch.object(m,"unit_active",return_value=True),mock.patch.object(m,"cmd") as cmd,mock.patch.object(m,"controller",return_value={"now":"chosen"}):
            self.assertTrue(m.tun_runtime_ready())
        cmd.assert_called_once_with("ip","link","show","dev","mihomo0",timeout=4)
    def test_stopped_service_rejected(self):
        with mock.patch.object(m,"unit_active",return_value=False),mock.patch.object(m,"cmd") as cmd:
            self.assertFalse(m.tun_runtime_ready())
        cmd.assert_not_called()
    def test_missing_interface_rejected(self):
        with mock.patch.object(m,"unit_active",return_value=True),mock.patch.object(m,"cmd",side_effect=RuntimeError("IF_DOWN")):
            self.assertFalse(m.tun_runtime_ready())
    def test_missing_selection_rejected(self):
        with mock.patch.object(m,"unit_active",return_value=True),mock.patch.object(m,"cmd"),mock.patch.object(m,"controller",return_value={}):
            self.assertFalse(m.tun_runtime_ready())
    def test_route_timeout_retains_failure(self):
        with mock.patch.object(m,"routing_ok",return_value=False),mock.patch.object(m.time,"monotonic",side_effect=[0,21]),self.assertRaisesRegex(RuntimeError,"NATIVE_ROUTING_NOT_RESTORED"):
            m.native_runtime_proof()
    def test_local_ready_does_not_start_external_probe(self):
        with mock.patch.object(m,"routing_ok",return_value=True),mock.patch.object(m,"tun_runtime_ready",return_value=True),mock.patch.object(m.subprocess,"run",side_effect=AssertionError("no HTTPS")):
            m.native_runtime_proof()
    def test_receipt_explicit_about_unchecked_connectivity(self):
        src=(ROOT/"src/awg-xray-manual-switch.py").read_text()
        self.assertIn("XRAY_MANUAL_RUNTIME=READY_EXTERNAL_CONNECTIVITY_NOT_TESTED",src)
        self.assertNotIn("XRAY_MANUAL_TUN=VERIFIED",src)
    def test_both_engines_keep_rollback(self):
        src=(ROOT/"src/awg-xray-manual-switch.py").read_text()
        self.assertIn("restore(path,state)",src);self.assertIn("restore_native(path,state)",src)
        self.assertIn("WATCHDOG_NOT_ARMED",src)

    def test_dead_selected_sidecar_is_not_hidden_by_live_mihomo(self):
        with mock.patch.object(m,"unit_active",side_effect=lambda u:u!=m.XRAY),mock.patch.object(m,"cmd"),mock.patch.object(m,"controller",return_value={"now":m.ALIAS}):
            self.assertFalse(m.tun_runtime_ready())
    def test_dormant_stopped_sidecar_does_not_reject_native(self):
        with mock.patch.object(m,"unit_active",side_effect=lambda u:u!=m.XRAY),mock.patch.object(m,"cmd"),mock.patch.object(m,"controller",return_value={"now":"Native"}):
            self.assertTrue(m.tun_runtime_ready())
