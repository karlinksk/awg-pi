"""Profile identity still guards selection; website access does not."""
import importlib.util,sys,unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("identity_preflight",ROOT/"src/awg-xray-manual-switch.py")
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
class Identity(unittest.TestCase):
    def test_exact_profile_accepts_without_network(self):
        info={"candidate":"node","sha":"provider","fingerprint":"profile"}
        with mock.patch.object(m,"source_node",return_value=("node","provider","profile")), mock.patch.object(m.subprocess,"run",side_effect=AssertionError("no external probes")), mock.patch.object(m.socket,"create_connection",side_effect=AssertionError("no external probes")):
            m.preflight_xray(2,info)
    def test_rotated_provider_rejected(self):self.reject(("node","rotated","profile"))
    def test_changed_credentials_rejected(self):self.reject(("node","provider","changed"))
    def test_changed_name_rejected(self):self.reject(("renamed","provider","profile"))
    def reject(self,value):
        with mock.patch.object(m,"source_node",return_value=value),self.assertRaisesRegex(RuntimeError,"PROVIDER_CHANGED_BEFORE_SELECTION"):
            m.preflight_xray(2,{"candidate":"node","sha":"provider","fingerprint":"profile"})
    def test_invalid_source_cannot_arm_transaction(self):
        with mock.patch.object(m,"source_node",side_effect=RuntimeError("INVALID_PROFILE")),mock.patch.object(m,"save_snap") as save,self.assertRaisesRegex(RuntimeError,"INVALID_PROFILE"):
            m.preflight_xray(2,{})
        save.assert_not_called()
    def test_auto_backend_has_no_website_preflight(self):
        s=(ROOT/"src/awg-xray-live-backend.py").read_text();body=s.split("    def preflight(self,failed,candidate):",1)[1].split("    def arm_watchdog(self):",1)[0]
        self.assertNotIn("fresh_exact_xray_https",body);self.assertNotIn("NODE_BASIC_NETWORK",body)
        self.assertIn('fields.get("NODE_PROVIDER_SHA256")!=self.provider_hash',body)
        self.assertIn("mod.validate(node)",body)
