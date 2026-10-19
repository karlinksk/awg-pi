#!/usr/bin/env python3
"""Rootless safety and installer tests for the dormant Xray Linux adapter."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/"src"/"awg-xray-live-backend.py"
spec=importlib.util.spec_from_file_location("xray_linux_backend",p)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class LinuxBackendTests(unittest.TestCase):
    def test_route_output_normalizes_whitespace(self):
        def good(*args,**kwargs):
            if args[-1]=="100":return "default    dev    mihomo0 scope link"
            return "default dev mihomo0 scope link"
        with mock.patch.object(m,"run",side_effect=good):
            self.assertTrue(m.routes_ok())
        with mock.patch.object(m,"run",return_value="default dev eth0"):
            self.assertFalse(m.routes_ok())
    def test_curl_probe_does_not_use_inherited_proxies(self):
        seen={}
        def fake(*args,**kwargs):
            seen["args"]=args;seen["env"]=kwargs["env"]
            return "401"
        with mock.patch.object(m,"run",side_effect=fake),mock.patch.dict(
            m.os.environ,{"HTTPS_PROXY":"http://attacker","http_proxy":"http://other"}):
            self.assertTrue(m.http_code(["--interface","mihomo0","--noproxy","*"]))
        self.assertEqual(seen["args"][1],"-q")
        self.assertIn("--interface",seen["args"])
        self.assertNotIn("HTTPS_PROXY",seen["env"])
        self.assertNotIn("http_proxy",seen["env"])
    def test_transit_quiesce_cleans_only_transaction_owned_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);mode=root/"mode";mode.write_text("transit")
            bridge=root/"bridge";bridge.write_text('[Service]\nEnvironment="MIHOMO_XRAY_VLESS_BRIDGE=1"\n')
            selected=root/"selected";selected.write_text("staged")
            events=[]
            def cmd(*args,**kw):
                events.append(args)
                if args[-1]=="status":
                    return "Transit guard: SAFE\nTransit policy rule: INACTIVE"
                return ""
            with mock.patch.object(m,"MODE",mode),mock.patch.object(m,"BRIDGE",bridge),\
                 mock.patch.object(m,"SELECTED",selected),mock.patch.object(m,"run",side_effect=cmd),\
                 mock.patch.object(m,"active",return_value=False):
                self.assertTrue(m.failclosed())
            self.assertFalse(bridge.exists());self.assertFalse(selected.exists())
            self.assertIn(("/usr/local/sbin/awg-transit-routing","disable"),events)
            self.assertIn(("systemctl","disable",m.XRAY),events)
    def test_quiesce_rejects_non_owned_override(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);mode=root/"mode";mode.write_text("transit")
            bridge=root/"bridge";bridge.write_text("DO_NOT_TOUCH")
            with mock.patch.object(m,"MODE",mode),mock.patch.object(m,"BRIDGE",bridge),\
                 mock.patch.object(m,"run",return_value=""):
                self.assertFalse(m.failclosed())
            self.assertTrue(bridge.exists())
    def test_cancelled_watchdog_never_quiesces_a_healthy_gateway(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);path=base/"xray-failover-1-2";path.mkdir()
            (path/"state.json").write_text(json.dumps({"state":"cancelled"}))
            with mock.patch.object(m,"BASE",base),mock.patch.object(m,"failclosed") as stop:
                m.watchdog(path)
            stop.assert_not_called()
    def test_watchdog_arm_state_quiesces_without_restoring_old_node(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);path=base/"xray-failover-1-2";path.mkdir()
            (path/"state.json").write_text(json.dumps({"state":"armed"}))
            with mock.patch.object(m,"BASE",base),mock.patch.object(m,"failclosed",return_value=True) as stop:
                m.watchdog(path)
            stop.assert_called_once()
            self.assertEqual(json.loads((path/"state.json").read_text())["state"],"quiesced")
    def test_watchdog_committed_requires_real_guard_and_healthy_tun(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);path=base/"xray-failover-1-2";path.mkdir()
            (path/"state.json").write_text(json.dumps({"state":"committed"}))
            with mock.patch.object(m,"BASE",base),mock.patch.object(m,"run",return_value=
                  "Transit guard: SAFE\nTransit policy rule: ACTIVE\nTransit VPN table: READY"),\
                 mock.patch.object(m,"routes_ok",return_value=True),\
                 mock.patch.object(m,"http_code",return_value=True),\
                 mock.patch.object(m,"failclosed") as stop:
                m.watchdog(path)
            stop.assert_not_called()
    def test_installer_and_backup_package_passive_executor(self):
        install=(ROOT/"install.sh").read_text()
        backup=(ROOT/"src/awg-update").read_text()
        for name in ("awg-xray-live-backend","awg-xray-activation-transaction"):
            self.assertIn("src/"+name+".py /usr/local/sbin/"+name,install)
            self.assertIn("usr/local/sbin/"+name,backup)
        self.assertNotIn("systemctl enable --now awg-xray-vless",install)
        self.assertNotIn("AWG_XRAY_EXPERIMENTAL_APPLY=TEST_PI_AUTHORIZED",install)

if __name__=="__main__":unittest.main()
