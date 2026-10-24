#!/usr/bin/env python3
"""Rootless regression for guarded AWG-owned stale-Xray dependency cleanup."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"src"/"awg-xray-live-backend.py"
spec=importlib.util.spec_from_file_location("stale_awg_backend",PATH)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

class StaleXrayCleanupTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        self.base=root/"backups"
        self.base.mkdir()
        self.bridge=root/"etc"/"61-awg-xray-bridge.conf"
        self.runtime=root/"run"/"61-awg-xray-bridge.conf"
        self.selected=root/"state"/"selected.json"
        self.lock=root/"maintenance.lock"
        data=(b'[Unit]\nRequires=awg-xray-vless.service\n'
              b'After=awg-xray-vless.service\n[Service]\n'
              b'Environment="MIHOMO_XRAY_VLESS_BRIDGE=1"\n')
        for file in (self.bridge,self.runtime,self.selected):
            file.parent.mkdir(parents=True,exist_ok=True)
            file.write_bytes(data if file!=self.selected else b'{"sha256":"proof"}')
        self.original={p:p.read_bytes() for p in (self.bridge,self.runtime,self.selected)}
        self.mode=root/"mode"
        self.mode.write_text("transit")
        self.xray_running=True
        self.mihomo_running=False
        self.xray_enabled=True
        self.loaded_requires=True
        self.freeze_requires=False
        self.calls=[]
        self.patches=[
            mock.patch.object(m,"BRIDGE",self.bridge),
            mock.patch.object(m,"BRIDGE_RUNTIME",self.runtime),
            mock.patch.object(m,"SELECTED",self.selected),
            mock.patch.object(m,"MAINTENANCE_LOCK",self.lock),
            mock.patch.object(m,"BASE",self.base),
            mock.patch.object(m,"MODE",self.mode),
            mock.patch.object(m,"root_owned_regular",
                              side_effect=lambda p:p.is_file() and not p.is_symlink()),
            mock.patch.object(m,"verified_awg_backup_safe",return_value=True),
            mock.patch.object(m,"active",side_effect=self.active),
            mock.patch.object(m,"run",side_effect=self.run),
            mock.patch.object(m.os,"geteuid",return_value=0),
            mock.patch.object(m.socket,"gethostname",return_value="awg-upgrade"),
            mock.patch.dict(os.environ,{"AWG_XRAY_STALE_CLEANUP":"TEST_PI_AUTHORIZED"})
        ]
        for patch in self.patches:
            patch.start();self.addCleanup(patch.stop)
    def active(self,name):
        if name==m.MIHOMO:return self.mihomo_running
        if name==m.XRAY:return self.xray_running
        if name in ("ssh.service","dnsmasq.service"):return True
        raise AssertionError("Unexpected unit "+str(name))
    def run(self,*args,**kwargs):
        self.calls.append(args)
        if args[:2]==("systemctl","is-enabled"):
            return "enabled" if self.xray_enabled else "disabled"
        if args[:2]==("systemctl","show"):
            return m.XRAY if self.loaded_requires else ""
        if args==("systemctl","daemon-reload"):
            if not self.freeze_requires:
                self.loaded_requires=self.bridge.exists() or self.runtime.exists()
            return ""
        if args==("systemctl","stop",m.XRAY):
            self.xray_running=False
            return ""
        if args==("systemctl","disable",m.XRAY):
            self.xray_enabled=False
            return ""
        if args==("systemctl","enable",m.XRAY):
            self.xray_enabled=True
            return ""
        if args==("systemctl","start",m.XRAY):
            self.xray_running=True
            return ""
        raise AssertionError("Unexpected command: "+repr(args))

    def test_detach_graph_before_stopping_sidecar(self):
        m.cleanup_stale_xray_while_awg()
        self.assertFalse(any(p.exists() for p in self.original))
        self.assertFalse(self.xray_running)
        self.assertFalse(self.xray_enabled)
        self.assertFalse(self.mihomo_running)
        reload_idx=self.calls.index(("systemctl","daemon-reload"))
        stop_idx=self.calls.index(("systemctl","stop",m.XRAY))
        self.assertLess(reload_idx,stop_idx)
        self.assertIn(("systemctl","show",m.MIHOMO,"-p","Requires","--value"),
                      self.calls[reload_idx+1:stop_idx])
        snapshots=list(self.base.glob("xray-stale-awg-*"))
        self.assertEqual(len(snapshots),1)
        self.assertTrue((snapshots[0]/"committed").exists())

    def test_live_mihomo_refuses_without_mutation(self):
        self.mihomo_running=True
        with self.assertRaisesRegex(RuntimeError,"STALE_CLEANUP_BASELINE_UNSAFE"):
            m.cleanup_stale_xray_while_awg()
        self.assertEqual(self.calls,[])
        for p,data in self.original.items():self.assertEqual(p.read_bytes(),data)

    def test_unconfirmed_detach_restores_owned_files_without_stopping_xray(self):
        self.freeze_requires=True
        with self.assertRaisesRegex(RuntimeError,"STALE_CLEANUP_DEPENDENCY_NOT_DETACHED"):
            m.cleanup_stale_xray_while_awg()
        self.assertNotIn(("systemctl","stop",m.XRAY),self.calls)
        self.assertTrue(self.xray_running)
        self.assertTrue(self.xray_enabled)
        for p,data in self.original.items():self.assertEqual(p.read_bytes(),data)

    def test_foreign_bridge_refuses_without_mutation(self):
        self.runtime.write_bytes(b"FOREIGN_UNIT\n")
        with self.assertRaisesRegex(RuntimeError,"STALE_CLEANUP_FOREIGN_BRIDGE"):
            m.cleanup_stale_xray_while_awg()
        self.assertFalse(self.calls)
        self.assertTrue(self.xray_running)

if __name__=="__main__":unittest.main()
