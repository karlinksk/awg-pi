#!/usr/bin/env python3
"""AUTO browser proof pool filtering: static negative and synthetic failover."""
from __future__ import annotations
import argparse
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
POOL=ROOT/"src"/"awg-mihomo-pool.py"
POLICY=ROOT/"src"/"awg-mihomo-node-policy"
spec=importlib.util.spec_from_file_location("allow_pool",POOL)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class PoolAllowlistTests(unittest.TestCase):
    def pick(self,allow,exclude=None):
        pool={"nodes":[
            {"name":"untrusted-fast","healthy":True,"delay_ms":1,"index":1},
            {"name":"approved-ss","healthy":True,"delay_ms":12,"index":2},
            {"name":"approved-vless","healthy":True,"delay_ms":25,"index":3},
            {"name":"bad-health","healthy":False,"delay_ms":2,"index":4},
        ]}
        args=argparse.Namespace(target="live",ignore_policy=False,
                                exclude=exclude or [],allow=allow)
        output=io.StringIO()
        with patch.object(module,"read_policy",return_value="all"), \
             patch.object(module,"pool_current",return_value=True), \
             patch.object(module,"load_json",return_value=pool), \
             patch.object(module,"target_paths",return_value=(None,"fake")), \
             patch.object(module,"load_cooldown",return_value={}), \
             contextlib.redirect_stdout(output):
            try:
                module.cmd_best(args)
            except SystemExit:
                return None
        return output.getvalue().strip()

    def test_legacy_pool_fastest_without_allow(self):
        self.assertEqual(self.pick([]),"untrusted-fast")

    def test_allowlist_skips_untrusted_faster_nodes(self):
        self.assertEqual(self.pick(["approved-ss","approved-vless"]),"approved-ss")

    def test_exclusions_advance_only_within_approved_nodes(self):
        self.assertEqual(self.pick(["approved-ss","approved-vless"],["approved-ss"]),
                         "approved-vless")

    def test_no_healthy_approved_nodes_is_no_candidate(self):
        self.assertIsNone(self.pick(["bad-health"]))

    def test_explicit_unknown_approval_is_no_candidate(self):
        self.assertIsNone(self.pick(["not-in-feed"]))

    def test_pool_command_does_not_bypass_existing_region_filters(self):
        self.assertIn("--allow",POOL.read_text())
        self.assertIn("effective_nodes(pool, show_all=False",POOL.read_text())


class BrowserPolicySyntheticTests(unittest.TestCase):
    @staticmethod
    def func(name):
        src=POLICY.read_text()
        return name+"(){"+src.split(name+"(){",1)[1].split("\n}\n",1)[0]+"\n}\n"

    def exercise(self,proof_names,healthy_names=("accepted-A","accepted-B"),approved=("accepted-A","accepted-B")):
        with tempfile.TemporaryDirectory(prefix="awg-browser-auto-test-",dir="/tmp") as t:
            root=Path(t)
            p=root/"proof"; pool=root/"pool"; apply=root/"apply"; log=root/"selected"
            p.write_text("#!/bin/sh\n"+ "".join(f"echo BROWSER_CANDIDATE={n}\n" for n in proof_names))
            p.chmod(0o700)
            pool.write_text('''#!/bin/bash
if [[ "$1" == ensure || "$1" == cooldown ]]; then exit 0; fi
[[ "$1" == best ]] || exit 1
shift 2
allowed=()
excluded=()
while (( $# )); do
  case "$1" in
  --allow) allowed+=("$2"); shift 2 ;;
  --exclude) excluded+=("$2"); shift 2 ;;
  *) exit 3 ;;
  esac
done
for node in "accepted-A" "accepted-B"; do
  permitted=0
  for a in "${allowed[@]}"; do [[ "$a" == "$node" ]] && permitted=1; done
  for e in "${excluded[@]}"; do [[ "$e" == "$node" ]] && permitted=0; done
  (( permitted )) || continue
  echo "$node"
  exit 0
done
exit 1
''')
            pool.chmod(0o700)
            apply.write_text(f'#!/bin/bash\n[[ "$1" == node && "$2" == select-auto ]] || exit 1\necho "$3" >> "{log}"\n')
            apply.chmod(0o700)
            script=(self.func("failover_auto") +
                '''service_candidate_allowed(){
  case "$1" in accepted-A|accepted-B) return 0 ;; *) return 1 ;; esac
}
'''+f'''
MIHOMO_POOL_CLI={pool}
MIHOMO_BROWSER_PROOF_BIN={p}
MIHOMO_CONFIGURE={apply}
MIHOMO_SERVICE_GATE_MODE=browser
failover_auto current-node
''')
            result=subprocess.run(["bash","-c",script],capture_output=True,text=True,timeout=8)
            selected=log.read_text().splitlines() if log.exists() else []
            return result,selected

    def test_auto_chooses_only_fresh_accepted_candidate(self):
        result,selected=self.exercise(["accepted-A","accepted-B"])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(selected,["accepted-A"])

    def test_unapproved_node_never_attempted(self):
        result,selected=self.exercise(["evil"])
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(selected,[])

    def test_empty_proof_list_fails_closed(self):
        result,selected=self.exercise([])
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(selected,[])

    def test_second_node_used_if_first_not_proved(self):
        result,selected=self.exercise(["accepted-B"])
        self.assertEqual(result.returncode,0)
        self.assertEqual(selected,["accepted-B"])

if __name__=="__main__":
    unittest.main()
