#!/usr/bin/env python3
"""Regression: an AUTO-owned Xray bridge can return to native without killing Mihomo."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE=Path(__file__).resolve().parents[1]/"src/awg-xray-manual-switch.py"
spec=importlib.util.spec_from_file_location("xray_native_auto_return_test",SOURCE)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)
REAL_SAVE_SNAP=m.save_snap
REAL_OWNED_AUTO_BRIDGE=m.owned_auto_bridge


class AutoBridgeNativeReturn(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.auto_boot=self.base/"etc"/"61-auto"
        self.auto_runtime=self.base/"run"/"61-auto"
        self.boot=self.base/"etc"/"62-manual"
        self.mode=self.base/"mode"
        self.mode.write_text("transit")
        self.provider=self.base/"provider"
        self.provider.write_bytes(b"example")
        self.lock=self.base/"maintenance.lock"
        self.selected=self.base/"selected"
        self.selected.write_text(json.dumps({"sha256":"a"*64}))
        self.current=self.base/"current"
        self.current.write_text("old\n")
        self.endpoint=self.base/"endpoint"
        self.endpoint.write_text("198.51.100.2\n")
        self.egress=self.base/"egress"
        self.config=self.base/"config"
        self.env=self.base/"env"
        self.policy=self.base/"policy"
        self.order=self.base/"order"
        self.root=self.base/"backups"
        self.snap=self.root/"snapshot"
        self.snap.mkdir(parents=True)
        self.text=b'[Unit]\nRequires=awg-xray-vless.service\nAfter=awg-xray-vless.service\nEnvironment="MIHOMO_XRAY_VLESS_BRIDGE=1"\n'
        for f in (self.auto_boot,self.auto_runtime):
            f.parent.mkdir(parents=True,exist_ok=True)
            f.write_bytes(self.text)
        for n in ("auto-boot.prev","auto-runtime.prev"):
            (self.snap/n).write_bytes(self.text)
        self.native=True
        self.xray=True
        self.graph=True
        self.stubborn=False
        self.calls=[]
        self.phases=[]
        self.info={"candidate":"NativeNew","previous":m.ALIAS,
                   "previous_xray":True,"auto_bridge":True,
                   "xray_enabled":True,"xray_active":True,
                   "filter":"test","endpoint":"198.51.100.3",
                   "sha":hashlib.sha256(self.provider.read_bytes()).hexdigest()}
        self.state={"watchdog":"awg-xray-manual-test",
                    "previous":m.ALIAS,
                    "previous_xray":True,"auto_bridge":True,"xray_enabled":True}
        self.patches=[
            mock.patch.object(m,"AUTO_BOOT",self.auto_boot),
            mock.patch.object(m,"AUTO_RUNTIME",self.auto_runtime),
            mock.patch.object(m,"BOOT",self.boot),
            mock.patch.object(m,"CURRENT",self.current),
            mock.patch.object(m,"MIHOMO_ENDPOINT",self.endpoint),
            mock.patch.object(m,"MIHOMO_EGRESS",self.egress),
            mock.patch.object(m,"SELECTED",self.selected),
            mock.patch.object(m,"MIHOMO_ENV",self.env),
            mock.patch.object(m,"MIHOMO_CONFIG",self.config),
            mock.patch.object(m,"POLICY",self.policy),
            mock.patch.object(m,"ORDER",self.order),
            mock.patch.object(m,"PROVIDER",self.provider),
            mock.patch.object(m,"MODE",self.mode),
            mock.patch.object(m,"LOCK",self.lock),
            mock.patch.object(m,"ROOT",self.root),
            mock.patch.object(m,"cmd",side_effect=self.fake_cmd),
            mock.patch.object(m,"unit_active",side_effect=self.active),
            mock.patch.object(m,"inspect_native",return_value=self.info),
            mock.patch.object(m,"preflight_mihomo"),
            mock.patch.object(m,"candidate_native",return_value=self.info),
            mock.patch.object(m,"save_snap",return_value=(self.snap,self.state)),
            mock.patch.object(m,"checkpoint",side_effect=self.checkpoint),
            mock.patch.object(m,"stored",side_effect=lambda p,s,phase:self.phases.append(phase)),
            mock.patch.object(m,"native_env"),
            mock.patch.object(m,"wait_native_controller"),
            mock.patch.object(m,"choose"),
            mock.patch.object(m,"prove_local_xray"),
            mock.patch.object(m,"native_runtime_proof",side_effect=self.local_proof),
            mock.patch.object(m,"invariant",side_effect=self.local_proof),
            mock.patch.object(m,"controller",return_value={"now":"NativeNew"}),
            mock.patch.object(m,"owned_auto_bridge",return_value=True),
            mock.patch.object(m.os,"geteuid",return_value=0)
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def active(self,unit):
        if unit==m.MIHOMO:return self.native
        if unit==m.XRAY:return self.xray
        if unit=="awg-xray-manual-test.timer":return True
        raise AssertionError("Unexpected unit "+str(unit))

    def local_proof(self):
        if not self.native:raise RuntimeError("NATIVE_SERVICE_STOPPED")
        return True

    def checkpoint(self,path,state,name):
        state["checkpoint"]=name
        self.phases.append(name)

    def fake_cmd(self,*args,**kwargs):
        self.calls.append(args)
        if args==("/usr/local/sbin/awg-transport","get"):
            return "mihomo"
        if args[:2]==("systemctl","show"):
            return m.XRAY if self.graph else ""
        if args==("systemctl","daemon-reload"):
            if not self.stubborn:
                self.graph=self.auto_boot.exists() or self.auto_runtime.exists()
            return ""
        if args==("systemctl","stop",m.MIHOMO):
            self.native=False
            return ""
        if args==("systemctl","start",m.MIHOMO):
            self.native=True
            return ""
        if args==("systemctl","stop",m.XRAY):
            if self.graph:self.native=False
            self.xray=False
            return ""
        if args==("systemctl","start",m.XRAY):
            self.xray=True
            return ""
        if args[0] in ("systemd-run","/usr/local/sbin/awg-mihomo-prepare"):
            return ""
        if args[:2]==("systemctl","disable") or args[:2]==("systemctl","enable"):
            return ""
        if args==("systemctl","stop","awg-xray-manual-test.timer"):
            return ""
        if args[:2]==("/usr/local/sbin/awg-transit-routing","disable") or args[:2]==("/usr/local/sbin/awg-transit-routing","apply"):
            return ""
        raise AssertionError("Unexpected subprocess: "+repr(args))

    def test_committed_auto_bridge_detached_before_stopping_xray(self):
        m.native_return("NativeNew")
        self.assertFalse(self.xray)
        self.assertTrue(self.native)
        self.assertFalse(self.graph)
        self.assertFalse(self.auto_boot.exists())
        self.assertFalse(self.auto_runtime.exists())
        self.assertIn("committed",self.phases)
        reload_at=self.calls.index(("systemctl","daemon-reload"))
        stop_at=self.calls.index(("systemctl","stop",m.XRAY))
        self.assertLess(reload_at,stop_at)
        self.assertTrue(any(c[:2]==("systemctl","show") for c in self.calls[reload_at+1:stop_at]))

    def test_loaded_dependency_refuses_to_stop_xray(self):
        self.stubborn=True
        with mock.patch.object(m,"restore_native") as rescue:
            with self.assertRaisesRegex(RuntimeError,"AUTO_XRAY_DEPENDENCY_NOT_DETACHED"):
                m.native_return("NativeNew")
        rescue.assert_called_once()
        self.assertNotIn(("systemctl","stop",m.XRAY),self.calls)
        self.assertTrue(self.xray)

    def test_real_snapshot_captures_both_auto_dropins(self):
        snapshot, state=REAL_SAVE_SNAP(self.info)
        self.assertEqual((snapshot/"auto-boot.prev").read_bytes(),self.text)
        self.assertEqual((snapshot/"auto-runtime.prev").read_bytes(),self.text)
        self.assertEqual(state["auto_bridge"],True)

    def test_incomplete_auto_dropin_is_rejected(self):
        self.auto_runtime.unlink()
        with mock.patch.object(m,"owned_auto_bridge",
                               side_effect=REAL_OWNED_AUTO_BRIDGE):
            with self.assertRaisesRegex(RuntimeError,"AUTO_XRAY_BRIDGE_INCOMPLETE"):
                m.owned_auto_bridge()

    def test_manual_boot_without_auto_dropins_keeps_legacy_return(self):
        self.auto_boot.unlink()
        self.auto_runtime.unlink()
        self.graph=False
        self.info["auto_bridge"]=False
        self.state["auto_bridge"]=False
        with mock.patch.object(m,"owned_auto_bridge",return_value=False):
            m.native_return("NativeNew")
        self.assertTrue(self.native)
        self.assertFalse(self.xray)
        self.assertIn("committed",self.phases)

    def test_auto_bridge_snapshot_restored_on_rollback(self):
        self.auto_boot.unlink()
        self.auto_runtime.unlink()
        self.graph=False
        # Restore native runs under a mocked systemd; snapshot should restore
        # both unit files before daemon-reload and restart.
        self.info["auto_bridge"]=True
        m.restore_native(self.snap,{"previous_xray":True,"auto_bridge":True,
                                    "previous":m.ALIAS,"xray_enabled":True})
        self.assertEqual(self.auto_boot.read_bytes(),self.text)
        self.assertEqual(self.auto_runtime.read_bytes(),self.text)
        self.assertTrue(self.graph)
        self.assertTrue(self.native)

if __name__=="__main__":
    unittest.main()
