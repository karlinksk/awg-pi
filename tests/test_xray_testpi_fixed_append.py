#!/usr/bin/env python3
"""No production changes: isolated test-Pi guard staging and FIXED append mocks."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
STAGER=ROOT/"scripts/awg-xray-policy-guard-stage-testpi.sh"
APPEND=ROOT/"scripts/awg-xray-testpi-fixed-append.py"
spec=importlib.util.spec_from_file_location("safe_fixed_append",APPEND)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class TestGuards(unittest.TestCase):
    def test_legacy_policy_guard_install_is_purely_passive(self):
        src=STAGER.read_text()
        self.assertIn("OLD_SHA=3f89f667",src)
        self.assertIn('bash -n "$SOURCE"',src)
        self.assertIn("XRAY_TRANSACTION_NOT_CERTIFIED",src)
        self.assertIn("candidate_visits",src)
        self.assertIn('flock -x 9',src)
        self.assertIn("CURRENT_BEFORE",src)
        self.assertIn("ORDER_BEFORE",src)
        self.assertIn("XRAY_POLICY_GUARD_ROLLBACK=ATTEMPTED",src)
        self.assertNotIn("systemctl restart",src)
        self.assertNotIn("systemctl enable --now",src)
        self.assertNotIn("awg-transit-routing disable",src)
        self.assertNotIn("node select-auto",src)
        self.assertNotIn("192.168.",src)
        r=subprocess.run(["bash","-n",str(STAGER)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)

    def test_old_chain_has_to_remain_valid_and_ordered(self):
        self.assertTrue(m.check_policy("HY2",["HY2","BACKUP-A","BACKUP-B"]))
        self.assertTrue(m.check_policy("BACKUP-A",["HY2","BACKUP-A","BACKUP-B"]))
        self.assertFalse(m.check_policy("UNKNOWN",["HY2","BACKUP-A","BACKUP-B"]))
        self.assertFalse(m.check_policy("HY2",["HY2","BACKUP-A","HY2"]))
        self.assertFalse(m.check_policy("HY2",["HY2"]))

    def fixture(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root=Path(folder.name)
        files={}
        for key,val in dict(MODE="transit",POLICY_MODE="fixed",CURRENT="HY2",
                POLICY_CHAIN="HY2\nBACKUP-A\nBACKUP-B\n",
                ROOT_POLICY="same-source",SOURCE_POLICY="same-source",
                RESOLVER="mock-catalog",LOCK="",XRAY_SELECTION="",BRIDGE="").items():
            path=root/key
            if key not in ("XRAY_SELECTION","BRIDGE"):path.write_text(val.replace("\\n",chr(10)))
            files[key]=path
        backup=root/"backups";backup.mkdir()
        rows=[
            dict(index=1,name="HY2",engine="MIHOMO",basic_network="NETWORK_OK"),
            dict(index=2,name="BAD-X",engine="XRAY",basic_network="NETWORK_FAIL"),
            dict(index=3,name="VLESS-TEST",engine="XRAY",basic_network="NETWORK_OK"),
            dict(index=4,name="ANOTHER",engine="XRAY",basic_network="NETWORK_OK")
        ]
        provider=root/"provider.yaml";provider.write_text("fake-provider")
        adapter=types.SimpleNamespace(secure_read=lambda p:p.read_bytes())
        module=types.SimpleNamespace(PROVIDER=provider)
        calls=[]
        def fake_cmd(*args,timeout=8):
            calls.append(args)
            if args[0]=="systemctl":return "active"
            if args[0]=="ip":return "default dev mihomo0 scope link"
            if args[0]=="/usr/local/sbin/awg-transit-routing":
                return "Transit guard: SAFE\nTransit policy rule: ACTIVE\nTransit VPN table: READY"
            raise AssertionError("unmocked "+str(args))
        patchers=[mock.patch.object(m,key,value) for key,value in files.items()]
        patchers += [mock.patch.object(m,"BACKUPS",backup),
                    mock.patch.object(m,"call",side_effect=fake_cmd),
                    mock.patch.object(m,"load_candidates",return_value=(rows,hashlib.sha256(provider.read_bytes()).hexdigest(),adapter,module)),
                    mock.patch.object(m.os,"geteuid",return_value=0),
                    mock.patch.object(m.socket,"gethostname",return_value="awg-upgrade"),
                    mock.patch.object(m.subprocess,"run",return_value=types.SimpleNamespace(returncode=1))]
        stack=contextlib.ExitStack()
        self.addCleanup(stack.close)
        for p in patchers:stack.enter_context(p)
        return files,backup,rows,calls

    def test_preview_preserves_fixed_and_mihomo(self):
        paths,backup,rows,calls=self.fixture()
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.execute(False)
        self.assertEqual(paths["POLICY_CHAIN"].read_text().splitlines(),["HY2","BACKUP-A","BACKUP-B"])
        self.assertEqual(list(backup.iterdir()),[])
        self.assertIn("XRAY_FIXED_ELIGIBLE_XRAY_CANDIDATES=2",out.getvalue())
        self.assertIn("XRAY_FIXED_PREVIEW=PASS",out.getvalue())
        self.assertNotIn("VLESS-TEST",out.getvalue())

    def test_append_only_after_last_original_reserve_and_backups(self):
        paths,backup,rows,calls=self.fixture()
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.execute(True)
        self.assertEqual(paths["POLICY_CHAIN"].read_text().splitlines(),
                         ["HY2","BACKUP-A","BACKUP-B","VLESS-TEST"])
        self.assertEqual(paths["CURRENT"].read_text(),"HY2")
        backups=list(backup.glob("xray-fixed-append-*"))
        self.assertEqual(len(backups),1)
        self.assertEqual((backups[0]/"node-policy.nodes").read_text().splitlines(),
                         ["HY2","BACKUP-A","BACKUP-B"])
        self.assertIn("XRAY_FIXED_CURRENT_SELECTED_CHANGED=NO",out.getvalue())
        self.assertNotIn("VLESS-TEST",out.getvalue())

    def test_no_fresh_evidence_cannot_append(self):
        paths,backup,rows,calls=self.fixture()
        rows[2]["basic_network"]="UNTESTED"
        rows[3]["basic_network"]="UNTESTED"
        with self.assertRaisesRegex(RuntimeError,"NO_FRESH"):
            m.execute(True)
        self.assertEqual(paths["POLICY_CHAIN"].read_text().splitlines(),
                         ["HY2","BACKUP-A","BACKUP-B"])
        self.assertEqual(list(backup.iterdir()),[])

    def test_policy_guard_must_already_be_installed(self):
        paths,backup,rows,calls=self.fixture()
        paths["ROOT_POLICY"].write_text("old-unguarded-version")
        with self.assertRaisesRegex(RuntimeError,"POLICY_GUARD_NOT_INSTALLED"):
            m.execute(True)
        self.assertEqual(list(backup.iterdir()),[])

    def test_provider_rotation_rejects_before_mutation(self):
        paths,backup,rows,calls=self.fixture()
        real=m.load_candidates
        def changed():
            x=real()
            return x[0],"0"*64,x[2],x[3]
        with mock.patch.object(m,"load_candidates",side_effect=changed):
            with self.assertRaisesRegex(RuntimeError,"PROVIDER_ROTATED"):
                m.execute(True)
        self.assertEqual(paths["POLICY_CHAIN"].read_text().splitlines(),
                         ["HY2","BACKUP-A","BACKUP-B"])

    def test_never_log_node_names_or_download_credentials(self):
        text=APPEND.read_text()
        self.assertIn('say("CHOSEN_PROVIDER_INDEX"',text)
        self.assertNotIn('say("NODE_NAME"',text)
        self.assertNotIn('node select-auto',text)
        self.assertNotIn('systemctl","restart"',text)
        self.assertNotIn('http://',text)
        p=subprocess.run([sys.executable,"-m","py_compile",str(APPEND)],
            capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

if __name__=="__main__":unittest.main()
