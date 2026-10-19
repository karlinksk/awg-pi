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
            ephemeral=root/"runtime";ephemeral.write_text(bridge.read_text())
            selected=root/"selected";selected.write_text("staged")
            events=[]
            def cmd(*args,**kw):
                events.append(args)
                if args[-1]=="status":
                    return "Transit guard: SAFE\nTransit policy rule: INACTIVE"
                return ""
            with mock.patch.object(m,"MODE",mode),mock.patch.object(m,"BRIDGE",bridge),\
                 mock.patch.object(m,"BRIDGE_RUNTIME",ephemeral),mock.patch.object(m,"SELECTED",selected),mock.patch.object(m,"run",side_effect=cmd),\
                 mock.patch.object(m,"active",return_value=False):
                self.assertTrue(m.failclosed())
            self.assertFalse(bridge.exists());self.assertFalse(ephemeral.exists());self.assertFalse(selected.exists())
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
    def test_bridge_stays_ephemeral_until_live_tun_verification(self):
        import tempfile
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname)
            runtime=root/"run"/"61-awg-xray-bridge.conf"
            persisted=root/"etc"/"61-awg-xray-bridge.conf"
            renderer=root/"renderer"
            renderer.write_text("MIHOMO_XRAY_VLESS_BRIDGE")
            template=chr(10).join(("proxies:","  - name: AWG-XRAY-VLESS-LOCAL","    type: socks5",""))
            old_td=tempfile.TemporaryDirectory
            events=[]
            def temp_dir(**kwargs):
                return old_td(dir=dirname,prefix="test-")
            def fake_run(*args,**kwargs):
                events.append(args)
                if args[0]==str(renderer):
                    return template
                return ""
            backend=m.LinuxBackend("dead","vless")
            with (mock.patch.object(m,"BRIDGE_RUNTIME",runtime),
                  mock.patch.object(m,"BRIDGE",persisted),
                  mock.patch.object(m,"RENDERER",renderer),
                  mock.patch.object(backend,"check_provider_unchanged",return_value=True),
                  mock.patch.object(m,"run",side_effect=fake_run),
                  mock.patch("tempfile.TemporaryDirectory",side_effect=temp_dir)):
                backend.stage_mihomo_bridge()
            self.assertTrue(runtime.is_file())
            self.assertFalse(persisted.exists())
            self.assertIn(b"Requires=awg-xray-vless.service",runtime.read_bytes())
            self.assertIn(("systemctl","daemon-reload"),events)

    def test_persist_override_only_after_tun_postcheck(self):
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname)
            runtime=root/"run"/"61-awg-xray-bridge.conf"
            persisted=root/"etc"/"61-awg-xray-bridge.conf"
            backend=m.LinuxBackend("dead","vless")
            events=[]
            def command(*args,**kwargs):
                events.append(args)
                return ""
            with (mock.patch.object(m,"BRIDGE_RUNTIME",runtime),
                  mock.patch.object(m,"BRIDGE",persisted),
                  mock.patch.object(m,"run",side_effect=command)):
                with self.assertRaisesRegex(RuntimeError,"EPHEMERAL_BRIDGE_NOT_READY"):
                    backend.install_boot_dependencies()
                self.assertFalse(persisted.exists())
                runtime.parent.mkdir(parents=True,exist_ok=True)
                runtime.write_bytes(b'[Unit]\\nRequires=awg-xray-vless.service\\n[Service]\\nEnvironment="MIHOMO_XRAY_VLESS_BRIDGE=1"\\n')
                backend.install_boot_dependencies()
                self.assertEqual(persisted.read_bytes(),runtime.read_bytes())
            self.assertIn(("systemctl","enable",m.XRAY),events)

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
    def test_fixed_policy_allows_only_later_explicit_nodes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);mode=root/"mode";order=root/"order"
            mode.write_text("fixed")
            order.write_text("HY2-1"+chr(10)+"VLESS-2"+chr(10)+"HY2-3"+chr(10))
            with (mock.patch.object(m,"NODE_POLICY_MODE",mode),
                  mock.patch.object(m,"NODE_POLICY_ORDER",order)):
                self.assertTrue(m.candidate_allowed_by_policy("HY2-1","VLESS-2"))
                self.assertFalse(m.candidate_allowed_by_policy("HY2-3","VLESS-2"))
                self.assertFalse(m.candidate_allowed_by_policy("HY2-1","UNLISTED"))
                self.assertFalse(m.candidate_allowed_by_policy("HY2-1","HY2-1"))
                mode.write_text("manual")
                self.assertFalse(m.candidate_allowed_by_policy("HY2-1","VLESS-2"))
                mode.write_text("auto")
                self.assertTrue(m.candidate_allowed_by_policy("HY2-1","VLESS-2"))

    def test_commit_persists_new_profile_identity_before_monitor_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);current=root/"node-name";current.write_text("dead" + chr(10))
            state=root/"state.json";state.write_text(json.dumps({"state":"armed"}))
            executor=m.LinuxBackend("dead","vless-fallback")
            executor.snapshot=root
            with (mock.patch.object(m,"CURRENT",current),
                  mock.patch.object(executor,"check_policy_routes",return_value=True),
                  mock.patch.object(executor,"verify_committed_node",return_value=True)):
                executor.commit()
            self.assertEqual(current.read_text().strip(),"vless-fallback")
            self.assertEqual(json.loads(state.read_text())["state"],"committed")
            self.assertFalse(json.loads(state.read_text())["boot_tested"])

    def test_commit_refuses_changed_failed_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);current=root/"node-name";current.write_text("different" + chr(10))
            state=root/"state.json";state.write_text(json.dumps({"state":"armed"}))
            executor=m.LinuxBackend("dead","vless-fallback")
            executor.snapshot=root
            with (mock.patch.object(m,"CURRENT",current),
                  mock.patch.object(executor,"check_policy_routes",return_value=True),
                  mock.patch.object(executor,"verify_committed_node",return_value=True)):
                with self.assertRaisesRegex(RuntimeError,"IDENTITY_CHANGED"):
                    executor.commit()
            self.assertEqual(current.read_text().strip(),"different")
            self.assertEqual(json.loads(state.read_text())["state"],"armed")

    def test_installer_and_backup_package_passive_executor(self):
        install=(ROOT/"install.sh").read_text()
        backup=(ROOT/"src/awg-update").read_text()
        for name in ("awg-xray-live-backend","awg-xray-activation-transaction"):
            self.assertIn("src/"+name+".py /usr/local/sbin/"+name,install)
            self.assertIn("usr/local/sbin/"+name,backup)
        self.assertNotIn("systemctl enable --now awg-xray-vless",install)
        self.assertNotIn("AWG_XRAY_EXPERIMENTAL_APPLY=TEST_PI_AUTHORIZED",install)

if __name__=="__main__":unittest.main()
