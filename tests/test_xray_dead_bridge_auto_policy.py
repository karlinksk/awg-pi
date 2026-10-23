#!/usr/bin/env python3
"""Rootless executable policy chain: exact native candidates before AWG."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
POLICY=(ROOT/"src/awg-mihomo-node-policy").read_text()

def function(name):
    return name+"(){"+POLICY.split(name+"(){",1)[1].split("\n}\n",1)[0]+"\n}\n"

class DeadBridgeAutoPolicy(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.bin=self.root/"bin";self.bin.mkdir()
        self.log=self.root/"log"
        self.write("pool",r'''
if [ "$1" = ensure ]; then exit 0; fi
if [ "$1" = best ]; then
  shift 2
  for candidate in NativeA NativeB NativeC NativeD; do
    excluded=0
    args="$*"
    for exclusion in "$@"; do
      [ "$exclusion" != "$candidate" ] || excluded=1
    done
    if [ "$excluded" = 0 ]; then echo "$candidate";exit 0;fi
  done
fi
exit 1
''')
        self.write("resolver",r'''
[ "$1" = resolve ] || exit 3
if [ "$2" = NativeA ] && [ "$MOCK_FIRST_ENGINE" = XRAY ]; then
  echo NODE_ENGINE=XRAY
else
  echo NODE_ENGINE=MIHOMO
fi
''')
        self.write("executor",r'''
[ "$1" = dead-xray-native ] || exit 3
echo "$2" >> "$MOCK_LOG"
if [ "$2" = NativeA ]; then exit "$MOCK_FIRST_RC"; fi
exit 0
''')

    def write(self,name,body):
        p=self.bin/name;p.write_text("#!/usr/bin/env bash\n"+body);p.chmod(0o755)
        return p

    def run_policy(self,first_rc="2",first_engine="MIHOMO",executor=True):
        self.log.write_text("")
        exe=self.bin/"executor"
        if not executor:exe.unlink(missing_ok=True)
        script=(
            "set -Eeuo pipefail\n"+
            'validate_node_name(){ [[ -n "$1" ]]; }\n'+
            function("failover_dead_xray_native")+
            'failover_dead_xray_native FailedXray\n'
        )
        env={**os.environ,
             "MIHOMO_POOL_CLI":str(self.bin/"pool"),
             "MIHOMO_UNIFIED_NODE_CLI":str(self.bin/"resolver"),
             "MIHOMO_XRAY_NATIVE_RECOVERY_CLI":str(exe),
             "MOCK_LOG":str(self.log),
             "MOCK_FIRST_RC":first_rc,
             "MOCK_FIRST_ENGINE":first_engine}
        return subprocess.run(["bash","-c",script],env=env,capture_output=True,text=True,timeout=8)

    def test_first_preflight_rejected_then_next_native_commits(self):
        result=self.run_policy(first_rc="2")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.log.read_text().splitlines(),["NativeA","NativeB"])
        self.assertEqual(result.stdout.strip(),"MIHOMO_NODE_FAILOVER=FailedXray->NativeB")

    def test_post_mutation_failure_aborts_for_awg_without_next_candidate(self):
        result=self.run_policy(first_rc="1")
        self.assertEqual(result.returncode,1)
        self.assertEqual(self.log.read_text().splitlines(),["NativeA"])
        self.assertIn("DEAD_XRAY_NATIVE_ABORT_AWG_FALLBACK",result.stderr)

    def test_engine_unavailable_not_forwarded_to_native_executor(self):
        result=self.run_policy(first_engine="XRAY")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.log.read_text().splitlines(),["NativeB"])

    def test_missing_executor_never_changes_transport(self):
        result=self.run_policy(executor=False)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.log.read_text(),"")
        self.assertIn("COMPONENT_MISSING",result.stderr)

    def test_pool_exhaustion_is_bounded_at_three(self):
        self.write("executor",'echo "$2" >> "$MOCK_LOG"\nexit 2')
        result=self.run_policy(first_rc="2")
        self.assertEqual(result.returncode,1)
        self.assertEqual(len(self.log.read_text().splitlines()),3)
        self.assertIn("NO_VERIFIED_NATIVE_AWG_FALLBACK",result.stderr)

if __name__=="__main__":
    unittest.main()
