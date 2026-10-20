#!/usr/bin/env python3
"""Rootless contracts for clearing ONLY dormant test-Pi Xray menu selection."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/awg-xray-testpi-staged-selection-clear.py"
spec=importlib.util.spec_from_file_location("xray_staged_selection_clear",SCRIPT)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

REAL_READ_MARKER=m.read_marker

class StagedSelectionClear(unittest.TestCase):
    def fixture(self,mode="valid"):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        root=Path(t.name)
        folder=root/"selection";folder.mkdir(mode=0o700)
        file=folder/"selected.json"
        contents=json.dumps({"version":1,"sha256":"a"*64}).encode()
        if mode=="valid":file.write_bytes(contents);file.chmod(0o600)
        elif mode=="invalid":file.write_text("{}");file.chmod(0o600)
        backups=root/"backups";backups.mkdir()
        lock=root/"maintenance.lock"
        s=[]
        real_require=m.require
        def rootless_require(ok,label):
            if label=="BACKUP_LOCATION_UNSAFE":return
            return real_require(ok,label)
        patches=[
            mock.patch.object(m,"require",side_effect=rootless_require),
            mock.patch.object(m,"SELECTED",file),
            mock.patch.object(m,"BACKUPS",backups),
            mock.patch.object(m,"LOCK",lock),
            mock.patch.object(m,"healthy_state",return_value=(("mihomo0","mihomo0"),"a"*64,"b"*64)),
            mock.patch.object(m,"emit",side_effect=lambda *arg:s.append(arg)),
            mock.patch.object(m,"read_marker",side_effect=lambda: file.read_bytes() if file.exists() else None),
            mock.patch.object(m,"args",types.SimpleNamespace(check=False,clear=True),create=True),
        ]
        stack=self.enterContext
        for item in patches:stack(item)
        return file,backups,contents,s

    def test_backup_and_atomic_clear_preserves_live_state(self):
        file,backups,contents,log=self.fixture()
        with mock.patch.object(m.os,"geteuid",return_value=0):
            m.clear()
        self.assertFalse(file.exists())
        folders=list(backups.glob("xray-staged-selection-*"))
        self.assertEqual(len(folders),1)
        self.assertEqual((folders[0]/"selected.json").read_bytes(),contents)
        self.assertIn(("RESULT","PASS"),log)
        self.assertIn(("SERVICES_RESTARTED","NO"),log)

    def test_check_does_not_clear_selected(self):
        file,backups,contents,log=self.fixture()
        with mock.patch.object(m,"args",types.SimpleNamespace(check=True,clear=False)):
            m.clear()
        self.assertEqual(file.read_bytes(),contents)
        self.assertEqual(list(backups.iterdir()),[])
        self.assertIn(("RESULT","READY_FOR_SAFE_CLEAR"),log)

    def test_already_cleared_is_idempotent(self):
        file,backups,contents,log=self.fixture(mode="absent")
        m.clear()
        self.assertIn(("RESULT","ALREADY_CLEAR"),log)
        self.assertEqual(list(backups.iterdir()),[])

    def test_reject_unreviewed_marker_format(self):
        file,backups,contents,log=self.fixture(mode="invalid")
        # Root-owned file checks are tested via simulated stat uid.
        with mock.patch.object(m.Path,"stat",autospec=True) as stat_mock:
            stat_mock.side_effect=lambda self,**kwargs: types.SimpleNamespace(
                st_uid=0,st_mode=(0o100000|0o600),st_size=40)
            with self.assertRaisesRegex(RuntimeError,"SELECTION_INVALID_FORMAT"):
                REAL_READ_MARKER()
        self.assertTrue(file.is_file())

    def test_postcheck_failure_restores_original_marker(self):
        file,backups,contents,log=self.fixture()
        with mock.patch.object(m,"healthy_state",side_effect=[
            (("mihomo0","mihomo0"),"a","b"),
            (("changed","changed"),"a","b"),
        ]):
            with self.assertRaisesRegex(RuntimeError,"POSTCHECK_TRANSPORT_CHANGED"):
                m.clear()
        self.assertEqual(file.read_bytes(),contents)
        self.assertIn(("ROLLBACK","STAGED_PROFILE_RESTORED"),log)

    def test_never_restart_or_change_routes(self):
        source=SCRIPT.read_text()
        for token in ('"systemctl","restart"','"systemctl","stop"',
                      '"ip","route","replace"','"ip","route","add"',
                      '"awg-mihomo-node-policy","select-auto"',
                      'os.system(','subprocess.Popen(', 'MIHOMO_READY_AUTO=1'):
            self.assertNotIn(token,source)
        self.assertIn('BACKUP_VERIFICATION_FAILED',source)
        self.assertIn('XRAY_ROLLBACK_TIMER_PRESENT',source)
        self.assertIn('TRANSIT_GUARD_UNSAFE',source)

    def test_python_syntax(self):
        p=subprocess.run([sys.executable,"-m","py_compile",str(SCRIPT)],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)

if __name__=="__main__":
    unittest.main()
