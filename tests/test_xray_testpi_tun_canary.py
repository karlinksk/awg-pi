#!/usr/bin/env python3
"""Regression gates for opt-in REAL Mihomo-TUN Xray canary and rollback.

These rootless tests cannot confer a hardware PASS. The canary requires
explicit user invocation and must not be wired into FIXED/AUTO or installer.
"""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
CANARY=ROOT/"scripts/awg-xray-testpi-tun-canary.py"
ROLLBACK=ROOT/"scripts/awg-xray-testpi-tun-rollback.py"

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

canary=load("awg_tun_canary_v13",CANARY)
rollback=load("awg_tun_canary_rollback_v13",ROLLBACK)

class CanarySafetyTests(unittest.TestCase):
    def test_exact_xray_is_provider_sha_and_network_bound(self):
        sha="a"*64
        def make(fields):
            return types.SimpleNamespace(returncode=0,stdout="".join(k+"="+v+"\n" for k,v in fields.items()))
        good=dict(NODE_ENGINE="XRAY",NODE_BASIC_NETWORK="NETWORK_OK",NODE_PROVIDER_SHA256=sha,NODE_INDEX="3")
        with mock.patch.object(canary,"proc",return_value=make(good)):
            self.assertEqual(canary.resolve_fixed_xray("test-xray",sha),"3")
        for bad in (
            {**good,"NODE_ENGINE":"MIHOMO"},
            {**good,"NODE_BASIC_NETWORK":"UNTESTED"},
            {**good,"NODE_BASIC_NETWORK":"NETWORK_FAIL"},
            {**good,"NODE_PROVIDER_SHA256":"b"*64},
            {**good,"NODE_INDEX":"none"}
        ):
            with self.subTest(bad=bad), mock.patch.object(canary,"proc",return_value=make(bad)):
                with self.assertRaises(RuntimeError):
                    canary.resolve_fixed_xray("test-xray",sha)
        with mock.patch.object(canary,"proc",return_value=types.SimpleNamespace(returncode=1,stdout="")):
            with self.assertRaises(RuntimeError):
                canary.resolve_fixed_xray("test-xray",sha)

    def test_real_canary_is_explicit_and_reverts_to_healthy_incumbent(self):
        script=CANARY.read_text()
        self.assertIn('--confirm-live-transit',script)
        self.assertIn('EXPLICIT_CONFIRM_REQUIRED',script)
        self.assertIn('"--on-active=300s"',script)
        self.assertIn('ROLLBACK_RUNTIME.parent.mkdir',script)
        self.assertIn('ROLLBACK_SOURCE.read_bytes()',script)
        self.assertIn('ROLLBACK_WATCHDOG=ARMED_300S',script)
        self.assertIn('fixed[-1]',script)
        self.assertIn('resolve_fixed_xray(candidate,before_provider_hash)',script)
        self.assertIn('choose(LOCAL)',script)
        self.assertIn('https("mihomo0")',script)
        self.assertIn('choose(chosen)',script)
        self.assertIn("TRANSIT_GUARD_NOT_SAFE",script)
        self.assertIn("CURRENT_SELECTED_NODE_MISMATCH",script)
        self.assertIn("XRAY_BRIDGE_ALREADY_INSTALLED",script)
        self.assertIn('LIVE_CANARY_RESTORED=PASS',script)
        self.assertIn('if rolled.returncode!=0:raise RuntimeError("ROLLBACK_INCOMPLETE")',script)
        self.assertNotIn('192.168.',script)
        self.assertNotIn('dab288bf',script)
        self.assertNotIn('MIHOMO_READY_AUTO=1',script)
        self.assertNotIn('node select-auto',script)
        self.assertNotIn('awg-transit-routing","disable"',script)

    def test_recovered_live_yaml_may_be_equivalent_but_backup_must_be_exact(self):
        import hashlib
        original=b'proxies:\n  - name: HY2\n    type: hysteria2\n'
        alternate=b'# ExecStartPre regenerated\n'+original
        changed=b'proxies:\n  - name: Xray\n    type: socks5\n'
        with tempfile.TemporaryDirectory() as d:
            backup=Path(d)/"previous"
            current=Path(d)/"current"
            backup.write_bytes(original)
            baseline=hashlib.sha256(original).hexdigest()
            current.write_bytes(original)
            self.assertEqual(canary.restored_config_proof(backup,current,baseline),"BYTE_IDENTICAL")
            current.write_bytes(alternate)
            self.assertEqual(canary.restored_config_proof(backup,current,baseline),"YAML_EQUIVALENT")
            current.write_bytes(changed)
            self.assertEqual(canary.restored_config_proof(backup,current,baseline),"CONFIG_DIFFERENT")
            current.write_bytes(alternate)
            self.assertEqual(canary.restored_config_proof(backup,current,"0"*64),"BACKUP_HASH_INVALID")

    def test_success_requires_restored_snapshot_and_semantically_verified_config(self):
        source=CANARY.read_text()
        self.assertIn('verified_state.get("state")=="restored"',source)
        self.assertIn('restored_config_proof(snap/"config.previous",CONF,before_config_hash)',source)
        self.assertIn('"RESTORED_CONFIG_"+proof',source)
        self.assertNotIn('"RESTORED_CONFIG_SHA_MISMATCH"',source)

    def test_rollback_is_independent_and_idempotent(self):
        text=ROLLBACK.read_text()
        self.assertIn('state.get("state")=="restored"',text)
        self.assertIn('state.get("state")!="armed"',text)
        self.assertIn('LIVE_CANARY_ROLLBACK=RESTORED',text)
        self.assertIn('CONFIG.read_bytes()',text)
        self.assertIn('previous_group',text)
        self.assertIn('ROUTE_DEFAULTS_MISSING',text)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            snap=root/"xray-live-switch-demo";snap.mkdir()
            (snap/"state.json").write_text(json.dumps({"state":"restored"}))
            with (mock.patch.object(rollback,"ROOT",root),
                  mock.patch.object(rollback.os,"geteuid",return_value=0),
                  mock.patch.object(rollback.sys,"argv",["rollback",str(snap)]),
                  mock.patch("sys.stdout",new_callable=io.StringIO) as out):
                rollback.main()
                self.assertIn("ALREADY_RESTORED",out.getvalue())

    def test_python_syntax_both(self):
        for path in (CANARY,ROLLBACK):
            with self.subTest(path=path):
                r=subprocess.run([sys.executable,"-m","py_compile",str(path)],
                  text=True,capture_output=True,timeout=10)
                self.assertEqual(r.returncode,0,r.stderr)

    def test_not_auto_installed_or_invoked(self):
        installer=(ROOT/"install.sh").read_text()
        policy=(ROOT/"src/awg-mihomo-node-policy").read_text()
        self.assertNotIn(CANARY.name,installer)
        self.assertNotIn(CANARY.name,policy)
        self.assertNotIn(ROLLBACK.name,installer)

if __name__=="__main__":unittest.main()
