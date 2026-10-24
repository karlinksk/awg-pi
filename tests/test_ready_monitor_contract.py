import os,pathlib,subprocess,tempfile,unittest
HERE=pathlib.Path(__file__).resolve().parent
MONITOR=str(HERE.parent/'src/awg-selection-monitor' if (HERE.parent/'src/awg-selection-monitor').exists() else '/usr/local/sbin/awg-selection-monitor')
class MonitorContract(unittest.TestCase):
 def run_case(self,node_answer='',transport_ok='0',mode='auto',threshold='1',awg_profile=True):
  with tempfile.TemporaryDirectory(prefix='selection-canary-') as d:
   p=pathlib.Path(d)
   (p/'common.sh').write_text('awg_transport_get(){ echo mihomo; }\nawg_transport_backend_valid(){ [[ "$1" == mihomo || "$1" == awg ]]; }\n')
   (p/'selection.env').write_text(f'SELECTION_MODE={mode}\nSELECTION_PRIMARY=mihomo\nSELECTION_ORDER=mihomo,awg\n')
   (p/'events').write_text('')
   if awg_profile:
    (p/'awg0.conf').write_text('mock AWG standby profile\n')
   (p/'transport').write_text('''#!/bin/bash
echo "transport:$*" >> "$LOG"
case "$1" in
 check|network-check) [[ "$TRANSPORT_OK" == 1 ]];;
 select) [[ "$2" == awg ]];;
 *) exit 1;;
esac
''')
   (p/'node').write_text('''#!/bin/bash
echo "node:$*" >> "$LOG"
case "$1" in
 enabled) exit 0;;
 failover) [[ -z "$NODE_ANSWER" ]] || printf '%s\n' "$NODE_ANSWER"; [[ -n "$NODE_ANSWER" ]];;
esac
''')
   for name in ('node','transport'): (p/name).chmod(0o755)
   env=dict(os.environ,AWG_COMMON_FILE=str(p/'common.sh'),AWG_SELECTION_FILE=str(p/'selection.env'),
            AWG_TRANSPORT_CLI=str(p/'transport'),MIHOMO_NODE_POLICY_CLI=str(p/'node'),
            AWG_SELECTION_STATE_DIR=d,AWG_SELECTION_FAILURES=str(p/'failures'),AWG_LOCK_FILE=str(p/'lock'),
            AWG_SELECTION_ONCE='1',AWG_SELECTION_FAILURE_THRESHOLD=threshold,
            MIHOMO_SERVICE_GATE_MODE='off',LOGGER_BIN='/bin/true',
            NODE_ANSWER=node_answer,TRANSPORT_OK=transport_ok,LOG=str(p/'events'),
            AWG_AUTO_AWG_CONFIG=str(p/'awg0.conf'))
   r=subprocess.run(['bash',MONITOR],env=env,capture_output=True,text=True,timeout=5)
   return r,(p/'events').read_text()
 def test_node_success_skips_awg(self):
  r,log=self.run_case('MIHOMO_NODE_FAILOVER=original->ready')
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertIn('MIHOMO_NODE_FAILOVER=original->ready',r.stdout)
  self.assertNotIn('transport:select awg',log)
 def test_failed_nodes_use_awg(self):
  r,log=self.run_case('')
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertIn('transport:select awg',log)
  self.assertIn('FAILOVER=mihomo->awg',r.stdout)
 def test_unconfigured_awg_is_never_started(self):
  r,log=self.run_case('',awg_profile=False)
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertNotIn('transport:select awg',log)
  self.assertNotIn('FAILOVER=',r.stdout)
 def test_extra_stdout_is_not_accepted(self):
  r,log=self.run_case('READY_AUTO_POSTCHECK=PASS\nMIHOMO_NODE_FAILOVER=original->ready')
  self.assertIn('transport:select awg',log)
 def test_healthy_transport_stays(self):
  r,log=self.run_case(transport_ok='1')
  self.assertEqual(r.returncode,0,r.stderr);self.assertNotIn('node:failover',log);self.assertNotIn('transport:select',log)
 def test_transient_one_failure_does_not_switch(self):
  r,log=self.run_case(threshold='2')
  self.assertEqual(r.returncode,0,r.stderr);self.assertNotIn('node:failover',log);self.assertNotIn('transport:select',log)
if __name__=='__main__':unittest.main(verbosity=2)

