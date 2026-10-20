import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

P=pathlib.Path(__file__).resolve().parents[1]/"src/awg-xray-live-backend.py"
spec=importlib.util.spec_from_file_location("xray_auto_transit_degraded",P)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

class TransitDegraded(unittest.TestCase):
    def test_safe_exhaustion_and_rejections(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            mode=root/"mode";mode.write_text("transit")
            policy=root/"policy";policy.write_text("auto")
            status="Transit guard: SAFE\nTransit policy rule: INACTIVE\nTransit VPN table: READY"
            def run(*args,**kwargs):
                if args[-1]=="get":return "mihomo"
                if args[-2:]==("check","awg"):return "healthy"
                if args[-1]=="status":return status
                if args[0]=="ip":return "default dev mihomo0 scope link"
                raise AssertionError(args)
            services={"ssh.service","dnsmasq.service","awg-pbr-health.service","awg-quick@awg0.service"}
            with mock.patch.object(m,"MODE",mode),mock.patch.object(m,"NODE_POLICY_MODE",policy),mock.patch.object(m.socket,"gethostname",return_value="awg-upgrade"),mock.patch.dict(m.os.environ,{"MIHOMO_XRAY_AUTO_FAILOVER_CANARY":"1"}),mock.patch.object(m,"run",side_effect=run),mock.patch.object(m,"active",side_effect=lambda u:u in services):
                self.assertTrue(m.verified_degraded_auto_transit_baseline())
                for changed in ("Transit guard: UNSAFE","Transit policy rule: ACTIVE"):
                    with self.subTest(changed=changed),mock.patch.object(m,"run",side_effect=lambda *a,**k: changed if a[-1]=="status" else run(*a,**k)):
                        self.assertFalse(m.verified_degraded_auto_transit_baseline())
                with mock.patch.object(m,"run",side_effect=lambda *a,**k: "default dev awg0" if a[0]=="ip" else run(*a,**k)):
                    self.assertFalse(m.verified_degraded_auto_transit_baseline())
                with mock.patch.object(m,"active",side_effect=lambda u:u in services or u==m.MIHOMO):
                    self.assertFalse(m.verified_degraded_auto_transit_baseline())
                with mock.patch.dict(m.os.environ,{"MIHOMO_XRAY_AUTO_FAILOVER_CANARY":"0"}):
                    self.assertFalse(m.verified_degraded_auto_transit_baseline())
                policy.write_text("manual")
                self.assertFalse(m.verified_degraded_auto_transit_baseline())
if __name__=="__main__":unittest.main()
