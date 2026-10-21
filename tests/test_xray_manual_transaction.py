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
                 mock.patch.object(mod,"routing_ok",return_value=True), \
                 mock.patch.object(mod,"invariant"), \
                 mock.patch.object(mod,"choose"):
                mod.apply(1)
            self.assertEqual(policy.read_bytes(),b"fixed\n")
            self.assertEqual(order.read_bytes(),b"OldNative\nFallback\n")
            self.assertEqual(ready.read_bytes(),b"0\n")
            self.assertEqual(current.read_bytes(),b"XrayNode\n")
            self.assertIn(b"AWG_XRAY_MANUAL=1",boot.read_bytes())

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
                 mock.patch.object(mod,"restore"), \
                 mock.patch.object(mod,"stored"):
                with self.assertRaisesRegex(RuntimeError,"WATCHDOG_NOT_ARMED"):
                    mod.apply(1)
            self.assertFalse(any(a[:2]==(str(mod.ADAPTER),"select") for a in calls))
            self.assertFalse(any(a[:2]==("systemctl","start") for a in calls))

if __name__=="__main__":unittest.main()
