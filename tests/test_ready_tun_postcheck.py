import os,pathlib,subprocess,tempfile,unittest
HERE=pathlib.Path(__file__).resolve().parent
SCRIPT=str(HERE/'ready_postcheck_tun.sh' if (HERE/'ready_postcheck_tun.sh').exists() else HERE.parent/'src/awg-mihomo-ready-postcheck-tun')
class PostcheckTests(unittest.TestCase):
 def case(self,node='candidate',mark='1',ip='8.8.8.8',api='401',link='1',attempts='1',mark_recover='0',api_recover='0',route_polls='1'):
  with tempfile.TemporaryDirectory(prefix='tun-verifier-') as d:
   p=pathlib.Path(d)
   (p/'node').write_text(node+'\n')
   (p/'mark-counter').write_text('0')
   (p/'api-counter').write_text('0')
   mockip=p/'ip'
   mockip.write_text('''#!/bin/bash
case "$*" in
 "-o link show dev mihomo0") [[ "$LINK_OK" == 1 ]] && echo 'mihomo0: UP';;
 "-4 route show table 100") echo 'default dev mihomo0 scope link';;
 "-4 route get 1.1.1.1 mark 0x100") if [[ "$MARK_RECOVER" == 1 ]]; then n=$(cat "$MARK_COUNTER"); n=$((n+1)); echo "$n" >"$MARK_COUNTER"; if (( n == 1 )); then echo '1.1.1.1 dev eth0'; else echo '1.1.1.1 dev mihomo0'; fi; else [[ "$MARK_OK" == 1 ]] && echo '1.1.1.1 dev mihomo0' || echo '1.1.1.1 dev eth0'; fi;;
esac
''')
   mockip.chmod(0o755)
   mockcurl=p/'curl'
   mockcurl.write_text('''#!/bin/bash
case "$*" in
 *api.ipify.org*) echo "$EGRESS";;
 *api.openai.com/v1/models*) if [[ "$API_RECOVER" == 1 ]]; then n=$(cat "$API_COUNTER"); n=$((n+1)); echo "$n" >"$API_COUNTER"; if (( n == 1 )); then printf 403; else printf 401; fi; else printf '%s' "$API_CODE"; fi;;
esac
''')
   mockcurl.chmod(0o755)
   env=dict(os.environ,MIHOMO_READY_NODE_FILE=str(p/'node'),MIHOMO_READY_IP_BIN=str(mockip),MIHOMO_READY_CURL_BIN=str(mockcurl),LINK_OK=link,MARK_OK=mark,EGRESS=ip,API_CODE=api,MIHOMO_READY_POSTCHECK_ATTEMPTS=attempts,MIHOMO_READY_POSTCHECK_DELAY='0',MARK_RECOVER=mark_recover,API_RECOVER=api_recover,MARK_COUNTER=str(p/'mark-counter'),API_COUNTER=str(p/'api-counter'),MIHOMO_READY_ROUTE_POLLS=route_polls,MIHOMO_READY_ROUTE_DELAY='0')
   r=subprocess.run(['bash',SCRIPT,'candidate'],env=env,text=True,capture_output=True,timeout=4)
   return r
 def test_route_deadline_fails_closed(self):
  r=self.case(mark='0',route_polls='3');self.assertNotEqual(r.returncode,0);self.assertIn('READY_TUN_CHECK=MARK_MISMATCH',r.stdout);self.assertIn('READY_TUN_ROUTE_POLLS=3',r.stdout)
 def test_route_grace_recover(self):
  r=self.case(mark_recover='1',route_polls='3');self.assertEqual(r.returncode,0,r.stdout);self.assertIn('READY_TUN_ROUTE_POLLS=2',r.stdout);self.assertIn('READY_TUN_ATTEMPTS=1',r.stdout)
 def test_api_grace_recover(self):
  r=self.case(attempts='3',api_recover='1');self.assertEqual(r.returncode,0,r.stdout);self.assertIn('READY_TUN_ATTEMPTS=2',r.stdout);self.assertIn('READY_TUN_RECOVERED_FROM=',r.stdout)
 def test_stable_403_does_not_pass(self):
  r=self.case(attempts='3',api='403');self.assertNotEqual(r.returncode,0);self.assertIn('READY_TUN_CHECK=OPENAI_NOT_QUALIFIED',r.stdout);self.assertIn('READY_TUN_ATTEMPTS=3',r.stdout)
 def test_invalid_public_egress(self):
  r=self.case(ip='192.168.112.1');self.assertNotEqual(r.returncode,0);self.assertIn('READY_TUN_CHECK=EGRESS_INVALID',r.stdout)
 def test_valid_tun(self): self.assertEqual(self.case().returncode,0)
 def test_changed_node(self): self.assertNotEqual(self.case(node='other').returncode,0)
 def test_missing_mark(self): self.assertNotEqual(self.case(mark='0').returncode,0)
 def test_down_interface(self): self.assertNotEqual(self.case(link='0').returncode,0)
 def test_bad_egress(self): self.assertNotEqual(self.case(ip='192.168.112.1').returncode,0)
 def test_api_region_denied(self): self.assertNotEqual(self.case(api='403').returncode,0)
if __name__=='__main__': unittest.main(verbosity=2)

