#!/usr/bin/env python3
"""Strict per-node service eligibility cache: offline, synthetic tests."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-service-eligibility.py"
spec=importlib.util.spec_from_file_location("eligible",SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ServiceEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir="/tmp",prefix="awg-eligibility-")
        self.root=Path(self.temp.name)
        self.provider=self.root/"subscription.yaml"
        self.provider.write_bytes(b"only synthetic fake subscription")
        self.provider.chmod(0o600)
        self.now=int(time.time())
        self.passrow={
            "name":"node-good","service_state":"PASS","service_ok":True,
            "warmup_ok":True,"ok":True,"sustained_verified":True,"confirmed":True,
            "service_checks":{
                key:{"state":"PASS","reason":"TEST_ONLY"}
                for key in m.REQUIRED_CHECKS
            },
        }
        self.report={
            "version":2,"mode":"shadow","production_modified":False,
            "switches_made":0,"timestamp":self.now,
            "source_sha256":hashlib.sha256(self.provider.read_bytes()).hexdigest(),
            "results":[self.passrow],
        }
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        p=self.root/"last.json"
        p.write_text(json.dumps(self.report),encoding="utf-8")
        p.chmod(0o600)

    def gate(self,name="node-good"):
        return m.assess(name,self.root/"last.json",self.provider,owner=os.geteuid(),
                        now=self.now,max_age=1800)

    def cli(self,node="node-good"):
        return subprocess.run([sys.executable,"-B",str(SCRIPT),"--fixture-root",str(self.root),
                               "--node",node],capture_output=True,text=True,timeout=8)

    def test_all_services_pass_exact_node(self):
        self.assertEqual(self.gate(),("PASS","FRESH_BOTH_SERVICES_CONFIRMED"))
        r=self.cli()
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("SERVICE_ELIGIBILITY=PASS",r.stdout)

    def test_missing_youtube_is_not_pass(self):
        self.passrow["service_checks"]["youtube_video"]["state"]="UNKNOWN"
        self.save()
        self.assertEqual(self.gate()[0],"UNKNOWN")

    def test_missing_chatgpt_is_not_pass(self):
        self.passrow["service_checks"]["chatgpt_web"]["state"]="FAIL"
        self.save()
        self.assertEqual(self.gate()[0],"UNKNOWN")

    def test_region_fail_does_not_pass(self):
        self.passrow["service_state"]="FAIL"
        self.passrow["service_ok"]=False
        self.save()
        self.assertEqual(self.gate()[0],"FAIL")

    def test_stale_and_future_report_rejected(self):
        self.report["timestamp"]=self.now-1801
        self.save()
        self.assertEqual(self.gate()[1],"STALE_OR_FUTURE_REPORT")
        self.report["timestamp"]=self.now+60
        self.save()
        self.assertEqual(self.gate()[1],"STALE_OR_FUTURE_REPORT")

    def test_source_changed_rejected(self):
        self.provider.write_text("other synthetic subscription")
        self.assertEqual(self.gate()[1],"PROVIDER_CHANGED")

    def test_different_node_never_inherits_pass(self):
        self.assertEqual(self.gate("node-other")[1],"MISSING_OR_AMBIGUOUS_NODE")

    def test_duplicate_name_rejected(self):
        self.report["results"].append(dict(self.passrow))
        self.save()
        self.assertEqual(self.gate()[1],"MISSING_OR_AMBIGUOUS_NODE")

    def test_unconfirmed_candidate_rejected(self):
        self.passrow["confirmed"]=False
        self.save()
        self.assertEqual(self.gate()[1],"PERFORMANCE_UNCONFIRMED")

    def test_unsustained_candidate_rejected(self):
        self.passrow["sustained_verified"]=False
        self.save()
        self.assertEqual(self.gate()[1],"PERFORMANCE_UNCONFIRMED")

    def test_missing_service_ok_flag_denied(self):
        self.passrow.pop("service_ok")
        self.save()
        self.assertEqual(self.gate()[1],"SERVICES_UNVERIFIED")

    def test_shadow_report_must_not_mutate(self):
        self.report["switches_made"]=1
        self.save()
        self.assertEqual(self.gate()[1],"MUTATING_REPORT_UNTRUSTED")

    def test_untrusted_report_permissions_refused(self):
        (self.root/"last.json").chmod(0o644)
        self.assertEqual(self.cli().returncode,1)
        self.assertIn("SERVICE_ELIGIBILITY=UNKNOWN",self.cli().stdout)

    def test_unsafe_parent_permissions_refused(self):
        self.root.chmod(0o755)
        self.assertEqual(self.cli().returncode,1)
        self.root.chmod(0o700)

    def test_symlink_report_refused(self):
        p=self.root/"last.json"
        p.unlink()
        p.symlink_to(self.provider)
        self.assertEqual(self.cli().returncode,1)

    def test_production_denied_for_unprivileged(self):
        if os.geteuid() == 0:self.skipTest("unprivileged-only")
        r=subprocess.run([sys.executable,"-B",str(SCRIPT),"--node","node-good"],
                         capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,1)
        self.assertIn("LIVE_GATE_REQUIRES_ROOT",r.stdout)

    def test_node_policy_calls_gate_before_both_auto_select_paths(self):
        source=(SCRIPT.parent/"awg-mihomo-node-policy").read_text()
        fixed=source.split("failover_fixed(){",1)[1].split("failover_auto(){",1)[0]
        auto=source.split("failover_auto(){",1)[1].split("failover(){",1)[0]
        self.assertLess(fixed.index('service_candidate_allowed "$node"'),
                        fixed.index('node select-auto "$node"'))
        self.assertLess(auto.index('service_candidate_allowed "$candidate"'),
                        auto.index('node select-auto "$candidate"'))
        self.assertIn('MIHOMO_SERVICE_GATE_MODE_FILE=',source)

    def test_shell_gate_strict_mode_calls_and_rejects_unknown(self):
        import tempfile
        source=(SCRIPT.parent/"awg-mihomo-node-policy").read_text()
        func=source.split("service_candidate_allowed(){",1)[1].split("\n}\n",1)[0]
        harness="service_candidate_allowed() {"+func+"\n}\n"
        with tempfile.TemporaryDirectory(dir="/tmp") as temp:
            stub=Path(temp)/"fake-gate"
            stub.write_text("#!/bin/sh\nprintf 'SERVICE_ELIGIBILITY=UNKNOWN\\n'\nexit 1\n")
            stub.chmod(0o700)
            for mode,expected in (("require",0),("off",0),("bad",0)):
                script=(harness+'MIHOMO_SERVICE_GATE_MODE='+mode+'\n'
                        +'MIHOMO_SERVICE_GATE_BIN="'+str(stub)+'"\n'
                        +'service_candidate_allowed node-good\n')
                r=subprocess.run(["bash","-c",script],capture_output=True,timeout=5)
                self.assertEqual(r.returncode,expected,mode)

    def test_fails_closed_on_untrusted_fixture_root(self):
        r=subprocess.run([sys.executable,"-B",str(SCRIPT),
                         "--fixture-root","/etc","--node","node-good"],
                         capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,1)

if __name__=="__main__":
    unittest.main()
