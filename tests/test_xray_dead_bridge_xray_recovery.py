#!/usr/bin/env python3
"""Rootless watchdog and boot-drop-in contract for dead Xray -> new Xray."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"src/awg-xray-manual-switch.py"
spec=importlib.util.spec_from_file_location("dead_xray_xray",SOURCE)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class DeadXrayToXray(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.commands=[]
        self.root.mkdir(exist_ok=True)
        self.provider=self.root/"provider";self.provider.write_bytes(b"subscription")
        self.selected=self.root/"selected";self.selected.write_text(json.dumps({"sha256":"a"*64}))
        self.mode=self.root/"mode";self.mode.write_text("transit")
        self.lock=self.root/"lock"
        self.boot=self.root/"boot"
        self.egress=self.root/"expected-egress"
        self.node_name="FreshXray"
        self.fingerprint="b"*64
        self.hash="c"*64
        self.profile=(self.node_name,self.hash,self.fingerprint)
        self.writes={}
        def cmd(*args,**kwargs):
            self.commands.append(args)
            if len(args)>1 and args[1]=="get" and args[0].endswith("awg-transport"):return "mihomo"
            if args[0]==str(module.ADAPTER) and args[1]=="select":
                self.selected.write_text(json.dumps({"sha256":self.fingerprint}))
            return ""
        def atomic(path,data,mode=0o600):
            self.writes[str(path)]=(data,mode)
        self.started=False
        self.patches=[
            mock.patch.multiple(module,LOCK=self.lock,MODE=self.mode,PROVIDER=self.provider,
                                SELECTED=self.selected,BOOT=self.boot,MIHOMO_EGRESS=self.egress),
            mock.patch.object(module.os,"geteuid",return_value=0),
            mock.patch.object(module,"cmd",side_effect=cmd),
            mock.patch.object(module,"dead_xray_owned_bridge"),
            mock.patch.object(module,"controller",return_value={"now":module.ALIAS,"all":[module.ALIAS]}),
            mock.patch.object(module,"tun_runtime_ready",return_value=False),
            mock.patch.object(module,"source_node",return_value=self.profile),
            mock.patch.object(module,"preflight_xray"),
            mock.patch.object(module,"unit_active",side_effect=lambda u:u in
               ("ssh.service","dnsmasq.service",module.XRAY) or u.endswith(".timer")),
            mock.patch.object(module,"unit_enabled",return_value=False),
            mock.patch.object(module,"save_snap",return_value=(self.root/"snap",
                {"watchdog":"awg-xray-manual-fake","phase":"pending"})),
            mock.patch.object(module,"stored"),
            mock.patch.object(module,"checkpoint"),
            mock.patch.object(module,"dead_xray_quiesce"),
            mock.patch.object(module,"prove_local_xray"),
            mock.patch.object(module,"native_env"),
            mock.patch.object(module,"atomic",side_effect=atomic),
            mock.patch.object(module,"wait_native_controller"),
            mock.patch.object(module,"choose"),
            mock.patch.object(module,"native_runtime_proof"),
            mock.patch.object(module,"auto_candidate_network_proof"),
            mock.patch.object(module.subprocess,"run",return_value=mock.Mock(returncode=0)),
            mock.patch.object(module,"invariant")
        ]
        for patch in self.patches:
            patch.start();self.addCleanup(patch.stop)

    def test_old_xray_must_be_dead(self):
        with mock.patch.object(module,"tun_runtime_ready",return_value=True),\
             self.assertRaisesRegex(module.DeadXrayPreflight,"PREVIOUS_TUN_STILL_HEALTHY"):
            module.dead_xray_xray(3)
        module.dead_xray_quiesce.assert_not_called()
        module.save_snap.assert_not_called()

    def test_awg_must_not_be_modified(self):
        def active_awg(*args,**kwargs):
            if len(args)>1 and args[1]=="get":return "awg"
            raise AssertionError("foreign active transport should not be modified")
        with mock.patch.object(module,"cmd",side_effect=active_awg),\
             self.assertRaisesRegex(module.DeadXrayPreflight,"ACTIVE_TRANSPORT_NOT_MIHOMO"):
            module.dead_xray_xray(3)
        module.dead_xray_quiesce.assert_not_called()
        module.save_snap.assert_not_called()

    def test_identical_failed_xray_never_reused(self):
        self.selected.write_text(json.dumps({"sha256":self.fingerprint}))
        with self.assertRaisesRegex(module.DeadXrayPreflight,"FAILED_XRAY_CANDIDATE_REUSED"):
            module.dead_xray_xray(3)
        module.dead_xray_quiesce.assert_not_called()

    def test_failed_exact_preflight_does_not_arm_watchdog(self):
        with mock.patch.object(module,"preflight_xray",
             side_effect=RuntimeError("XRAY_ISOLATED_HTTPS_NOT_VERIFIED")),\
             self.assertRaisesRegex(module.DeadXrayPreflight,"XRAY_ISOLATED_HTTPS_NOT_VERIFIED"):
            module.dead_xray_xray(3)
        module.dead_xray_quiesce.assert_not_called()
        self.assertFalse(any(c[0]=="systemd-run" for c in self.commands))

    def test_verified_new_xray_keeps_manual_exit_possible(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            module.dead_xray_xray(3)
        self.assertIn("DEAD_XRAY_XRAY_LOCAL_RUNTIME=READY",output.getvalue())
        module.native_env.assert_any_call("MIHOMO_XRAY_VLESS_BRIDGE","auto")
        boot=self.writes[str(self.boot)][0]
        self.assertIn(b"AWG_XRAY_MANUAL=1",boot)
        self.assertIn(b'Environment="MIHOMO_XRAY_VLESS_BRIDGE=1"',boot)
        self.assertFalse(any(c[0].endswith("awg-mihomo-prepare") for c in self.commands))
        self.assertIn(("systemctl","start",module.MIHOMO),[c[:3] for c in self.commands])
        self.assertIn(("systemctl","enable",module.XRAY),self.commands)
        self.assertEqual(module.native_runtime_proof.call_count,2)

    def test_new_xray_failure_quiesces_before_awg(self):
        with mock.patch.object(module,"native_runtime_proof",
             side_effect=RuntimeError("XRAY_TUN_FAILED")),\
             self.assertRaisesRegex(module.DeadXrayAbort,"XRAY_TUN_FAILED"):
            module.dead_xray_xray(3)
        self.assertEqual(module.dead_xray_quiesce.call_count,2)
        module.stored.assert_any_call(self.root/"snap",mock.ANY,"rolled_back")
        self.assertIn(("systemctl","stop","awg-xray-manual-fake.timer"),self.commands)

if __name__=="__main__":
    unittest.main()
