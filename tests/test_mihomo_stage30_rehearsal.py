#!/usr/bin/env python3
import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path

p=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-stage30-rehearsal.py"
spec=importlib.util.spec_from_file_location("stage30",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.root=Path(self.t.name)/"private"
        self.root.mkdir(mode=0o700)
        self.source=Path(self.t.name)/"source"
        self.source.write_text("sample value")
    def tearDown(self):
        self.t.cleanup()
    def test_copy_and_recovery_without_source_mutation(self):
        before=m.digest(self.source)
        records=m.secure_snapshot([str(self.source)],self.root)
        self.assertEqual(m.rehearse_rollback(records,self.root),1)
        m.assert_sources_unchanged(records)
        self.assertEqual(before,m.digest(self.source))
    def test_private_snapshot_mode(self):
        records=m.secure_snapshot([str(self.source)],self.root)
        self.assertEqual(stat.S_IMODE(records[0][1].stat().st_mode),0o600)
    def test_symlink_refusal(self):
        alias=Path(self.t.name)/"link"
        alias.symlink_to(self.source)
        with self.assertRaises(ValueError):
            m.secure_snapshot([str(alias)],self.root)
    def test_missing_required(self):
        absent=str(Path(self.t.name)/"missing")
        with self.assertRaises(FileNotFoundError):
            m.secure_snapshot([absent],self.root,[absent])
    def test_optional_absent(self):
        missing=Path(self.t.name)/"missing"
        records=m.secure_snapshot([str(self.source),str(missing)],self.root)
        self.assertEqual(m.rehearse_rollback(records,self.root),1)
        m.assert_sources_unchanged(records)
    def test_changed_source_detected(self):
        records=m.secure_snapshot([str(self.source)],self.root)
        self.source.write_text("altered")
        with self.assertRaises(RuntimeError):
            m.assert_sources_unchanged(records)

if __name__=="__main__":
    unittest.main()
