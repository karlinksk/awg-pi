#!/usr/bin/env python3
"""Prove rollback tolerates formatting only, never settings/network changes."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
ROLL=ROOT/"scripts/awg-xray-testpi-tun-rollback.py"
FIX=ROOT/"scripts/awg-xray-testpi-rollback-finalize.py"
DIAG=ROOT/"scripts/awg-xray-testpi-rollback-diagnose.py"

def module_from(filename,name):
    spec=importlib.util.spec_from_file_location(name,filename)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

rollback=module_from(ROLL,"xray_rollback_semantic")
finalizer=module_from(FIX,"xray_rollback_finalizer")

class ReconciliationTests(unittest.TestCase):
    def test_backup_hash_stays_strict(self):
        good=b"proxy-groups:\n- name: AWG-MIHOMO\n  type: select\n"
        different=b"proxy-groups:\n- name: AWG-MIHOMO\n  type: url-test\n"
        with tempfile.TemporaryDirectory() as d:
            original=Path(d)/"old"
            current=Path(d)/"new"
            original.write_bytes(good)
            current.write_bytes(good)
            digest=hashlib.sha256(good).hexdigest()
            self.assertEqual(rollback.restored_config_status(original,current,digest),"BYTE_IDENTICAL")
            current.write_bytes(b"# regenerated\n"+good)
            self.assertEqual(rollback.restored_config_status(original,current,digest),"YAML_EQUIVALENT")
            current.write_bytes(different)
            self.assertEqual(rollback.restored_config_status(original,current,digest),"CONFIG_MISMATCH")
            self.assertEqual(rollback.restored_config_status(original,current,"f"*64),"BACKUP_HASH_MISMATCH")
    def test_finalizer_rejects_changed_provider_or_rules(self):
        old=b"rules:\n- MATCH,AWG-MIHOMO\n"
        fmt=b"# whitespace regeneration\n"+old
        changed=b"rules:\n- MATCH,DIRECT\n"
        digest=hashlib.sha256(old).hexdigest()
        self.assertEqual(finalizer.equivalent(old,fmt,digest),"YAML_EQUIVALENT")
        self.assertEqual(finalizer.equivalent(old,changed,digest),"CONTENT_DIFFERENT")
        self.assertEqual(finalizer.equivalent(old,fmt,"b"*64),"BACKUP_CORRUPT")
    def test_reconcile_writes_only_root_snapshot_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);snap=base/"xray-live-switch-20261019-210015";snap.mkdir()
            original=b"rules:\n- MATCH,AWG-MIHOMO\n"
            (snap/"config.previous").write_bytes(original)
            state={"state":"armed","old_config_sha256":hashlib.sha256(original).hexdigest()}
            (snap/"state.json").write_text(json.dumps(state))
            target=base/"config.yaml";target.write_bytes(b"# regenerated\n"+original)
            calls=[]
            def fake_command(*args,**kwargs):
                if args[0]=="hostname":
                    return subprocess.CompletedProcess(args,0,"awg-upgrade")
                raise AssertionError("Unexpected executable called:"+args[0])
            with (mock.patch.object(finalizer,"SNAP",snap),
                  mock.patch.object(finalizer,"CONFIG",target),
                  mock.patch.object(finalizer,"TIMER","test.timer"),
                  mock.patch.object(finalizer.os,"geteuid",return_value=0),
                  mock.patch.object(finalizer,"is_active",return_value=False),
                  mock.patch.object(finalizer,"command",side_effect=fake_command),
                  mock.patch.object(finalizer,"verify",return_value="YAML_EQUIVALENT"),
                  mock.patch.object(finalizer,"emit",side_effect=lambda *a:calls.append(a))):
                finalizer.finalize()
                self.assertEqual(json.loads((snap/"state.json").read_text())["state"],"restored")
                finalizer.finalize()
            self.assertEqual(target.read_bytes(),b"# regenerated\n"+original)
            self.assertIn(("NETWORK_MUTATION","NO"),calls)
            self.assertIn(("SNAPSHOT_STATE","ALREADY_RESTORED"),calls)
    def test_refuse_if_watchdog_is_active(self):
        with (mock.patch.object(finalizer.os,"geteuid",return_value=0),
              mock.patch.object(finalizer,"command",return_value=subprocess.CompletedProcess([],0,"awg-upgrade")),
              mock.patch.object(finalizer,"is_active",return_value=True)):
            with self.assertRaisesRegex(RuntimeError,"WATCHDOG_STILL_ACTIVE"):
                finalizer.finalize()
    def test_no_service_or_network_mutators(self):
        src=FIX.read_text()
        for banned in ('"restart"','"start"','"stop"','"disable"',
                       '"replace"','"route","add"','"node select-auto"',
                       '"systemd-run"','192.168.'):
            self.assertNotIn(banned,src)
        self.assertIn('os.replace(tmp,state_file)',src)
        self.assertIn('flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)',src)
        self.assertIn('TRANSIT_GUARD_UNSAFE',src)
        self.assertIn('TUN_OPENAI_NOT_REACHABLE',src)
        self.assertIn('ORIGINAL_NODE_NOT_RESTORED',src)
    def test_syntax(self):
        for path in (ROLL,FIX,DIAG):
            with self.subTest(path=path):
                p=subprocess.run([sys.executable,"-m","py_compile",str(path)],text=True,
                                 capture_output=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)

if __name__=="__main__":unittest.main()
