#!/usr/bin/env python3
"""Rootless regression checks for guarded manual Xray TUN transaction.

Mocks prevent live network, systemctl, policy routing and service modifications.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src/awg-xray-manual-switch.py"
spec=importlib.util.spec_from_file_location("manual_xray",SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class ManualSwitchContract(unittest.TestCase):
    def test_installer_contains_manual_executor_and_ui(self):
        install=(ROOT/"install.sh").read_text()
        menu=(ROOT/"src/awg-menu").read_text()
        self.assertIn("install_project_python_helper src/awg-xray-manual-switch.py",install)
        self.assertIn('"$XRAY_MANUAL_SWITCH" preview "$index"',menu)
        self.assertIn('"$XRAY_MANUAL_SWITCH" apply "$index"',menu)
        self.assertIn('confirm "Переключение на Xray"',menu)
        self.assertNotIn("awg-transport select awg",SCRIPT.read_text())

    def test_does_not_reuse_failed_incumbent_auto_executor(self):
        s=SCRIPT.read_text()
        self.assertIn("if not https_ok(\"tun\"):refuse(\"PREVIOUS_TUN_NOT_PROVEN\")",s)
        self.assertIn('if ALIAS not in con.get("all",[]):refuse("XRAY_BRIDGE_NOT_IN_RUNNING_CONFIG")',s)
        self.assertIn("XRAY_FRESH_NETWORK_PROOF_REQUIRED",s)
        self.assertIn("systemd-run",s)
        self.assertIn("xray-manual-",s)
        self.assertNotIn("shell=True",s)
        self.assertNotIn("AWG_XRAY_EXPERIMENTAL_APPLY",s)
        self.assertIn('AWG_XRAY_MANUAL=1',s)

    @mock.patch.object(mod.os,"geteuid",return_value=1000)
    def test_preview_rejects_nonroot(self,_):
        with self.assertRaisesRegex(RuntimeError,"ROOT_REQUIRED"):
            mod.inspect(1)

    def test_preview_requires_live_native_or_xray_and_healthy_tun(self):
        with mock.patch.object(mod.os,"geteuid",return_value=0), \
             mock.patch.object(mod,"source_node",return_value=("Germany", "hash","id")), \
             mock.patch.object(mod,"invariant"), \
             mock.patch.object(mod,"controller",return_value={"now":"Native","all":[mod.ALIAS]}), \
             mock.patch.object(mod,"unit_active",return_value=False), \
             mock.patch.object(mod,"unit_enabled",return_value=False), \
             mock.patch.object(mod,"https_ok",return_value=False), \
             mock.patch.object(mod,"BOOT",Path("/nonexistent/xray-manual-test-absent")):
            with self.assertRaisesRegex(RuntimeError,"PREVIOUS_TUN_NOT_PROVEN"):
                mod.inspect(3)

    def test_missing_bridge_rejects_before_any_mutation(self):
        with mock.patch.object(mod.os,"geteuid",return_value=0), \
             mock.patch.object(mod,"source_node",return_value=("Germany","hash","id")), \
             mock.patch.object(mod,"invariant"), \
             mock.patch.object(mod,"controller",return_value={"now":"Native","all":["Native"]}), \
             mock.patch.object(mod,"cmd") as c:
            with self.assertRaisesRegex(RuntimeError,"XRAY_BRIDGE_NOT_IN_RUNNING_CONFIG"):
                mod.inspect(3)
            c.assert_not_called()

    def test_failed_switch_restores_native_and_policy(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);snap=p/"snapshot";snap.mkdir()
            for name,body in [("current.prev",b"Native\n"),("policy.prev",b"fixed\n"),
                              ("order.prev",b"Native\nBackup\n"),("selected.prev",b"old-staged"),
                              ("boot.prev",b"old # AWG_XRAY_MANUAL=1")]:
                (snap/name).write_bytes(body)
            targets={key:p/(key+".new") for key in ("selected","boot","current","policy","order")}
            for file in targets.values():file.write_bytes(b"mutated")
            calls=[]
            def fake_cmd(*args,**kwargs):
                calls.append(args)
                return "mihomo" if args[:2]==("/usr/local/sbin/awg-transport","get") else ""
            with mock.patch.multiple(mod,SELECTED=targets["selected"],
                BOOT=targets["boot"],CURRENT=targets["current"],
                POLICY=targets["policy"],ORDER=targets["order"]), \
                 mock.patch.object(mod,"cmd",side_effect=fake_cmd), \
                 mock.patch.object(mod,"choose") as choose, \
                 mock.patch.object(mod,"https_ok",return_value=True), \
                 mock.patch.object(mod,"prove_local_xray"), \
                 mock.patch.object(mod,"invariant"):
                mod.restore(snap,{"previous":"Native","previous_xray":False,
                                  "xray_enabled":False})
            choose.assert_called_once_with("Native")
            self.assertEqual(targets["current"].read_bytes(),b"Native\n")
            self.assertEqual(targets["policy"].read_bytes(),b"fixed\n")
            self.assertEqual(targets["selected"].read_bytes(),b"old-staged")
            self.assertIn(("systemctl","stop",mod.XRAY),calls)
            self.assertIn(("systemctl","disable",mod.XRAY),calls)

    def test_rollback_xray_restores_old_profile_before_local_selection(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);snap=p/"snapshot";snap.mkdir()
            (snap/"selected.prev").write_bytes(b"original Xray profile")
            new_selected=p/"selected.json";new_selected.write_bytes(b"candidate")
            actions=[]
            def fake_cmd(*args,**kwargs):
                actions.append(args)
                return "mihomo" if args[:2]==("/usr/local/sbin/awg-transport","get") else ""
            with mock.patch.multiple(mod,SELECTED=new_selected,BOOT=p/"boot",
                CURRENT=p/"current",POLICY=p/"policy",ORDER=p/"order"), \
                 mock.patch.object(mod,"cmd",side_effect=fake_cmd), \
                 mock.patch.object(mod,"choose") as choose, \
                 mock.patch.object(mod,"https_ok",return_value=True), \
                 mock.patch.object(mod,"unit_active",return_value=True), \
                 mock.patch.object(mod,"prove_local_xray"), \
                 mock.patch.object(mod,"invariant"):
                mod.restore(snap,{"previous":mod.ALIAS,"previous_xray":True,
                                  "xray_enabled":True})
            self.assertEqual(new_selected.read_bytes(),b"original Xray profile")
            self.assertIn(("systemctl","stop",mod.XRAY),actions)
            self.assertIn(("systemctl","start",mod.XRAY),actions)
            choose.assert_called_once_with(mod.ALIAS)

    def test_successful_manual_xray_switch_preserves_fixed_chain_and_ready_policy(self):
        # All operations are mocked: no live service or network is touched.
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            snap=p/"snapshot";snap.mkdir()
            lock=p/"maintenance.lock"
            current=p/"current";current.write_text("OldNative\n")
            policy=p/"node-policy.mode";policy.write_bytes(b"fixed\n")
            order=p/"node-policy.nodes";order.write_bytes(b"OldNative\nFallback\n")
            ready=p/"ready-auto.mode";ready.write_bytes(b"0\n")
            boot=p/"systemd"/"62-awg-xray-manual.conf"
            info={"index":1,"candidate":"XrayNode","sha":"provider-digest",
                  "fingerprint":"transport-digest","previous":"OldNative",
                  "previous_xray":False,"xray_enabled":False}
            state={"phase":"pending",**info,"watchdog":"awg-xray-manual-test"}
            with mock.patch.multiple(mod,LOCK=lock,CURRENT=current,POLICY=policy,
                                     ORDER=order,BOOT=boot), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"inspect",return_value=info), \
                 mock.patch.object(mod,"save_snap",return_value=(snap,state)), \
                 mock.patch.object(mod,"source_node",return_value=("XrayNode","provider-digest","transport-digest")), \
                 mock.patch.object(mod,"cmd",return_value=""), \
                 mock.patch.object(mod,"unit_active",return_value=True), \
                 mock.patch.object(mod,"unit_enabled",return_value=True), \
                 mock.patch.object(mod,"https_ok",return_value=True), \
                 mock.patch.object(mod,"prove_local_xray"), \
                 mock.patch.object(mod,"routing_ok",return_value=True), \
                 mock.patch.object(mod,"invariant"), \
                 mock.patch.object(mod,"choose"):
                mod.apply(1)
            self.assertEqual(policy.read_bytes(),b"fixed\n")
            self.assertEqual(order.read_bytes(),b"OldNative\nFallback\n")
            self.assertEqual(ready.read_bytes(),b"0\n")
            self.assertEqual(current.read_bytes(),b"XrayNode\n")
            self.assertIn(b"AWG_XRAY_MANUAL=1",boot.read_bytes())

    def test_local_xray_waits_for_listener_and_tries_https_twice(self):
        fake_socket=mock.MagicMock()
        with mock.patch.object(mod,"unit_active",return_value=True), \
             mock.patch.object(mod.socket,"create_connection",return_value=fake_socket), \
             mock.patch.object(mod,"https_ok",side_effect=[False,True]) as https, \
             mock.patch.object(mod.time,"sleep"):
            mod.prove_local_xray()
        self.assertEqual(https.call_count,2)
        self.assertEqual(fake_socket.__enter__.call_count,1)

    def test_local_xray_reports_service_inactive(self):
        with mock.patch.object(mod,"unit_active",return_value=False), \
             mock.patch.object(mod.time,"monotonic",side_effect=[0,11]), \
             mock.patch.object(mod.time,"sleep"):
            with self.assertRaisesRegex(RuntimeError,"XRAY_SERVICE_NOT_ACTIVE"):
                mod.prove_local_xray()

    def test_local_xray_reports_missing_fixed_socks_listener(self):
        with mock.patch.object(mod,"unit_active",return_value=True), \
             mock.patch.object(mod.socket,"create_connection",side_effect=OSError("unavailable")), \
             mock.patch.object(mod.time,"monotonic",side_effect=[0,11]), \
             mock.patch.object(mod.time,"sleep"):
            with self.assertRaisesRegex(RuntimeError,"XRAY_SOCKS_PORT_NOT_LISTENING"):
                mod.prove_local_xray()

    def test_local_xray_reports_https_failure_before_selector_change(self):
        fake_socket=mock.MagicMock()
        with mock.patch.object(mod,"unit_active",return_value=True), \
             mock.patch.object(mod.socket,"create_connection",return_value=fake_socket), \
             mock.patch.object(mod,"https_ok",return_value=False), \
             mock.patch.object(mod.time,"sleep"):
            with self.assertRaisesRegex(RuntimeError,"XRAY_SOCKS_HTTPS_NOT_VERIFIED"):
                mod.prove_local_xray()

    def test_local_xray_reports_process_exit_during_https(self):
        fake_socket=mock.MagicMock()
        with mock.patch.object(mod,"unit_active",side_effect=[True,True,False]), \
             mock.patch.object(mod.socket,"create_connection",return_value=fake_socket), \
             mock.patch.object(mod,"https_ok",return_value=False), \
             mock.patch.object(mod.time,"sleep"):
            with self.assertRaisesRegex(RuntimeError,"XRAY_SERVICE_EXITED_DURING_HTTPS"):
                mod.prove_local_xray()


    def test_exact_current_xray_identity_is_recognized_only_by_fingerprint(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            selected=p/"selected.json"
            selected.write_text('{"sha256":"exact-transport-identity"}')
            with mock.patch.multiple(mod,SELECTED=selected,
                    BOOT=p/"absent-unit.conf"), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"source_node",
                                   return_value=("Xray", "provider","exact-transport-identity")), \
                 mock.patch.object(mod,"invariant"), \
                 mock.patch.object(mod,"controller",
                                   return_value={"now":mod.ALIAS,"all":[mod.ALIAS]}), \
                 mock.patch.object(mod,"unit_active",return_value=True), \
                 mock.patch.object(mod,"unit_enabled",return_value=True), \
                 mock.patch.object(mod,"https_ok",return_value=True):
                same=mod.inspect(1)
                self.assertTrue(same["already_selected"])
                with mock.patch.object(mod,"source_node",
                        return_value=("OtherXray","provider","different-identity")):
                    different=mod.inspect(2)
                    self.assertFalse(different["already_selected"])

    def test_already_active_xray_does_not_arm_watchdog_or_stop_live_service(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            info={"already_selected":True,"previous":mod.ALIAS,
                  "previous_xray":True,"index":1}
            with mock.patch.multiple(mod,LOCK=p/"lock"), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"inspect",return_value=info), \
                 mock.patch.object(mod,"save_snap") as snapshot, \
                 mock.patch.object(mod,"cmd") as command, \
                 mock.patch.object(mod,"choose") as controller:
                mod.apply(1)
                snapshot.assert_not_called()
                command.assert_not_called()
                controller.assert_not_called()

    def test_menu_avoids_restarting_already_selected_xray(self):
        menu=(ROOT/"src/awg-menu").read_text()
        self.assertIn("grep -Fxq 'XRAY_MANUAL_ALREADY_SELECTED=YES' \"$TMP\"",menu)
        self.assertIn('Повторная остановка Xray и переключение не требуются',menu)


    def test_previous_xray_restore_waits_for_transient_tun_recovery(self):
        with mock.patch.object(mod,"unit_active",return_value=True), \
             mock.patch.object(mod,"https_ok",side_effect=[False,False,True]) as probe, \
             mock.patch.object(mod.time,"sleep") as sleep:
            mod.prove_previous_tun()
            self.assertEqual(probe.call_count,3)
            self.assertEqual(sleep.call_count,2)

    def test_previous_xray_restore_fails_closed_if_tun_never_recovers(self):
        with mock.patch.object(mod,"unit_active",return_value=True), \
             mock.patch.object(mod,"https_ok",return_value=False), \
             mock.patch.object(mod.time,"sleep"):
            with self.assertRaisesRegex(RuntimeError,"PREVIOUS_TUN_RESTORE_FAILED"):
                mod.prove_previous_tun()

    def test_diagnostics_never_persist_secret_exception_details(self):
        self.assertEqual(mod.stable_error_code(RuntimeError("XRAY_SOCKS_HTTPS_NOT_VERIFIED")),
                         "XRAY_SOCKS_HTTPS_NOT_VERIFIED")
        self.assertEqual(mod.stable_error_code(RuntimeError("secret.example:8888 uuid-1")),
                         "UNCLASSIFIED_FAILURE")

    def test_xray_to_xray_failed_probe_persists_safe_step_and_original_error(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            snap=p/"snap";snap.mkdir()
            state={"phase":"pending","watchdog":"awg-xray-manual-test",
                   "previous":mod.ALIAS,"previous_xray":True}
            info={"already_selected":False,"index":2,"candidate":"Other",
                  "sha":"digest","fingerprint":"new","previous":mod.ALIAS,
                  "previous_xray":True,"xray_enabled":True}
            actions=[]
            def fake_cmd(*args,**kwargs):
                actions.append(args)
                return ""
            with mock.patch.multiple(mod,LOCK=p/"maintenance.lock"), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"inspect",return_value=info), \
                 mock.patch.object(mod,"save_snap",return_value=(snap,state)), \
                 mock.patch.object(mod,"cmd",side_effect=fake_cmd), \
                 mock.patch.object(mod,"unit_active",return_value=True), \
                 mock.patch.object(mod,"source_node",return_value=("Other","digest","new")), \
                 mock.patch.object(mod,"prove_local_xray",
                     side_effect=RuntimeError("XRAY_SOCKS_HTTPS_NOT_VERIFIED")), \
                 mock.patch.object(mod,"restore") as restore:
                with self.assertRaisesRegex(RuntimeError,"XRAY_SOCKS_HTTPS_NOT_VERIFIED"):
                    mod.apply(2)
            saved=__import__("json").loads((snap/"state.json").read_text())
            self.assertEqual(saved["phase"],"rolled_back")
            self.assertEqual(saved["failure_code"],"XRAY_SOCKS_HTTPS_NOT_VERIFIED")
            self.assertEqual(saved["failed_at"],"PROBE_NEW_XRAY_SOCKS")
            self.assertEqual(saved["checkpoint"],"ROLLBACK_COMPLETE")
            restore.assert_called_once()
            self.assertIn(("systemctl","stop",mod.XRAY),actions)

    def test_xray_to_xray_failed_immediate_restore_leaves_watchdog_armed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            snap=p/"snap";snap.mkdir()
            state={"phase":"pending","watchdog":"awg-xray-manual-test",
                   "previous":mod.ALIAS,"previous_xray":True}
            info={"already_selected":False,"index":2,"candidate":"Other",
                  "sha":"digest","fingerprint":"new","previous":mod.ALIAS,
                  "previous_xray":True,"xray_enabled":True}
            with mock.patch.multiple(mod,LOCK=p/"maintenance.lock"), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"inspect",return_value=info), \
                 mock.patch.object(mod,"save_snap",return_value=(snap,state)), \
                 mock.patch.object(mod,"cmd",return_value=""), \
                 mock.patch.object(mod,"unit_active",return_value=True), \
                 mock.patch.object(mod,"source_node",return_value=("Other","digest","new")), \
                 mock.patch.object(mod,"prove_local_xray",
                     side_effect=RuntimeError("XRAY_SOCKS_HTTPS_NOT_VERIFIED")), \
                 mock.patch.object(mod,"restore",
                     side_effect=RuntimeError("PREVIOUS_TUN_RESTORE_FAILED")):
                with self.assertRaisesRegex(RuntimeError,"XRAY_MANUAL_ROLLBACK_UNCONFIRMED"):
                    mod.apply(2)
            saved=__import__("json").loads((snap/"state.json").read_text())
            self.assertEqual(saved["phase"],"armed")
            self.assertEqual(saved["rollback_failure_code"],"PREVIOUS_TUN_RESTORE_FAILED")
            self.assertEqual(saved["checkpoint"],"WATCHDOG_RECOVERY_PENDING")

    def test_native_preview_handles_both_engines_and_unloaded_target(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            selected=p/"selected.json";selected.write_text(json.dumps({"sha256":"a"*64}))
            current=p/"node";current.write_text("OldNative\n")
            candidate={"candidate":"NewNative","endpoint":"203.0.113.20",
                       "filter":"^NewNative$","sha":"providerdigest"}
            with mock.patch.multiple(mod,SELECTED=selected,CURRENT=current,
                                     BOOT=p/"absent-boot.conf"), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"candidate_native",return_value=candidate), \
                 mock.patch.object(mod,"invariant"), \
                 mock.patch.object(mod,"controller",return_value={
                     "now":mod.ALIAS,"all":[mod.ALIAS,"OldNative"]}), \
                 mock.patch.object(mod,"unit_active",return_value=True), \
                 mock.patch.object(mod,"unit_enabled",return_value=True), \
                 mock.patch.object(mod,"https_ok",return_value=True):
                info=mod.inspect_native("NewNative")
                self.assertTrue(info["previous_xray"])
                self.assertEqual(info["previous"],mod.ALIAS)
                self.assertFalse(info["already_selected"])
            with mock.patch.multiple(mod,CURRENT=current,
                                     BOOT=p/"absent-boot.conf"), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"candidate_native",return_value=candidate), \
                 mock.patch.object(mod,"invariant"), \
                 mock.patch.object(mod,"controller",return_value={
                     "now":"OldNative","all":["OldNative"]}), \
                 mock.patch.object(mod,"unit_active",return_value=False), \
                 mock.patch.object(mod,"unit_enabled",return_value=False), \
                 mock.patch.object(mod,"https_ok",return_value=True):
                info=mod.inspect_native("NewNative")
                self.assertFalse(info["previous_xray"])
                self.assertEqual(info["previous"],"OldNative")
                self.assertFalse(info["already_selected"])

    def test_native_same_profile_does_not_arm_watchdog(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            info={"previous":"Native","candidate":"Native",
                  "previous_xray":False,"already_selected":True}
            with mock.patch.multiple(mod,LOCK=p/"lock"), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"inspect_native",return_value=info), \
                 mock.patch.object(mod,"save_snap") as save, \
                 mock.patch.object(mod,"cmd") as cmd:
                mod.native_return("Native")
                save.assert_not_called()
                cmd.assert_not_called()

    def test_native_env_uses_shell_escaping_without_provider_expansion(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"provider.env"
            p.write_text("OTHER=keep\nMIHOMO_NODE_FILTER='^Old$'\n")
            with mock.patch.multiple(mod,MIHOMO_ENV=p):
                mod.native_env("MIHOMO_NODE_FILTER","^New (x)$")
            self.assertIn("OTHER=keep",p.read_text())
            self.assertIn("MIHOMO_NODE_FILTER='^New (x)$'",p.read_text())
            self.assertNotIn("^Old",p.read_text())

    def test_successful_native_return_commits_actual_native_controller(self):
        import hashlib,json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            provider=p/"provider";provider.write_bytes(b"synthetic-provider")
            current=p/"node";current.write_text("OldXray\n")
            selected=p/"selected";selected.write_text(json.dumps({"sha256":"a"*64}))
            boot=p/"boot";boot.write_text("# AWG_XRAY_MANUAL=1\n")
            policy=p/"policy";policy.write_text("fixed\n")
            order=p/"order";order.write_text("native1\nnative2\n")
            endpoint=p/"endpoint";endpoint.write_text("203.0.113.4\n")
            egress=p/"egress";egress.write_text("203.0.113.8\n")
            snap=p/"snap";snap.mkdir()
            info={"candidate":"NewNative","endpoint":"203.0.113.20",
                  "filter":"^NewNative$","sha":hashlib.sha256(b"synthetic-provider").hexdigest(),
                  "previous":mod.ALIAS,"previous_xray":True,"xray_enabled":True,
                  "operation":"NATIVE_SWITCH","already_selected":False}
            state={"phase":"pending",**info,"watchdog":"awg-xray-manual-test"}
            commands=[]
            def fake_cmd(*args,**kwargs):
                commands.append(args);return ""
            with mock.patch.multiple(mod,LOCK=p/"lock",PROVIDER=provider,CURRENT=current,
                    SELECTED=selected,BOOT=boot,POLICY=policy,ORDER=order,
                    MIHOMO_ENDPOINT=endpoint,MIHOMO_EGRESS=egress), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"inspect_native",return_value=info), \
                 mock.patch.object(mod,"candidate_native",return_value=info), \
                 mock.patch.object(mod,"save_snap",return_value=(snap,state)), \
                 mock.patch.object(mod,"cmd",side_effect=fake_cmd), \
                 mock.patch.object(mod,"native_env"), \
                 mock.patch.object(mod,"wait_native_controller"), \
                 mock.patch.object(mod,"native_tun_proof"), \
                 mock.patch.object(mod,"unit_active",side_effect=lambda name:name.endswith(".timer")), \
                 mock.patch.object(mod,"invariant"), \
                 mock.patch.object(mod,"controller",return_value={
                     "now":"NewNative","all":["NewNative"]}), \
                 mock.patch.object(mod,"choose") as choose:
                mod.native_return("NewNative")
            choose.assert_called_once_with("NewNative")
            self.assertEqual(current.read_text(),"NewNative\n")
            self.assertEqual(policy.read_text(),"fixed\n")
            self.assertEqual(order.read_text(),"native1\nnative2\n")
            self.assertFalse(selected.exists())
            self.assertFalse(boot.exists())
            self.assertEqual(json.loads((snap/"state.json").read_text())["phase"],"committed")
            self.assertIn(("systemctl","stop",mod.XRAY),commands)

    def test_failed_native_tun_restores_full_previous_state(self):
        import hashlib,json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            provider=p/"provider";provider.write_bytes(b"provider")
            endpoint=p/"endpoint";current=p/"current"
            info={"candidate":"NewNative","endpoint":"203.0.113.20",
                  "filter":"^NewNative$","sha":hashlib.sha256(b"provider").hexdigest(),
                  "previous":mod.ALIAS,"previous_xray":True,"xray_enabled":True,
                  "already_selected":False,"operation":"NATIVE_SWITCH"}
            state={"phase":"pending",**info,"watchdog":"awg-xray-manual-test"}
            snap=p/"snapshot";snap.mkdir()
            with mock.patch.multiple(mod,LOCK=p/"lock",PROVIDER=provider,
                     MIHOMO_ENDPOINT=endpoint,MIHOMO_EGRESS=p/"egress",
                     CURRENT=current), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"inspect_native",return_value=info), \
                 mock.patch.object(mod,"candidate_native",return_value=info), \
                 mock.patch.object(mod,"save_snap",return_value=(snap,state)), \
                 mock.patch.object(mod,"cmd",return_value=""), \
                 mock.patch.object(mod,"unit_active",return_value=True), \
                 mock.patch.object(mod,"native_env"), \
                 mock.patch.object(mod,"wait_native_controller"), \
                 mock.patch.object(mod,"native_tun_proof",
                      side_effect=RuntimeError("NATIVE_TUN_HTTPS_UNVERIFIED")), \
                 mock.patch.object(mod,"choose"), \
                 mock.patch.object(mod,"restore_native") as restore:
                with self.assertRaisesRegex(RuntimeError,"NATIVE_TUN_HTTPS_UNVERIFIED"):
                    mod.native_return("NewNative")
                restore.assert_called_once()
            record=json.loads((snap/"state.json").read_text())
            self.assertEqual(record["phase"],"rolled_back")
            self.assertEqual(record["failed_at"],"NATIVE_TUN_PROOF")

    def test_native_restore_replaces_config_env_endpoint_and_original_xray(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);snapshot=p/"backup";snapshot.mkdir()
            targets={key:p/(key+".live") for key in
                     ("env","config","endpoint","egress","selected","current","boot","policy","order")}
            for key,target in targets.items():
                target.write_bytes(b"mutated")
                (snapshot/(key+".prev")).write_bytes((key+"-previous").encode())
            selected=targets["selected"]
            calls=[]
            def fake_cmd(*args,**kwargs):
                calls.append(args)
                return "mihomo" if args[:2]==("/usr/local/sbin/awg-transport","get") else ""
            state={"previous":mod.ALIAS,"previous_xray":True,"xray_enabled":True}
            with mock.patch.multiple(mod,MIHOMO_ENV=targets["env"],
                     MIHOMO_CONFIG=targets["config"],MIHOMO_ENDPOINT=targets["endpoint"],
                     MIHOMO_EGRESS=targets["egress"],SELECTED=selected,
                     CURRENT=targets["current"],BOOT=targets["boot"],
                     POLICY=targets["policy"],ORDER=targets["order"]), \
                 mock.patch.object(mod,"cmd",side_effect=fake_cmd), \
                 mock.patch.object(mod,"unit_active",return_value=False), \
                 mock.patch.object(mod,"prove_local_xray"), \
                 mock.patch.object(mod,"wait_native_controller"), \
                 mock.patch.object(mod,"native_tun_proof"), \
                 mock.patch.object(mod,"choose") as choose, \
                 mock.patch.object(mod,"invariant"):
                mod.restore_native(snapshot,state)
            choose.assert_called_once_with(mod.ALIAS)
            for key,target in targets.items():
                self.assertEqual(target.read_bytes(),(key+"-previous").encode())
            self.assertIn(("systemctl","stop",mod.MIHOMO),calls)
            self.assertIn(("systemctl","start",mod.MIHOMO),calls)
            self.assertIn(("systemctl","start",mod.XRAY),calls)

    def test_native_invalid_candidate_rejects_without_mutation(self):
        import yaml
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"provider.yaml"
            p.write_text(yaml.safe_dump({"proxies":[{"name":"xray-only","type":"vless",
                     "network":"xhttp"},{"name":"native","type":"ss"}]}))
            with mock.patch.object(mod,"PROVIDER",p), \
                 mock.patch.object(mod,"cmd") as command:
                with self.assertRaisesRegex(RuntimeError,"XRAY_PROFILE_IS_NOT_NATIVE"):
                    mod.candidate_native("xray-only")
                with self.assertRaisesRegex(RuntimeError,"NATIVE_PROFILE_NOT_UNIQUE"):
                    mod.candidate_native("not-in-provider")
                command.assert_not_called()

    def test_native_menu_dispatches_all_mihomo_from_any_engine(self):
        menu=(ROOT/"src/awg-menu").read_text()
        self.assertIn('"$XRAY_MANUAL_SWITCH" native-preview "$node_name"',menu)
        self.assertIn('"$XRAY_MANUAL_SWITCH" native-apply "$node_name"',menu)
        selection=menu.split("mihomo_node_menu(){",1)[1].split("mihomo_candidate_is_staged(){",1)[0]
        self.assertNotIn('"$MIHOMO_CONFIGURE" node select-auto',selection)
        status=(ROOT/"src/awg-mihomo-configure").read_text()
        self.assertIn("Actual outbound engine: XRAY",status)
        self.assertIn("Actual outbound engine: MIHOMO",status)

    def test_native_watchdog_not_armed_never_stops_healthy_xray(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);snap=p/"snapshot";snap.mkdir()
            info={"candidate":"NL native","previous":mod.ALIAS,
                  "previous_xray":True,"sha":"digest",
                  "fingerprint":"a"*64,"xray_enabled":True}
            state={"phase":"pending",**info,"watchdog":"awg-xray-manual-test"}
            commands=[]
            def fake_cmd(*args,**kwargs):
                commands.append(args)
                return ""
            with mock.patch.multiple(mod,LOCK=p/"lock"), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"inspect_native",return_value=info), \
                 mock.patch.object(mod,"save_snap",return_value=(snap,state)), \
                 mock.patch.object(mod,"cmd",side_effect=fake_cmd), \
                 mock.patch.object(mod,"unit_active",return_value=False), \
                 mock.patch.object(mod,"choose") as choose, \
                 mock.patch.object(mod,"restore") as restore:
                with self.assertRaisesRegex(RuntimeError,"WATCHDOG_NOT_ARMED"):
                    mod.native_return("NL native")
                choose.assert_not_called()
                restore.assert_not_called()
            record=json.loads((snap/"state.json").read_text())
            self.assertEqual(record["phase"],"cancelled")
            self.assertFalse(any(a[:2]==("systemctl","stop") and
                                 len(a)>2 and a[2]==mod.XRAY for a in commands))

    def test_prearm_error_never_stages_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            info={"index":1,"candidate":"X","sha":"sha","fingerprint":"fp",
                "previous":"Native","previous_xray":False,"xray_enabled":False}
            state={"phase":"pending",**info,"watchdog":"awg-xray-manual-test"}
            snap=p/"snapshot";snap.mkdir()
            (snap/"state.json").write_text("{}")
            calls=[]
            def fake_cmd(*args,**kwargs):
                calls.append(args)
                return ""
            with mock.patch.multiple(mod,LOCK=p/"lock"), \
                 mock.patch.object(mod.os,"geteuid",return_value=0), \
                 mock.patch.object(mod,"inspect",return_value=info), \
                 mock.patch.object(mod,"save_snap",return_value=(snap,state)), \
                 mock.patch.object(mod,"cmd",side_effect=fake_cmd), \
                 mock.patch.object(mod,"unit_active",return_value=False), \
                 mock.patch.object(mod,"restore") as restore, \
                 mock.patch.object(mod,"stored"):
                with self.assertRaisesRegex(RuntimeError,"WATCHDOG_NOT_ARMED"):
                    mod.apply(1)
                restore.assert_not_called()
            self.assertFalse(any(a[:2]==(str(mod.ADAPTER),"select") for a in calls))
            self.assertFalse(any(a[:2]==("systemctl","start") for a in calls))

if __name__=="__main__":unittest.main()
