#!/usr/bin/env python3
"""Rootless bounded discovery regressions; no real subscription or network."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import subprocess
import types
import unittest
from unittest import mock

SRC=Path(__file__).resolve().parents[1]/"scripts"/"awg-xray-testpi-discover.py"
spec=importlib.util.spec_from_file_location("xray_bounded_discovery",SRC)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

def node(i,health="UNTESTED",engine="XRAY"):
    return {"index":i,"basic_network":health,"engine":engine}

class IsolatedXrayDiscoveryTests(unittest.TestCase):
    def execute(self,rows,after=None,first_sha="1"*64,final_sha=None,limit=4):
        calls=[]
        def subprocess_mock(args,timeout):
            calls.append((args,timeout))
            return types.SimpleNamespace(returncode=0,stdout="",stderr="")
        snapshots=[(None,rows,first_sha),
                   (None,after if after is not None else rows,final_sha or first_sha)]
        stdout=io.StringIO()
        with (mock.patch.object(m,"valid_roots",return_value=(True,"PASS")),
              mock.patch.object(m,"snapshot",side_effect=snapshots),
              contextlib.redirect_stdout(stdout)):
            code=m.scan(limit,scanner=subprocess_mock)
        return code,calls,stdout.getvalue()

    def test_only_bounded_unverified_xray_probed(self):
        profiles=[node(1,engine="MIHOMO"),node(2,health="NETWORK_FAIL"),
                  node(3),node(4),node(5),node(6),node(7),node(8)]
        code,calls,out=self.execute(profiles,limit=3)
        self.assertEqual(code,0)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],[str(m.LIVE),"probe","3","4","5"])
        self.assertIn("XRAY_DISCOVERY_SCAN_BATCH=3",out)
        self.assertIn("XRAY_DISCOVERY_FIXED_POLICY_CHANGED=NO",out)
        self.assertIn("XRAY_DISCOVERY_LIVE_SERVICE_CHANGED=NO",out)

    def test_cached_live_https_pass_stops_scan(self):
        profiles=[node(2,health="NETWORK_OK"),node(4)]
        code,calls,out=self.execute(profiles)
        self.assertEqual(code,0)
        self.assertEqual(calls,[])
        self.assertIn("XRAY_DISCOVERY_CANDIDATE_FOR_REVIEW=YES",out)
        self.assertIn("XRAY_DISCOVERY_SCAN_BATCH=0",out)

    def test_provider_changed_aborts_without_claiming_candidate(self):
        code,calls,out=self.execute([node(4)],final_sha="2"*64)
        self.assertEqual(code,1)
        self.assertIn("XRAY_DISCOVERY_SCAN_STATUS=PROVIDER_CHANGED_AFTER_PROBE",out)
        self.assertNotIn("CANDIDATE_FOR_REVIEW=YES",out)

    def test_probe_failure_is_not_pass(self):
        stdout=io.StringIO()
        with (mock.patch.object(m,"valid_roots",return_value=(True,"PASS")),
              mock.patch.object(m,"snapshot",return_value=(None,[node(7)],"a"*64)),
              contextlib.redirect_stdout(stdout)):
            code=m.scan(2,scanner=lambda a,timeout:types.SimpleNamespace(returncode=1))
        self.assertEqual(code,1)
        self.assertIn("XRAY_DISCOVERY_SCAN_STATUS=PROBE_FAILED_OR_PROVIDER_CHANGED",stdout.getvalue())

    def test_no_xray_is_not_a_pass(self):
        code,calls,out=self.execute([node(5,engine="MIHOMO")])
        self.assertEqual(code,0)
        self.assertEqual(calls,[])
        self.assertIn("XRAY_DISCOVERY_XRAY_PROFILE_COUNT=0",out)
        self.assertIn("XRAY_DISCOVERY_CANDIDATE_FOR_REVIEW=NO",out)

    def test_root_denial_prohibits_probe(self):
        stdout=io.StringIO()
        with mock.patch.object(m,"valid_roots",return_value=(False,"ROOT_TEST_PI_REQUIRED")),contextlib.redirect_stdout(stdout):
            code=m.scan(2,scanner=lambda *a,**kw:self.fail("must not scan"))
        self.assertEqual(code,2)
        self.assertIn("XRAY_DISCOVERY_ERROR=ROOT_TEST_PI_REQUIRED",stdout.getvalue())

    def test_invalid_batch_is_refused(self):
        with mock.patch.object(sys,"argv",["discover","--batch","100"]),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(m.main(),2)
            self.assertIn("BATCH_MUST_BE_1_TO_6",out.getvalue())

    def test_script_cannot_mutate_live_services_or_policy(self):
        source=SRC.read_text()
        for fragment in ('"systemctl","restart"', '"systemctl","stop"',
                         '"systemctl","start"', '"systemctl","enable"',
                         '"ip","route","replace"', 'awg-mihomo-configure',
                         'awg-xray-live-backend', 'node select-auto'):
            self.assertNotIn(fragment,source)
        self.assertIn('"probe",*indices',source)
        self.assertNotIn("XRAY_DISCOVERY_NODE_NAME",source)
        self.assertNotIn("XRAY_DISCOVERY_PROVIDER_SHA256",source)

    def test_root_preflight_rejects_unsafe_transit_guard(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            mode=root/"mode";mode.write_text("transit")
            binary=root/"catalog";binary.write_text("#!/bin/sh"+chr(10))
            binary.chmod(0o700)
            def fake_run(args,timeout=12):
                if args[:2]==["systemctl","is-active"]:
                    value="inactive" if args[-1]==m.SIDECAR_SERVICE else "active"
                elif args[:2]==["systemctl","is-enabled"]:
                    value="disabled"
                elif args[:3]==["ip","route","show"]:
                    value="default dev mihomo0 scope link"
                else:
                    value="Transit guard: UNSAFE"
                return types.SimpleNamespace(returncode=0,stdout=value,stderr="")
            with (mock.patch.object(m.os,"geteuid",return_value=0),
                  mock.patch.object(m.socket,"gethostname",return_value=m.EXPECTED_HOST),
                  mock.patch.object(m,"MODE",mode),
                  mock.patch.object(m,"BRIDGE",root/"missing-bridge"),
                  mock.patch.object(m,"SELECTED",root/"missing-selection"),
                  mock.patch.object(m,"LIVE",binary),
                  mock.patch.object(m,"run",side_effect=fake_run)):
                self.assertEqual(m.valid_roots(),(False,"TRANSIT_GUARD_UNSAFE"))

    def test_python_syntax(self):
        p=subprocess.run([sys.executable,"-m","py_compile",str(SRC)],
                         capture_output=True,text=True,timeout=9)
        self.assertEqual(p.returncode,0,p.stderr)

if __name__=="__main__":unittest.main()
