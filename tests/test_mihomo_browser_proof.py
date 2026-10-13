#!/usr/bin/env python3
"""Browser manual proof root-owned RAM TTL validator and negative cases."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SOURCE=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-browser-proof.py"
spec=importlib.util.spec_from_file_location("browser_proof_fixture",SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class BrowserProofTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="awg-browser-proof-",dir="/tmp")
        self.root=Path(self.temp.name)
        self.prov=self.root/"subscription.yaml"
        self.prov.write_bytes(b"fake-subscription-1")
        self.prov.chmod(0o600)
        self.file=self.root/"browser-proof.json"
        self.now=int(time.time())
        self.uid=os.geteuid()
        self.name="candidate-A"
        self.egress="93.184.216.34"

    def tearDown(self):
        self.temp.cleanup()

    def state(self,now=None,name=None):
        data=m.read_proof(self.file,self.uid)
        return m.proof_state(data,name or self.name,m.provider_digest(self.prov),
                             self.now if now is None else now,
                             egress_ip=self.egress)

    def write(self,age=0):
        return m.record(self.file,self.prov,self.name,self.now-age,self.now,self.uid,self.egress)

    def cli(self,*args):
        return subprocess.run([sys.executable,"-B",str(SOURCE),*args,
            "--fixture-root",str(self.root),"--node",self.name,
            "--egress-ip",self.egress],
            capture_output=True,text=True,timeout=8)

    def test_explicit_authenticated_reply_is_not_implicit_but_recordable(self):
        self.assertEqual(self.state()[0],"UNKNOWN")
        self.assertEqual(self.write(),("PASS","RECENT_OPERATOR_BROWSER_ACCEPTANCE"))
        self.assertEqual(self.state()[0],"PASS")
        self.assertEqual(self.file.stat().st_mode & 0o777,0o600)
        self.assertNotIn("cookie",self.file.read_text().lower())
        self.assertNotIn("token",self.file.read_text().lower())
        self.assertNotIn("password",self.file.read_text().lower())

    def test_expiration_strict_after_30_minutes(self):
        self.write()
        self.assertEqual(self.state(self.now+1800)[0],"PASS")
        self.assertEqual(self.state(self.now+1801),("UNKNOWN","STALE_OR_FUTURE_PROOF"))

    def test_old_observation_cannot_be_recorded_as_fresh(self):
        with self.assertRaisesRegex(m.Reject,"OUTSIDE_ACCEPTANCE_WINDOW"):
            self.write(age=1801)

    def test_future_observation_rejected(self):
        with self.assertRaisesRegex(m.Reject,"OUTSIDE_ACCEPTANCE_WINDOW"):
            self.write(age=-16)

    def test_provider_replaced_revokes_prior_acceptance(self):
        self.write()
        self.prov.write_bytes(b"fake-subscription-2")
        self.assertEqual(self.state()[1],"PROVIDER_CHANGED")

    def test_exit_ip_change_revokes_browser_acceptance(self):
        self.write()
        self.assertEqual(self.state()[0],"PASS")
        self.egress="193.233.74.6"
        self.assertEqual(self.state(),("UNKNOWN","EGRESS_CHANGED"))

    def test_private_or_missing_exit_not_recorded(self):
        with self.assertRaisesRegex(m.Reject,"EGRESS_MUST_BE_PUBLIC_IPV4"):
            m.record(self.file,self.prov,self.name,self.now,self.now,self.uid,"192.168.112.34")

    def test_missing_exit_parameter_cannot_approve_a_different_node(self):
        self.write()
        self.assertEqual(self.cli("check").returncode,0)
        self.assertEqual(m.proof_state(m.read_proof(self.file,self.uid),self.name,
                                      m.provider_digest(self.prov),self.now,
                                      egress_ip="8.8.8.8")[0],"UNKNOWN")

    def test_candidate_list_expires_and_tracks_provider(self):
        self.write()
        result=self.cli("candidates")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("BROWSER_CANDIDATE=candidate-A",result.stdout)
        self.prov.write_bytes(b"different-feed")
        later=self.cli("candidates")
        self.assertEqual(later.returncode,0,later.stderr)
        self.assertNotIn("BROWSER_CANDIDATE=",later.stdout)

    def test_exact_node_required(self):
        self.write()
        self.assertEqual(self.state(name="other-node")[1],"NODE_NOT_ACCEPTED")

    def test_duplicate_names_do_not_get_separate_proof(self):
        self.write()
        self.assertEqual(self.state(name="candidate-A-alt")[0],"UNKNOWN")

    def test_symlink_file_rejected(self):
        self.write()
        self.file.unlink()
        self.file.symlink_to(self.prov)
        with self.assertRaisesRegex(m.Reject,"SYMLINK"):
            self.state()

    def test_insecure_permissions_rejected(self):
        self.write()
        self.file.chmod(0o644)
        with self.assertRaisesRegex(m.Reject,"UNTRUSTED_FILE"):
            self.state()

    def test_insecure_parent_rejected_by_cli(self):
        self.write()
        self.root.chmod(0o755)
        result=self.cli("check")
        self.assertEqual(result.returncode,1)
        self.assertIn("BROWSER_PROOF=UNKNOWN",result.stdout)
        self.root.chmod(0o700)

    def test_check_exposes_no_secret(self):
        self.write()
        result=self.cli("check")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("BROWSER_PROOF=PASS",result.stdout)
        self.assertNotIn("fake-subscription",result.stdout)

    def test_record_cli_needs_explicit_ack(self):
        r=self.cli("record","--observed-at",str(self.now))
        self.assertNotEqual(r.returncode,0)
        self.assertIn("--ack-user-test",r.stderr)
        self.assertEqual(self.state()[0],"UNKNOWN")

    def test_record_cli_real_ack_in_fixture(self):
        r=self.cli("record","--observed-at",str(self.now),"--ack-user-test")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.state()[0],"PASS")

    def test_bad_claim_never_counts_as_chat(self):
        self.write()
        obj=json.loads(self.file.read_text())
        obj["entries"][self.name]["claim"]="api401"
        self.file.write_text(json.dumps(obj))
        self.assertEqual(self.state()[0],"UNKNOWN")

    def test_malformed_json_fails_closed(self):
        self.write()
        self.file.write_text("not json")
        with self.assertRaisesRegex(m.Reject,"MALFORMED_PROOF"):
            self.state()

    def test_no_browser_proof_in_source_changes_production(self):
        text=SOURCE.read_text()
        self.assertNotIn("systemctl",text)
        self.assertNotIn("nft ",text)
        self.assertNotIn("awg-transport select",text)

if __name__=="__main__":
    unittest.main()
