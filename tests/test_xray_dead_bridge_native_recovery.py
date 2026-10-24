#!/usr/bin/env python3
"""Isolated, rootless contract for dead-Xray -> native Mihomo recovery.

Mocks prove failed preflight cannot change a running AWG or mutate a route;
post-activation failure cannot 'restore' a known-dead Xray outbound.
"""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"src/awg-xray-manual-switch.py"
spec=importlib.util.spec_from_file_location("dead_xray_native",SOURCE)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ACTUAL_QUIESCE=mod.dead_xray_quiesce

class DeadXrayRecovery(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.lock=self.root/"lock"
        self.mode=self.root/"mode";self.mode.write_text("transit\n")
        self.provider=self.root/"provider";self.provider.write_bytes(b"test-provider")
        self.selected=self.root/"selected"
        self.current=self.root/"current"
        self.boot=self.root/"boot"
        self.endpoint=self.root/"endpoint"
        self.egress=self.root/"egress"
        self.target={"candidate":"HealthyNative","sha":__import__("hashlib").sha256(b"test-provider").hexdigest(),
                     "filter":"^HealthyNative$","endpoint":"198.51.100.21"}
        self.commands=[]
        def cmd(*args,**kw):
            self.commands.append(args)
            if args[:2]==("/usr/local/sbin/awg-transport","get"):return "mihomo"
            return ""
        def active(service):
            return service in ("ssh.service","dnsmasq.service","awg-mihomo.service") or service.endswith(".timer")
        self.patches=[
            mock.patch.multiple(mod,LOCK=self.lock,MODE=self.mode,PROVIDER=self.provider,
                  SELECTED=self.selected,CURRENT=self.current,BOOT=self.boot,
                  MIHOMO_ENDPOINT=self.endpoint,MIHOMO_EGRESS=self.egress),
            mock.patch.object(mod.os,"geteuid",return_value=0),
            mock.patch.object(mod,"cmd",side_effect=cmd),
            mock.patch.object(mod,"dead_xray_owned_bridge"),
            mock.patch.object(mod,"controller",return_value={"now":mod.ALIAS,"all":[mod.ALIAS,"HealthyNative"]}),
            mock.patch.object(mod,"tun_runtime_ready",return_value=False),
            mock.patch.object(mod,"candidate_native",return_value=self.target.copy()),
            mock.patch.object(mod,"preflight_mihomo"),
            mock.patch.object(mod,"unit_active",side_effect=active),
            mock.patch.object(mod,"unit_enabled",return_value=False),
            mock.patch.object(mod,"save_snap",return_value=(self.root/"snap",
                        {"watchdog":"xray-manual-test","phase":"pending"})),
            mock.patch.object(mod,"stored"),
            mock.patch.object(mod,"checkpoint"),
            mock.patch.object(mod,"dead_xray_quiesce"),
            mock.patch.object(mod,"native_env"),
            mock.patch.object(mod,"atomic"),
            mock.patch.object(mod,"wait_native_controller"),
            mock.patch.object(mod,"choose"),
            mock.patch.object(mod,"native_runtime_proof"),
            mock.patch.object(mod,"invariant")
        ]
        for patch in self.patches:
            patch.start();self.addCleanup(patch.stop)

    def test_active_awg_never_modified(self):
        def on_cmd(*a,**kw):
            if a[:2]==("/usr/local/sbin/awg-transport","get"):return "awg"
            raise AssertionError("unsafe command")
        with mock.patch.object(mod,"cmd",side_effect=on_cmd),self.assertRaisesRegex(
             mod.DeadXrayPreflight,"ACTIVE_TRANSPORT_NOT_MIHOMO"):
            mod.dead_xray_native("HealthyNative")
        mod.preflight_mihomo.assert_not_called()
        mod.dead_xray_quiesce.assert_not_called()
        mod.save_snap.assert_not_called()

    def test_live_tun_must_already_be_failed(self):
        with mock.patch.object(mod,"tun_runtime_ready",return_value=True),self.assertRaisesRegex(
             mod.DeadXrayPreflight,"PREVIOUS_TUN_STILL_HEALTHY"):
            mod.dead_xray_native("HealthyNative")
        mod.dead_xray_quiesce.assert_not_called()
        mod.save_snap.assert_not_called()

    def test_unrelated_controller_cannot_be_replaced(self):
        with mock.patch.object(mod,"controller",return_value={"now":"Native","all":["Native"]}), \
             self.assertRaisesRegex(mod.DeadXrayPreflight,"FAILED_XRAY_BRIDGE_NOT_SELECTED"):
            mod.dead_xray_native("HealthyNative")
        mod.dead_xray_quiesce.assert_not_called()

    def test_bad_candidate_leaves_original_without_mutation(self):
        with mock.patch.object(mod,"preflight_mihomo",side_effect=RuntimeError(
             "NATIVE_ISOLATED_HTTPS_NOT_VERIFIED")),self.assertRaisesRegex(
             mod.DeadXrayPreflight,"NATIVE_ISOLATED_HTTPS_NOT_VERIFIED"):
            mod.dead_xray_native("BadNative")
        mod.save_snap.assert_not_called()
        mod.dead_xray_quiesce.assert_not_called()

    def test_verified_native_with_recovery_watchdog(self):
        buf=io.StringIO()
        mod.choose.side_effect=lambda name:setattr(
            mod.controller,"return_value",{"now":name,"all":[name]})
        with contextlib.redirect_stdout(buf):
            mod.dead_xray_native("HealthyNative")
        self.assertIn("DEAD_XRAY_NATIVE_LOCAL_RUNTIME=READY",buf.getvalue())
        self.assertEqual(mod.dead_xray_quiesce.call_count,1)
        mod.native_runtime_proof.assert_called_once()
        mod.native_env.assert_any_call("MIHOMO_XRAY_VLESS_BRIDGE","auto")
        mod.stored.assert_any_call(self.root/"snap",mock.ANY,"committed")
        self.assertIn(("systemd-run","--unit=xray-manual-test","--on-active=180s",
                       str(mod.SWITCH),"watchdog",str(self.root/"snap")),self.commands)
        self.assertIn(("systemctl","stop","xray-manual-test.timer"),self.commands)

    def test_postcheck_failure_quiesces_not_revives_old_xray(self):
        with mock.patch.object(mod,"native_runtime_proof",side_effect=RuntimeError(
             "NATIVE_TUN_HTTPS_UNVERIFIED")),self.assertRaisesRegex(
             mod.DeadXrayAbort,"NATIVE_TUN_HTTPS_UNVERIFIED"):
            mod.dead_xray_native("HealthyNative")
        self.assertEqual(mod.dead_xray_quiesce.call_count,2)
        mod.stored.assert_any_call(self.root/"snap",mock.ANY,"rolled_back")
        self.assertFalse(any(c==("systemctl","start",mod.XRAY) for c in self.commands))

    def test_quiesce_fails_keeps_independent_watchdog(self):
        def quiesce():
            if mod.dead_xray_quiesce.call_count>=2:raise RuntimeError("ROUTE_UNSAFE")
        with mock.patch.object(mod,"native_runtime_proof",side_effect=RuntimeError(
             "NATIVE_TUN_HTTPS_UNVERIFIED")),mock.patch.object(
             mod,"dead_xray_quiesce",side_effect=quiesce),self.assertRaisesRegex(
             mod.DeadXrayAbort,"DEAD_XRAY_WATCHDOG_PENDING"):
            mod.dead_xray_native("HealthyNative")
        self.assertNotIn(("systemctl","stop","xray-manual-test.timer"),self.commands)

    def test_watchdog_on_healthy_awg_does_not_stop_it(self):
        def awg_cmd(*a,**kw):
            self.commands.append(a)
            if a[1]=="get":return "awg"
            if a[1]=="check":return "healthy"
            raise AssertionError("attempted to modify healthy AWG")
        with mock.patch.object(mod,"cmd",side_effect=awg_cmd), \
             mock.patch.object(mod,"dead_xray_quiesce",new=ACTUAL_QUIESCE):
            mod.dead_xray_quiesce()
        self.assertEqual(len(self.commands),2)
        self.assertNotIn(("systemctl","stop",mod.XRAY),self.commands)

    def test_exhausted_healthy_awg_cannot_quiesce(self):
        with mock.patch.object(mod,"cmd",side_effect=lambda *args,**kwargs:
             "awg" if args[1]=="get" else ""):
            with self.assertRaisesRegex(RuntimeError,"ACTIVE_TRANSPORT_NOT_MIHOMO"):
                mod.dead_xray_exhausted()
        mod.dead_xray_quiesce.assert_not_called()

    def test_exhausted_healthy_old_tun_cannot_quiesce(self):
        with mock.patch.object(mod,"tun_runtime_ready",return_value=True):
            with self.assertRaisesRegex(RuntimeError,"CURRENT_XRAY_TUN_HEALTHY"):
                mod.dead_xray_exhausted()
        mod.dead_xray_quiesce.assert_not_called()

    def test_exhausted_failed_xray_enters_mode_guard(self):
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.dead_xray_exhausted()
        self.assertIn("QUIESCED_SAFE",buf.getvalue())
        mod.dead_xray_quiesce.assert_called_once()

    def test_preflight_and_abort_cli_status_are_distinct(self):
        with mock.patch.object(mod.sys,"argv",["helper","dead-xray-native","Node"]), \
             mock.patch.object(mod,"dead_xray_native",side_effect=mod.DeadXrayPreflight("XRAY_UNAVAILABLE")), \
             self.assertRaises(SystemExit) as raised:
            mod.main()
        self.assertEqual(raised.exception.code,2)
        with mock.patch.object(mod.sys,"argv",["helper","dead-xray-native","Node"]), \
             mock.patch.object(mod,"dead_xray_native",side_effect=mod.DeadXrayAbort("AWG_FALLBACK")), \
             self.assertRaises(SystemExit) as raised:
            mod.main()
        self.assertEqual(raised.exception.code,1)

if __name__=="__main__":
    unittest.main()
