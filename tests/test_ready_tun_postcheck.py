import os,pathlib,subprocess,tempfile,unittest
HERE=pathlib.Path(__file__).resolve().parent
SCRIPT=str(HERE/'ready_postcheck_tun.sh' if (HERE/'ready_postcheck_tun.sh').exists() else HERE.parent/'src/awg-mihomo-ready-postcheck-tun')
class PostcheckTests(unittest.TestCase):
 def case(self,node='candidate',mark='1',ip='8.8.8.8',api='401',link='1'):
  with tempfile.TemporaryDirectory(prefix='tun-verifier-') as d:
   p=pathlib.Path(d)
   (p/'node').write_text(node+'\n')
   mockip=p/'ip'
   mockip.write_text('''#!/bin/bash
case "$*" in
 "-o link show dev mihomo0") [[ "$LINK_OK" == 1 ]] && echo 'mihomo0: UP';;
 "-4 route show table 100") echo 'default dev mihomo0 scope link';;
 "-4 route get 1.1.1.1 mark 0x100") [[ "$MARK_OK" == 1 ]] && echo '1.1.1.1 dev mihomo0' || echo '1.1.1.1 dev eth0';;
esac
''')
   mockip.chmod(0o755)
   mockcurl=p/'curl'
   mockcurl.write_text('''#!/bin/bash
case "$*" in
 *api.ipify.org*) echo "$EGRESS";;
 *api.openai.com/v1/models*) printf '%s' "$API_CODE";;
esac
''')
   mockcurl.chmod(0o755)
   env=dict(os.environ,MIHOMO_READY_NODE_FILE=str(p/'node'),MIHOMO_READY_IP_BIN=str(mockip),MIHOMO_READY_CURL_BIN=str(mockcurl),LINK_OK=link,MARK_OK=mark,EGRESS=ip,API_CODE=api)
   r=subprocess.run(['bash',SCRIPT,'candidate'],env=env,text=True,capture_output=True,timeout=4)
   return r
 def test_valid_tun(self): self.assertEqual(self.case().returncode,0)
 def test_changed_node(self): self.assertNotEqual(self.case(node='other').returncode,0)
 def test_missing_mark(self): self.assertNotEqual(self.case(mark='0').returncode,0)
 def test_down_interface(self): self.assertNotEqual(self.case(link='0').returncode,0)
 def test_bad_egress(self): self.assertNotEqual(self.case(ip='192.168.112.1').returncode,0)
 def test_api_region_denied(self): self.assertNotEqual(self.case(api='403').returncode,0)
if __name__=='__main__': unittest.main(verbosity=2)

[executed on device: awg-upgrade (7ff7c792-9f11-48ea-9b09-8734178c247a)]