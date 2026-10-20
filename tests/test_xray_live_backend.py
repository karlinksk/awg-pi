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
    def test_verified_awg_backup_must_have_exact_safe_transit_routes(self):
        with tempfile.TemporaryDirectory() as d:
            mode=Path(d)/"mode";mode.write_text("transit")
            def valid(*args,**kwargs):
                if args[-1]=="get":return "awg"
                if args[-1]=="status":
                    return "Transit guard: SAFE\nTransit policy rule: ACTIVE\nTransit VPN table: READY"
                if args[0]=="ip":return "default dev awg0 scope link"
                raise AssertionError(args)
            with mock.patch.object(m,"MODE",mode), mock.patch.object(m,"run",side_effect=valid),\
                 mock.patch.object(m,"active",return_value=True):
                self.assertTrue(m.verified_awg_backup_safe())
            with mock.patch.object(m,"MODE",mode), mock.patch.object(m,"run",side_effect=lambda *a,**k:
                 "default dev mihomo0" if a[0]=="ip" else valid(*a,**k)),\
                 mock.patch.object(m,"active",return_value=True):
                self.assertFalse(m.verified_awg_backup_safe())

    def test_failclosed_never_quiesces_healthy_active_awg(self):
        with tempfile.TemporaryDirectory() as d:
            mode=Path(d)/"mode";mode.write_text("transit")
            with mock.patch.object(m,"MODE",mode),\
                 mock.patch.object(m,"verified_awg_backup_safe",return_value=True),\
                 mock.patch.object(m,"run") as cmd:
                self.assertTrue(m.failclosed())
                cmd.assert_not_called()

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
    def test_healthy_original_tun_forbids_live_emergency_activation(self):
        with mock.patch.object(m,"http_code",return_value=True) as check:
            self.assertFalse(m.original_tun_unreachable_twice())
        check.assert_called_once_with(["--interface","mihomo0","--noproxy","*"])
        with mock.patch.object(m,"http_code",side_effect=[False,True]) as check:
            self.assertFalse(m.original_tun_unreachable_twice())
        self.assertEqual(check.call_count,2)
        with mock.patch.object(m,"http_code",side_effect=[False,False]) as check:
            self.assertTrue(m.original_tun_unreachable_twice())
        self.assertEqual(check.call_count,2)

    def test_degraded_fixed_requires_explicit_test_pi_failclosed(self):
        import os
        with tempfile.TemporaryDirectory() as dirname:
            mode=Path(dirname)/"node-policy.mode"
            mode.write_text("fixed")
            env={"AWG_XRAY_DEGRADED_FIXED":"1",
                 "MIHOMO_XRAY_FIXED_FAILOVER_CANARY":"1"}
            def services(unit):
                return unit in ("ssh.service","dnsmasq.service")
            def status(*args,**kwargs):
                if args[-1]=="status":
                    return "Transit guard: SAFE\nTransit policy rule: INACTIVE\nTransit VPN table: NOT_READY"
                return ""
            with (mock.patch.object(m,"NODE_POLICY_MODE",mode),
                  mock.patch.object(m.socket,"gethostname",return_value="awg-upgrade"),
                  mock.patch.dict(os.environ,env),
                  mock.patch.object(m,"active",side_effect=services),
                  mock.patch.object(m,"run",side_effect=status)):
                self.assertTrue(m.verified_degraded_fixed_baseline())
                with mock.patch.dict(os.environ,{"AWG_XRAY_DEGRADED_FIXED":"0"}):
                    self.assertFalse(m.verified_degraded_fixed_baseline())
                with mock.patch.object(m,"active",return_value=True):
                    self.assertFalse(m.verified_degraded_fixed_baseline())
                with mock.patch.object(m,"run",return_value=
                      "Transit guard: SAFE\nTransit policy rule: ACTIVE"):
                    self.assertFalse(m.verified_degraded_fixed_baseline())
                with mock.patch.object(m,"run",side_effect=lambda *a,**kw:
                      ("default via 192.0.2.1 dev eth0" if a[0]=="ip" else status(*a,**kw))):
                    self.assertFalse(m.verified_degraded_fixed_baseline())
                mode.write_text("auto")
                self.assertFalse(m.verified_degraded_fixed_baseline())

    def test_degraded_fixed_accepts_only_old_mihomo_defaults_not_foreign_routes(self):
        with tempfile.TemporaryDirectory() as dirname:
            path=Path(dirname)/"mode"
            path.write_text("fixed")
            env={"AWG_XRAY_DEGRADED_FIXED":"1",
                 "MIHOMO_XRAY_FIXED_FAILOVER_CANARY":"1"}
            def services(unit):
                return unit in ("ssh.service","dnsmasq.service")
            def check(*args,**kwargs):
                if args[-1]=="status":
                    return "Transit guard: LOCKDOWN"+chr(10)+"Transit policy rule: INACTIVE"
                if args[0]=="ip":
                    return "default dev mihomo0 scope link"
                raise AssertionError("unexpected test call")
            with (mock.patch.object(m,"NODE_POLICY_MODE",path),
                  mock.patch.object(m.socket,"gethostname",return_value="awg-upgrade"),
                  mock.patch.dict(m.os.environ,env),
                  mock.patch.object(m,"active",side_effect=services),
                  mock.patch.object(m,"run",side_effect=check)):
                self.assertTrue(m.verified_degraded_fixed_baseline())

    def test_degraded_policy_rule_restored_only_after_real_xray_tun_https(self):
        with tempfile.TemporaryDirectory() as dirname:
            mode=Path(dirname)/"mode"
            mode.write_text("transit")
            with mock.patch.object(m,"MODE",mode):
                backend=m.LinuxBackend("failed-HY2","Xray-VLESS")
                backend.degraded_fixed=True
                good="Transit guard: SAFE\nTransit policy rule: ACTIVE\nTransit VPN table: READY"
                calls=[]
                def command(*argv,**kwargs):
                    calls.append(argv)
                    return good
                with (mock.patch.object(m,"routes_ok",return_value=True),
                      mock.patch.object(backend,"check_tun_https",return_value=True),
                      mock.patch.object(m,"run",side_effect=command)):
                    self.assertTrue(backend.check_policy_routes())
                self.assertIn(("/usr/local/sbin/awg-transit-routing","apply"),calls)
                calls.clear()
                with (mock.patch.object(m,"routes_ok",return_value=True),
                      mock.patch.object(backend,"check_tun_https",return_value=False),
                      mock.patch.object(m,"run",side_effect=command)):
                    self.assertFalse(backend.check_policy_routes())
                self.assertEqual(calls,[])
                backend.degraded_fixed=False
                calls.clear()
                with (mock.patch.object(m,"routes_ok",return_value=True),
                      mock.patch.object(m,"run",side_effect=command)):
                    self.assertTrue(backend.check_policy_routes())
                self.assertNotIn(("/usr/local/sbin/awg-transit-routing","apply"),calls)
        
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
    def test_watchdog_pending_expires_without_killing_healthy_mihomo(self):
        with tempfile.TemporaryDirectory() as dirname:
            base=Path(dirname);snap=base/"xray-failover-19-3";snap.mkdir()
            (snap/"state.json").write_text(json.dumps({"state":"pending"}))
            with mock.patch.object(m,"BASE",base),mock.patch.object(m,"failclosed") as stop:
                m.watchdog(snap)
            stop.assert_not_called()
            self.assertEqual(json.loads((snap/"state.json").read_text())["state"],
                             "expired_before_mutation")
            with mock.patch.object(m,"BASE",base),mock.patch.object(m,"failclosed") as stop:
                m.watchdog(snap)
            stop.assert_not_called()

    def test_expired_watchdog_blocks_any_subsequent_xray_stage(self):
        with tempfile.TemporaryDirectory() as dirname:
            snap=Path(dirname)
            (snap/"state.json").write_text(json.dumps(
                {"state":"expired_before_mutation"}))
            backend=m.LinuxBackend("HY2","VLESS")
            backend.snapshot=snap
            with mock.patch.object(backend,"check_provider_unchanged",return_value=True):
                with mock.patch.object(m,"run") as command:
                    with self.assertRaisesRegex(RuntimeError,"WATCHDOG_EXPIRED_BEFORE_MUTATION"):
                        backend.stage_xray("VLESS")
            command.assert_not_called()

    def test_pre_mutation_transition_is_serialized_with_watchdog(self):
        with tempfile.TemporaryDirectory() as dirname:
            snap=Path(dirname)
            (snap/"state.json").write_text(json.dumps({"state":"pending"}))
            self.assertTrue(m.snapshot_transition(snap,"pending","armed"))
            self.assertFalse(m.snapshot_transition(snap,"pending","armed"))
            self.assertEqual(json.loads((snap/"state.json").read_text())["state"],"armed")

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
            mode=base/"mode";mode.write_text("transit")
            with mock.patch.object(m,"MODE",mode),mock.patch.object(m,"BASE",base),mock.patch.object(m,"run",return_value=
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

    def test_watchdog_safe_timer_script_scopes_actual_systemd_trigger(self):
        script=ROOT/"scripts"/"awg-xray-testpi-watchdog-safe-trigger.py"
        source=script.read_text()
        self.assertIn('str(EXEC),"watchdog",str(folder)',source)
        # Snapshot filename is part of the security boundary in watchdog().
        self.assertIn('folder=BASE/("xray-failover-"+str(int(time.time()))+"-"+str(os.getpid()))',source)
        self.assertIn('folder.mkdir(mode=0o700)',source)
        self.assertNotIn('mkdtemp(prefix="xray-failover-"',source)
        self.assertIn('"--on-active=5s"',source)
        self.assertIn('current=="pending"',source)
        self.assertIn('"expired_before_mutation"',source)
        self.assertIn('baseline()==before',source)
        self.assertIn('sha(EXEC)==sha(SRC)',source)
        self.assertIn('TRANSIT_GUARD_UNSAFE',source)
        self.assertIn('"FAIL_CLOSED_PATH","NOT_TESTED"',source)
        self.assertNotIn('"ip","route","replace"',source)
        self.assertNotIn('"systemctl","restart"',source)
        self.assertNotIn('"systemctl","disable"',source)

    def test_installer_and_backup_package_passive_executor(self):
        install=(ROOT/"install.sh").read_text()
        backup=(ROOT/"src/awg-update").read_text()
        for name in ("awg-xray-live-backend","awg-xray-activation-transaction"):
            self.assertIn("src/"+name+".py /usr/local/sbin/"+name,install)
            self.assertIn("usr/local/sbin/"+name,backup)
        self.assertNotIn("systemctl enable --now awg-xray-vless",install)
        self.assertNotIn("AWG_XRAY_EXPERIMENTAL_APPLY=TEST_PI_AUTHORIZED",install)

if __name__=="__main__":unittest.main()
