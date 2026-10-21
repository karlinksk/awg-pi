#!/usr/bin/env python3
"""Rootless confirmation tests: engine separation and two-probe Mihomo health."""
import importlib.util
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock
import yaml

SRC=Path(__file__).resolve().parents[1]/"src/awg-mihomo-pool.py"
spec=importlib.util.spec_from_file_location("confirmed_mihomo_pool",SRC)
pool=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pool)

NATIVE={"name":"Native A","type":"ss","server":"192.0.2.4","port":443,
        "cipher":"aes-128-gcm","password":"synthetic-fixture-only"}
XRAY={"name":"Other Xray","type":"vless","network":"xhttp","tls":True,
      "server":"192.0.2.5","port":443,"reality-opts":{"public-key":"A"*43}}

class ConfirmedHealth(unittest.TestCase):
    def run_scan(self,profiles,answers):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        provider=root/"subscription.yaml"
        live=root/"live.json"
        provider.write_text(yaml.safe_dump({"proxies":profiles}))
        proc=mock.Mock()
        proc.poll.return_value=None
        calls=iter(answers)
        def result(*args,**kwargs):
            return next(calls)
        names={f"AWG-PROBE-{i:06d}" for i,n in enumerate(profiles,1)
               if not pool.uses_xray_sidecar(n)}
        with mock.patch.multiple(pool,LIVE_PROVIDER=provider,LIVE_POOL=live,
                                 LIVE_POOL_SNAPSHOT=root/"lkg.gz",
                                 MIHOMO_BIN="/usr/local/bin/mihomo"),\
             mock.patch.object(pool.os.path,"isfile",return_value=True),\
             mock.patch.object(pool.os,"access",return_value=True),\
             mock.patch.object(pool,"read_protocol_policy",return_value="all"),\
             mock.patch.object(pool,"choose_free_port",side_effect=[17880,19090]),\
             mock.patch.object(pool.subprocess,"Popen",return_value=proc) as popen,\
             mock.patch.object(pool,"wait_controller"),\
             mock.patch.object(pool,"wait_probe_inventory",return_value=names),\
             mock.patch.object(pool,"probe_delay",side_effect=result) as probe,\
             mock.patch.object(pool.time,"sleep") as delay:
            try:
                outcome=pool.scan("live",geo=False)
                code=0
            except SystemExit as exc:
                outcome=None
                code=exc.code
        return root,live,code,outcome,popen,probe,delay

    def test_first_failure_then_success_is_ok(self):
        root,live,code,payload,popen,probe,delay=self.run_scan(
            [NATIVE],[(False,None,"timeout"),(True,125,"")])
        self.assertEqual(code,0)
        self.assertTrue(payload["nodes"][0]["healthy"])
        self.assertEqual(payload["nodes"][0]["delay_ms"],125)
        self.assertEqual(probe.call_count,2)
        delay.assert_called_once_with(15)

    def test_two_failures_are_recorded_without_replacing_last_good_pool(self):
        root,live,code,payload,popen,probe,delay=self.run_scan(
            [NATIVE],[(False,None,"timeout"),(False,None,"timeout")])
        self.assertEqual(code,3)
        self.assertEqual(probe.call_count,2)
        latest=json.loads((root/"live-lastscan.json").read_text())
        self.assertIs(latest["nodes"][0]["healthy"],False)
        self.assertIn("confirmed-",latest["nodes"][0]["error"])

    def test_mixed_subscription_tests_native_only(self):
        root,live,code,payload,popen,probe,delay=self.run_scan(
            [XRAY,NATIVE],[(True,91,"")])
        self.assertEqual(code,0)
        self.assertEqual(payload["source_total"],2)
        self.assertEqual(payload["nodes"][0]["engine"],"XRAY")
        self.assertIsNone(payload["nodes"][0]["healthy"])
        self.assertEqual(payload["nodes"][1]["engine"],"MIHOMO")
        self.assertTrue(payload["nodes"][1]["healthy"])
        self.assertEqual(probe.call_count,1)

    def test_only_xray_is_valid_and_never_launches_shadow_mihomo(self):
        root,live,code,payload,popen,probe,delay=self.run_scan([XRAY],[])
        self.assertEqual(code,0)
        self.assertEqual(payload["total"],1)
        self.assertEqual(payload["healthy"],0)
        self.assertIsNone(payload["nodes"][0]["healthy"])
        popen.assert_not_called()
        probe.assert_not_called()

if __name__=="__main__":
    unittest.main()
