#!/usr/bin/env python3
"""Rootless negative tests: apply must arm watchdog before restarting Mihomo."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/awg-xray-bridge-reload-test.py"
spec=importlib.util.spec_from_file_location("xray_bridge_stage",SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class BridgeReload(unittest.TestCase):
    def test_does_not_change_router_or_transport_or_dns(self):
        source=SCRIPT.read_text()
        self.assertIn("AUTONOMOUS_WATCHDOG_NOT_ARMED",source)
        self.assertIn("XRAY_BRIDGE_ROLLBACK=VERIFIED",source)
        self.assertIn('run("systemctl","restart",SERVICE',source)
        self.assertIn('run("systemd-run"',source)
        for unsafe in ("awg-transport select","awg-route mode","nft add","nft flush",
                       "systemctl restart dnsmasq","systemctl restart ssh"):
            self.assertNotIn(unsafe,source)

    def test_nonroot_preflight_rejected(self):
        with mock.patch.object(mod.os,"geteuid",return_value=1000):
            with self.assertRaisesRegex(RuntimeError,"ROOT_REQUIRED"):
                mod.sanity()

    def test_preflight_rejects_other_host(self):
        with mock.patch.object(mod.os,"geteuid",return_value=0), \
             mock.patch.object(mod.socket,"gethostname",return_value="production"):
            with self.assertRaisesRegex(RuntimeError,"WRONG_HOST"):
                mod.sanity()

    def test_watchdog_disarmed_never_mutates_active_config(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            backup=d/"original.yaml";backup.write_bytes(b"existing configuration")
            fake_conf=d/"live.yaml";fake_conf.write_bytes(b"original production")
            fake_lock=d/"maintenance.lock"
            fake_new=d/"new.yaml";fake_new.write_bytes(b"staged candidate")
            info={"phase":"pending","previous":"HEALTHY-NATIVE",
                  "mode":"transit","watch":"awg-xray-bridge-test"}
            fake_mode=d/"mode";fake_mode.write_text("transit")
            calls=[]
            def fake_run(*args,**kwargs):
                calls.append(args);return ""
            def fake_state(folder,state):
                (folder/"state.json").write_text(str(state))
            with mock.patch.multiple(mod,LOCK=fake_lock,CONF=fake_conf,
                MODE=fake_mode,TRANSPORT=d/"transport"), \
                 mock.patch.object(mod,"sanity",return_value="HEALTHY-NATIVE"), \
                 mock.patch.object(mod,"stable_snapshot",return_value=d), \
                 mock.patch.object(mod,"make_config",return_value=fake_new), \
                 mock.patch.object(mod,"run",side_effect=fake_run), \
                 mock.patch.object(mod,"active",return_value=False), \
                 mock.patch.object(mod,"restore"), \
                 mock.patch.object(mod,"save_state",side_effect=fake_state):
                with self.assertRaisesRegex(RuntimeError,"AUTONOMOUS_WATCHDOG_NOT_ARMED"):
                    mod.do_apply()
                self.assertEqual(fake_conf.read_bytes(),b"original production")
                self.assertFalse(any(c[:2]==("systemctl","restart") for c in calls))

    def test_untrusted_recovery_path_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"fake-untrusted-directory"
            with self.assertRaisesRegex(RuntimeError,"UNTRUSTED_SNAPSHOT"):
                mod.recover(p)

    def test_completed_watchdog_does_not_restart(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            snap=d/"xray-bridge-123-456";snap.mkdir()
            (snap/"state.json").write_text('{"phase":"committed"}')
            original_stat=type(snap).stat
            def root_owned_snap(path,*args,**kwargs):
                if path==snap:
                    from types import SimpleNamespace
                    return SimpleNamespace(st_uid=0,st_mode=original_stat(path,*args,**kwargs).st_mode)
                return original_stat(path,*args,**kwargs)
            with mock.patch.multiple(mod,BASE=d,LOCK=d/"test.lock"), \
                 mock.patch.object(type(snap),"stat",autospec=True,side_effect=root_owned_snap), \
                 mock.patch.object(mod,"restore") as restore:
                mod.recover(snap)
                restore.assert_not_called()

    def test_rollback_holds_original_execstartpre_override_through_restart(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            snap=d/"snap";snap.mkdir()
            (snap/"original.yaml").write_bytes(b"old baseline")
            live=d/"active.yaml";live.write_bytes(b"new candidate")
            transport=d/"transport";transport.write_text("mihomo")
            mode=d/"mode";mode.write_text("transit")
            override=d/"rollback.conf"
            seen=[]
            def simulated_systemctl(*args,**kwargs):
                if args[:2]==("systemctl","restart"):
                    self.assertEqual(live.read_bytes(),b"old baseline")
                    self.assertEqual(override.read_bytes(),mod.ROLLBACK_OVERRIDE_CONTENT)
                seen.append(args)
                return ""
            with mock.patch.multiple(mod,CONF=live,TRANSPORT=transport,MODE=mode,
                                     ROLLBACK_OVERRIDE=override), \
                 mock.patch.object(mod,"run",side_effect=simulated_systemctl), \
                 mock.patch.object(mod,"wait_ready"):
                mod.restore(snap,{"mode":"transit","previous":"NATIVE"})
            self.assertEqual(live.read_bytes(),b"old baseline")
            self.assertFalse(override.exists())
            self.assertEqual([a[1] for a in seen],["daemon-reload","restart","daemon-reload"])

    def test_rollback_restores_config_and_requires_live_proof(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            snap=d/"snap";snap.mkdir()
            (snap/"original.yaml").write_bytes(b"original config")
            live=d/"live.yaml";live.write_bytes(b"modified config")
            transport=d/"transport";transport.write_text("mihomo")
            mode=d/"mode";mode.write_text("transit")
            calls=[]
            def fake_run(*args,**kwargs):
                calls.append(args);return ""
            with mock.patch.multiple(mod,CONF=live,TRANSPORT=transport,MODE=mode,ROLLBACK_OVERRIDE=d/"rollback-override.conf"), \
                 mock.patch.object(mod,"run",side_effect=fake_run), \
                 mock.patch.object(mod,"wait_ready") as checker:
                mod.restore(snap,{"mode":"transit","previous":"NATIVE"})
                self.assertEqual(live.read_bytes(),b"original config")
                self.assertIn(("systemctl","restart",mod.SERVICE),calls)
                self.assertEqual(calls[0][:2],("systemctl","daemon-reload"))
                self.assertEqual(calls[1][:2],("systemctl","restart"))
                self.assertEqual(calls[-1][:2],("systemctl","daemon-reload"))
                self.assertFalse((d/"rollback-override.conf").exists())
                checker.assert_called_once_with("NATIVE",False)

if __name__=="__main__":unittest.main()
