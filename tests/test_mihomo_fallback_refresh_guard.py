#!/usr/bin/env python3
"""Stage28 unit tests: read-only, no production routes, services or provider writes."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
import yaml

path=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-fallback-refresh-guard.py"
spec=importlib.util.spec_from_file_location("refresh_guard",path)
guard=importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

def ss(name,host):
    return {"name":name,"server":host,"port":8080,"type":"ss","cipher":"aes-128-gcm","password":"TESTONLY"}

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"config.yaml"
        self.mode=Path(self.tmp.name)/"native-fallback.mode"
        self.payload={"proxies":[ss("A","169.150.210.233"),ss("B","176.32.32.108")],
           "proxy-groups":[{"name":"AWG-MIHOMO","type":"fallback","proxies":["A","B"]}]}
        self.write()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        self.path.write_text(yaml.safe_dump(self.payload))

    def test_native_detected_without_marker(self):
        self.assertEqual(guard.decide(self.path,self.mode),"native")

    def test_legacy_select_stays_legacy(self):
        self.payload["proxy-groups"][0]["type"]="select"
        self.write()
        self.assertEqual(guard.decide(self.path,self.mode),"legacy")

    def test_marker_native_overrides_legacy_group(self):
        self.payload["proxy-groups"][0]["type"]="select"
        self.write()
        self.mode.write_text("native\n")
        self.assertEqual(guard.decide(self.path,self.mode),"native")

    def test_marker_legacy_cannot_override_fallback(self):
        self.mode.write_text("legacy\n")
        self.assertEqual(guard.decide(self.path,self.mode),"native")

    def test_corrupt_marker_fails_closed(self):
        self.mode.write_text("oops\n")
        self.assertEqual(guard.decide(self.path,self.mode),"unknown")

    def test_invalid_config_with_no_marker_fails_closed(self):
        self.path.write_text("old-config\n")
        self.assertEqual(guard.decide(self.path,self.mode),"unknown")

    def test_duplicate_proxy_name_rejected(self):
        self.payload["proxies"][1]["name"]="A"
        self.write()
        with self.assertRaises(ValueError):guard.audit(self.path,"eth0","192.168.112.1")

    def test_native_direct_both_nodes_pass(self):
        def runner(cmd,**kwargs):
            return subprocess.CompletedProcess(cmd,0,stdout=f"{cmd[-1]} via 192.168.112.1 dev eth0 src 192.168.112.34\n",stderr="")
        self.assertEqual(guard.audit(self.path,"eth0","192.168.112.1",runner),["A","B"])

    def test_direct_route_reroute_rejected(self):
        def runner(cmd,**kwargs):
            ip=cmd[-1]
            route=f"{ip} via 192.168.112.1 dev eth0\n" if ip=="169.150.210.233" else f"{ip} dev mihomo0 table 100\n"
            return subprocess.CompletedProcess(cmd,0,stdout=route,stderr="")
        with self.assertRaises(ValueError):guard.audit(self.path,"eth0","192.168.112.1",runner)

    def test_unlisted_node_rejected(self):
        self.payload["proxy-groups"][0]["proxies"].append("C")
        self.write()
        with self.assertRaises(ValueError):guard.audit(self.path,"eth0","192.168.112.1")


    def test_monitor_native_tun_and_routes_healthy(self):
        self.payload["tun"]={"enable":True}
        self.write()
        def runner(cmd,**kwargs):
            return subprocess.CompletedProcess(cmd,0,stdout=f"{cmd[-1]} via 192.168.112.1 dev eth0 src 192.168.112.34\n",stderr="")
        self.assertEqual(guard.monitor_state(self.path,self.mode,"eth0","192.168.112.1",runner),"NATIVE_OK")

    def test_monitor_rejects_shadow_tun_off(self):
        self.payload["tun"]={"enable":False}
        self.write()
        self.assertEqual(guard.monitor_state(self.path,self.mode,"eth0","192.168.112.1"),"NATIVE_UNSAFE")

    def test_monitor_bad_route_is_unsafe(self):
        self.payload["tun"]={"enable":True}
        self.write()
        def runner(cmd,**kwargs):
            return subprocess.CompletedProcess(cmd,0,stdout=f"{cmd[-1]} dev mihomo0\n",stderr="")
        self.assertEqual(guard.monitor_state(self.path,self.mode,"eth0","192.168.112.1",runner),"NATIVE_UNSAFE")

    def test_monitor_legacy_without_marker(self):
        self.payload["proxy-groups"][0]["type"]="select"
        self.write()
        self.assertEqual(guard.monitor_state(self.path,self.mode,"eth0","192.168.112.1"),"LEGACY")

    def test_monitor_rejects_legacy_marker_with_invalid_config(self):
        self.mode.write_text("legacy\n")
        self.path.write_text("old-config\n")
        self.assertEqual(guard.monitor_state(self.path,self.mode,"eth0","192.168.112.1"),"NATIVE_UNSAFE")


if __name__=="__main__":
    unittest.main()
