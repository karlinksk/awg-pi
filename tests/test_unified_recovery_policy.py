#!/usr/bin/env python3
"""Rootless full-provider sequential failover, 13 mixed engine nodes."""
import os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"src/awg-mihomo-node-policy").read_text()
def extract(n):
    return n+"(){"+SOURCE.split(n+"(){",1)[1].split("\n}\n",1)[0]+"\n}\n"
class UnifiedPolicy(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.bin=self.root/"bin";self.bin.mkdir()
        self.log=self.root/"actions";self.mode=self.root/"mode";self.order=self.root/"fixed"
        self.sha="a"*64
        self.nodes=[("MIHOMO" if i%3 else "XRAY",i,"Node"+str(i)) for i in range(1,14)]
        self.write("resolver",'''
[ "$1" = resolve ] || exit 3
index="${2#Node}"
if [ $((index % 3)) -eq 0 ];then engine=XRAY;else engine=MIHOMO;fi
printf 'NODE_ENGINE=%s\\nNODE_PROVIDER_SHA256=%s\\n' "$engine" "$MOCK_SHA"
''')
        self.write("executor",'''
case "$1" in
  probe-native|probe-xray|dead-xray-exhausted)exit 0;;
esac
echo "$1:$2" >> "$MOCK_LOG"
case "$1" in
  dead-xray-native) [ "$2" = "$MOCK_SUCCESS" ] && exit 0 || exit 2;;
  dead-xray-xray) [ "Node$2" = "$MOCK_SUCCESS" ] && exit 0 || exit 2;;
  *)exit 9;;
esac
''')
        self.write("configure",'''
[ "$1" = node ] || exit 3
echo "NATIVE:$3" >> "$MOCK_LOG";exit 0
''')
    def write(self,name,body):
        path=self.bin/name;path.write_text("#!/usr/bin/env bash\n"+body);path.chmod(0o755)
    def run_case(self,bridge=True,success="Node13",fixed=False,decline=False):
        self.log.write_text("")
        self.mode.write_text("fixed\n" if fixed else "auto\n")
        self.order.write_text("Node11\nNode2\n")
        data="".join("printf '%s\\n' '"+("\t".join((engine,str(index),self.sha,name)))+"'\n"
                     for engine,index,name in self.nodes)
        script="".join((
            "set -Eeuo pipefail\n",extract("failover_unified"),
            'validate_node_name(){ [[ -n "$1" ]]; }\n',
            'mode_get(){ cat "$MIHOMO_NODE_POLICY_MODE_FILE"; }\n',
            'xray_bridge_present(){ return '+("0" if bridge else "1")+'; }\n',
            'unified_recovery_candidates(){\n'+data+'}\n',
            'service_candidate_allowed(){ return 0; }\n',
            'unified_native_tun_postcheck(){ return 1; }\n',
            'unified_native_quiesce(){ echo QUIESCE >> "$MOCK_LOG"; return 0; }\n',
            'auto_xray_candidate(){ echo "XRAY:$2" >> "$MOCK_LOG"; [ "$UNIFIED_SUCCESS" = "$2" ]; }\n',
            'failover_unified FailedNode\n'
        ))
        env={**os.environ,"MOCK_SHA":self.sha,"MOCK_LOG":str(self.log),
             "MIHOMO_NODE_POLICY_MODE_FILE":str(self.mode),
             "MIHOMO_NODE_POLICY_ORDER_FILE":str(self.order),
             "MIHOMO_UNIFIED_NODE_CLI":str(self.bin/"resolver"),
             "MIHOMO_XRAY_NATIVE_RECOVERY_CLI":str(self.bin/"executor"),
             "MIHOMO_CONFIGURE":str(self.bin/"configure"),
             "UNIFIED_SUCCESS":success,"MOCK_SUCCESS":success}
        if decline:self.write("executor","exit 2")
        return subprocess.run(["bash","-c",script],env=env,capture_output=True,text=True,timeout=10)
    def test_thirteenth_candidate_can_win(self):
        r=self.run_case()
        self.assertEqual(r.returncode,0,r.stderr)
        actions=self.log.read_text().splitlines()
        self.assertEqual(len(actions),13)
        self.assertEqual(actions[-1],"dead-xray-native:Node13")
    def test_late_xray_candidate_is_not_skipped(self):
        r=self.run_case(success="Node9")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.log.read_text().splitlines()[-1],"dead-xray-xray:9")
    def test_all_unsuccessful_fall_back_to_awg(self):
        r=self.run_case(success="None")
        self.assertEqual(r.returncode,1)
        self.assertEqual(len(self.log.read_text().splitlines()),13)
        self.assertIn("UNIFIED_EXHAUSTED_NO_VERIFIED_CANDIDATE_AWG_FALLBACK",r.stderr)
    def test_fixed_order_first_then_unified_remainder(self):
        r=self.run_case(success="Node11",fixed=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.log.read_text().splitlines(),["dead-xray-native:Node11"])
    def test_native_failure_can_choose_xray(self):
        r=self.run_case(bridge=False,success="Node3")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("XRAY:Node3",self.log.read_text().splitlines())
    def test_preflight_exhaustion_does_not_mutate(self):
        r=self.run_case(decline=True)
        self.assertEqual(r.returncode,1)
        self.assertEqual(self.log.read_text(),"")
    def test_no_numeric_caps(self):
        fn=extract("failover_unified")
        self.assertNotIn("max_xray_visits",fn)
        self.assertNotIn("max_candidate_visits",fn)
        self.assertIn('for line in "${prioritized[@]}"; do',fn)
if __name__=="__main__":unittest.main()
