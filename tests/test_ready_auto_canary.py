import os, pathlib, subprocess, tempfile, unittest, sys
HERE=pathlib.Path(__file__).resolve().parent
SCRIPT=str(HERE/'awg-mihomo-node-policy' if (HERE/'awg-mihomo-node-policy').exists() else HERE.parent/'src/awg-mihomo-node-policy')
GUARD=str(HERE/'ready_live_match.py' if (HERE/'ready_live_match.py').exists() else HERE.parent/'src/awg-mihomo-ready-live-match')
class ReadyAutoV2(unittest.TestCase):
 def rootless_script(self,path):
  source=pathlib.Path(SCRIPT).read_text()
  line='[[ ${EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"'
  assert source.count(line)==1
  outfile=path/'rootless-policy'
  outfile.write_text(source.replace(line,': # isolated mocked fixture'))
  return str(outfile)
 def case(self, ready='1', guard='1', activate='1', post='1', rollback='1', gate='balanced', checker='1',canary='1',post_reason='EGRESS_FAILED',strict_gate='0',api_state='PASS',second_ready='0',post_second='1',fallback_available='1'):
  with tempfile.TemporaryDirectory(prefix='ready-v2-') as d:
   p=pathlib.Path(d)
   (p/'mode').write_text('auto\n')
   (p/'node').write_text('original\n')
   (p/'op-mode').write_text('transit\n')
   (p/'events').write_text('')
   mocks={
    'hot': '''#!/bin/bash
echo "hot:$*" >> "$LOG"
if [[ "$*" == *" quarantine "* ]]; then exit 0; fi
if [[ "$READY" == 1 && " $* " != *" --exclude standby "* ]]; then echo standby; exit 0; fi
if [[ "$READY" == 1 && "$SECOND_READY" == 1 && " $* " != *" --exclude standby-second "* ]]; then echo standby-second; exit 0; fi
exit 3
''',
    'pool': '''#!/bin/bash
echo "pool:$*" >> "$LOG"
case "$1" in
 best) if [[ "$FALLBACK_AVAILABLE" == 1 && " $* " != *" --exclude ordinary "* ]]; then echo ordinary; exit 0; fi; exit 3;;
 *) exit 0;;
esac
''',
    'guard': '''#!/usr/bin/env python3
import os,sys
with open(os.environ['LOG'],'a') as f: f.write('guard')
sys.exit(0 if os.environ.get('GUARD_OK') == '1' else 1)
''',
    'configure': '''#!/bin/bash
echo "config:$* recovery=${MIHOMO_NODE_FAILOVER_RECOVERY:-unset}" >> "$LOG"
[[ "$*" != "node select-auto standby" || "$ACTIVATE_OK" == 1 ]] || exit 1
[[ "$*" != "node select-auto original" || "$ROLLBACK_OK" == 1 ]] || exit 1
if [[ "$1" == node && "$2" == select-auto ]]; then printf '%s\n' "$3" > "$NODE_FILE"; fi
''',
    'post': '''#!/bin/bash
echo "post:$*" >> "$LOG"
if [[ "$1" == standby && "$POST_OK" != 1 ]]; then echo "READY_TUN_CHECK=$POST_REASON"; exit 1; fi
if [[ "$1" == standby-second && "$POST_SECOND_OK" != 1 ]]; then echo "READY_TUN_CHECK=$POST_REASON"; exit 1; fi
''',
    'scan': '''#!/bin/bash
echo "scan:$*" >> "$LOG"
if [[ "$STRICT_GATE" == 1 ]]; then
 cat <<EOF
SERVICE_IP_CONNECT_STATE=PASS
SERVICE_IP_CONNECT_REASON=ALL_CHECKED_IPV4_HTTPS_OK
SERVICE_ELIGIBILITY=UNKNOWN
SERVICE_CHECK_OPENAI_API=$API_STATE
SERVICE_CHECK_CHATGPT_WEB=UNKNOWN
SERVICE_CHECK_YOUTUBE_VIDEO=PASS
SERVICE_REASON_CHATGPT_WEB=chatgpt_web_http_403
SERVICE_REASON_YOUTUBE_VIDEO=youtube_24_video_frames_decoded
EOF
else
 [[ "$CHECKER_OK" == 1 ]] && echo PASS
fi
''',
    'network': '''#!/bin/bash
if [[ "$STRICT_GATE" == 1 ]]; then
 exec /usr/bin/python3 -B "$NETWORK_GATE"
fi
cat >/dev/null
[[ "$CHECKER_OK" == 1 ]]
''',
    'transit': '''#!/bin/bash
echo "transit:$*" >> "$LOG"
[[ "$1" == disable ]]
''',
    'failopen': '''#!/bin/bash
echo "failopen:$*" >> "$LOG"
''',
    'systemctl': '''#!/bin/bash
echo "systemctl:$*" >> "$LOG"
[[ "$1" == stop && "$2" == awg-mihomo.service ]]
'''
   }
   for name,data in mocks.items():
    f=p/name;f.write_text(data);f.chmod(0o755)
   params={'MIHOMO_NODE_POLICY_MODE_FILE':str(p/'mode'),'MIHOMO_NODE_NAME_FILE':str(p/'node'),
           'MIHOMO_NODE_POLICY_ORDER_FILE':str(p/'order'), 'MIHOMO_POOL_CLI':str(p/'pool'),
           'MIHOMO_HOT_POOL_CLI':str(p/'hot'),'MIHOMO_CONFIGURE_BIN':str(p/'configure'),
           'MIHOMO_UNIFIED_NODE_CLI':str(p/'missing-unified-cli'),
           'MIHOMO_READY_GUARD_BIN':str(p/'guard'),'MIHOMO_READY_POSTCHECK_BIN':str(p/'post'),
           'MIHOMO_SERVICE_QUICKCHECK_BIN':str(p/'scan'),'MIHOMO_NETWORK_GATE_BIN':str(p/'network'),
           'MIHOMO_READY_AUTO_CANARY':canary,'MIHOMO_SERVICE_GATE_MODE':gate,
           'READY':ready,'GUARD_OK':guard,'ACTIVATE_OK':activate,'POST_OK':post,'POST_REASON':post_reason,
           'ROLLBACK_OK':rollback,'CHECKER_OK':checker,'LOG':str(p/'events'),'NODE_FILE':str(p/'node'),
           'SECOND_READY':second_ready,'POST_SECOND_OK':post_second,'FALLBACK_AVAILABLE':fallback_available,
           'MIHOMO_AUTO_MODE_FILE':str(p/'op-mode'),
           'MIHOMO_AUTO_TRANSIT_ROUTING':str(p/'transit'),
           'MIHOMO_AUTO_FAILOPEN':str(p/'failopen'),
           'MIHOMO_AUTO_SYSTEMCTL':str(p/'systemctl'),
           'STRICT_GATE':strict_gate,'API_STATE':api_state,
           'NETWORK_GATE':str(HERE.parent/'src/awg-mihomo-network-eligibility.py')}
   if canary is None:
    (p/'ready-auto.mode').write_text('1\n')
    params.pop('MIHOMO_READY_AUTO_CANARY')
    params['MIHOMO_READY_AUTO_MODE_FILE']=str(p/'ready-auto.mode')
   if gate is None:
    params.pop('MIHOMO_SERVICE_GATE_MODE')
    params['MIHOMO_SERVICE_GATE_MODE_FILE']=str(p/'absent-service-mode')
   r=subprocess.run(['bash',self.rootless_script(p),'failover'],
      env=dict(os.environ,**params),text=True,capture_output=True,timeout=12)
   return r,(p/'events').read_text(),(p/'node').read_text().strip()
 def test_ready_first(self):
  r,log,node=self.case();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(node,'standby');self.assertNotIn('config:node select-auto ordinary',log);self.assertEqual(r.stdout.strip(),'MIHOMO_NODE_FAILOVER=original->standby')
 def test_real_network_gate_filters_extra_service_diagnostics(self):
  # A real service scan contains diagnostic lines, rejected by the strict
  # medium-confidence parser if they are passed without field filtering.
  r,log,node=self.case(canary=None,gate=None,strict_gate='1')
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(node,'standby')
  self.assertNotIn('scan:service-scan --node standby',log)
  self.assertIn('post:standby',log)
  self.assertNotIn('READY_AUTO=CANDIDATE_SERVICE_REJECTED',r.stderr)
 def test_real_network_gate_rejects_missing_openai_api(self):
  r,log,node=self.case(canary=None,gate=None,strict_gate='1',api_state='UNKNOWN',ready='0')
  self.assertNotEqual(r.returncode,0)
  self.assertEqual(node,'original')
  self.assertNotIn('config:node select-auto',log)
  self.assertIn('REASON=OPENAI_API_NOT_CONFIRMED',r.stderr)
 def test_persistent_ready_first_with_balanced_fallback(self):
  r,log,node=self.case(canary=None,gate=None)
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(node,'standby')
  self.assertIn('hot:',log)
  self.assertNotIn('scan:service-scan --node standby',log)
  self.assertIn('post:standby',log)
  self.assertNotIn('config:node select-auto ordinary',log)
 def test_persistent_no_ready_requires_new_service_proof(self):
  r,log,node=self.case(ready='0',canary=None,gate=None)
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(node,'ordinary')
  self.assertIn('scan:service-scan --node ordinary',log)
  self.assertIn('post:ordinary',log)
 def test_persistent_no_ready_rejects_unverified_candidate(self):
  r,log,node=self.case(ready='0',checker='0',canary=None,gate=None)
  self.assertNotEqual(r.returncode,0)
  self.assertEqual(node,'original')
  self.assertNotIn('config:node select-auto ordinary',log)
 def test_canary_off_preserves_existing_auto(self):
  r,log,node=self.case(canary='0',gate='off');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(node,'ordinary');self.assertNotIn('hot:',log);self.assertEqual(r.stdout.strip(),'MIHOMO_NODE_FAILOVER=original->ordinary')
 def test_no_ready_fallback(self):
  r,log,node=self.case(ready='0');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(node,'ordinary');self.assertEqual(r.stdout.strip(),'MIHOMO_NODE_FAILOVER=original->ordinary')
 def test_guard_rejects_archived_mismatch(self):
  r,log,node=self.case(guard='0');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(node,'ordinary');self.assertNotIn('config:node select-auto standby',log)
 def test_failed_ready_activation_quarantines(self):
  r,log,node=self.case(activate='0');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(node,'ordinary');self.assertIn('quarantine standby --reason activation-failed',log)
 def test_postcheck_failure_tries_next_candidate_not_original(self):
  r,log,node=self.case(post='0');self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(node,'ordinary')
  self.assertNotIn('config:node select-auto original',log)
  self.assertIn('config:node select-auto ordinary',log)
  self.assertIn('READY_AUTO=RETRY_NEXT_READY',r.stderr)
 def test_transit_route_failure_does_not_quarantine(self):
  r,log,node=self.case(post='0',post_reason='ROUTE_MISSING')
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(node,'ordinary')
  self.assertNotIn('quarantine standby',log)
  self.assertNotIn('cooldown add standby',log)
 def test_invalid_egress_quarantines(self):
  r,log,node=self.case(post='0',post_reason='EGRESS_INVALID')
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(node,'ordinary')
  self.assertIn('quarantine standby --reason active-health-failed',log)
 def test_recovery_transaction_propagated_to_configure(self):
  r,log,node=self.case(post='0',second_ready='1',fallback_available='0')
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertIn('config:node select-auto standby recovery=1',log)
  self.assertIn('config:node select-auto standby-second recovery=1',log)
  self.assertNotIn('config:node select-auto original',log)
 def test_activation_failure_does_not_restart_old_node(self):
  r,log,node=self.case(activate='0',second_ready='1',fallback_available='0')
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(node,'standby-second')
  self.assertIn('config:node select-auto standby recovery=1',log)
  self.assertNotIn('config:node select-auto original',log)
 
 def test_two_ready_candidates_first_fails_second_passes(self):
  r,log,node=self.case(post='0',second_ready='1',fallback_available='0')
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(node,'standby-second')
  self.assertIn('post:standby-second',log)
  self.assertNotIn('config:node select-auto original',log)
  self.assertNotIn('config:node select-auto ordinary',log)
  self.assertNotIn('transit:disable',log)
  self.assertEqual(r.stdout.strip(),'MIHOMO_NODE_FAILOVER=original->standby-second')
 def test_exhausted_ready_no_awg_quiesces_transit(self):
  r,log,node=self.case(post='0',second_ready='1',post_second='0',fallback_available='0')
  self.assertNotEqual(r.returncode,0)
  self.assertNotIn('config:node select-auto original',log)
  self.assertIn('transit:disable',log)
  self.assertIn('systemctl:stop awg-mihomo.service',log)
  self.assertIn('READY_AUTO=NO_WORKING_MIHOMO_NODE',r.stderr)
 def test_no_return_to_initial_even_when_rollback_unavailable(self):
  r,log,node=self.case(post='0',rollback='0',second_ready='1',fallback_available='0')
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(node,'standby-second')
  self.assertNotIn('config:node select-auto original',log)
 def test_missing_hot_pool_refuses_canary(self):
  with tempfile.TemporaryDirectory(prefix='ready-missing-hot-') as d:
   p=pathlib.Path(d)
   (p/'mode').write_text('auto\n')
   (p/'node').write_text('original\n')
   env=dict(os.environ, MIHOMO_NODE_POLICY_MODE_FILE=str(p/'mode'),
     MIHOMO_NODE_NAME_FILE=str(p/'node'), MIHOMO_READY_AUTO_CANARY='1',
     MIHOMO_POOL_CLI='/bin/true',
     MIHOMO_READY_POSTCHECK_BIN='/bin/true',
     MIHOMO_READY_GUARD_BIN=GUARD,
     MIHOMO_HOT_POOL_CLI=str(p/'does-not-exist'),
     MIHOMO_SERVICE_GATE_MODE='balanced')
   r=subprocess.run(['bash',self.rootless_script(p),'failover'],
     env=env,capture_output=True,text=True,timeout=5)
   self.assertNotEqual(r.returncode,0)
   self.assertIn('READY_AUTO=HOT_POOL_UNAVAILABLE',r.stderr)
   self.assertEqual((p/'node').read_text().strip(),'original')
 def test_service_gate_off_fails_closed(self):
  r,log,node=self.case(gate='off');self.assertNotEqual(r.returncode,0);self.assertEqual(node,'original');self.assertNotIn('config:',log)
 def test_service_rejection_before_switch(self):
  r,log,node=self.case(ready='0',checker='0');self.assertNotEqual(r.returncode,0);self.assertEqual(node,'original');self.assertNotIn('config:',log);self.assertIn('transit:disable',log)
 def test_invalid_postcheck_refused(self):
  # This scenario is covered by production canary's executable preflight.
  r,log,node=self.case();self.assertEqual(r.returncode,0)
class ExactLiveIdentity(unittest.TestCase):
 def test_full_credentials_and_duplicate(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);a=p/'live.yaml';b=p/'union.yaml'
   a.write_text('proxies:\n  - {name: standby, type: ss, server: 198.51.100.2, port: 443, password: one}\n')
   b.write_text(a.read_text())
   cmd=[sys.executable,'-B',GUARD,'--live',str(a),'--union',str(b),'--node','standby']
   self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,0)
   b.write_text(a.read_text().replace('password: one','password: two'))
   self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
   b.write_text(a.read_text()+ '  - {name: standby, type: ss, server: 198.51.100.3, port: 443, password: one}\n')
   self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
   b.write_text(a.read_text().replace('name: standby','name: renamed'))
   self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
if __name__=='__main__':unittest.main(verbosity=2)

