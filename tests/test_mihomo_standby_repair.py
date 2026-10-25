"""Rootless tests for AWG-safe one-shot Mihomo standby repair."""
import os, pathlib, subprocess, tempfile, unittest
SRC=pathlib.Path(__file__).resolve().parents[1]/"src/awg-mihomo-node-policy"
ROOT_GUARD='[[ ${EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"'
class StandbyRepair(unittest.TestCase):
 def run_case(self,selected='awg',healthy='yes',routes='yes',ready='yes',tun='yes',canary='1'):
  with tempfile.TemporaryDirectory(prefix='standby-repair-') as td:
   p=pathlib.Path(td)
   script=SRC.read_text()
   self.assertEqual(script.count(ROOT_GUARD),1)
   (p/'policy').write_text(script.replace(ROOT_GUARD,': # mock nonroot'))
   for f,value in [('node','original'),('mode','auto'),('opmode','transit'),('events','')]:
    (p/f).write_text(value+'\n')
   mocks={
    'transport':'''#!/bin/bash
echo "transport:$*" >> "$EVENTS"
if [[ "$1" == get ]]; then echo "$SELECTED"; exit; fi
[[ "$1" == check && "$2" == awg && "$AWG_OK" == yes ]]
''',
    'ip':'''#!/bin/bash
echo "ip:$*" >> "$EVENTS"
if [[ "$*" == "-4 route show table 100" || "$*" == "-4 route show table 101" ]]; then
 [[ "$ROUTES_OK" == yes ]] && echo "default dev awg0 scope link" || echo "default dev mihomo0 scope link"
elif [[ "$*" == "link show dev mihomo0" ]]; then exit 0; else exit 2; fi
''',
    'curl':'''#!/bin/bash
echo "curl:$*" >> "$EVENTS"
[[ "$TUN_OK" == yes ]] || exit 35
if [[ "$*" == *"api.ipify.org"* ]]; then echo 185.199.110.153
elif [[ "$*" == *"api.openai.com"* ]]; then printf 401
else exit 2; fi
''',
    'pool':'''#!/bin/bash
echo "pool:$*" >> "$EVENTS"
[[ "$1" == best ]] && exit 3 || exit 0
''',
    'hot':'''#!/bin/bash
echo "hot:$*" >> "$EVENTS"
if [[ "$*" == *" best"* && "$READY" == yes && "$*" != *"--exclude standby"* ]]; then echo standby; exit 0; fi
exit 3
''',
    'configure':'''#!/bin/bash
echo "config:$*" >> "$EVENTS"
[[ "$*" == "node select-auto standby" ]] || exit 1
echo standby > "$NODE_FILE"
''',
    'systemctl':'''#!/bin/bash
echo "systemctl:$*" >> "$EVENTS"
[[ "$1" == stop && "$2" == awg-mihomo.service ]]
''',
    'post':'''#!/bin/bash
echo BAD_LEGACY_POSTCHECK >> "$EVENTS"
exit 19
''',
    'transit':'''#!/bin/bash
echo ROUTING_CHANGED >> "$EVENTS"
''',
    'failopen':'''#!/bin/bash
echo ROUTING_CHANGED >> "$EVENTS"
'''
   }
   mocks['guard']='''#!/usr/bin/env python3
import sys
sys.exit(0)
'''
   for name,code in mocks.items():
    f=p/name;f.write_text(code);f.chmod(0o755)
   env=dict(os.environ,PATH=str(p)+':'+os.environ['PATH'],
    MIHOMO_NODE_POLICY_MODE_FILE=str(p/'mode'),MIHOMO_NODE_NAME_FILE=str(p/'node'),
    MIHOMO_AUTO_MODE_FILE=str(p/'opmode'),MIHOMO_AUTO_TRANSPORT_CLI=str(p/'transport'),
    MIHOMO_AUTO_SYSTEMCTL=str(p/'systemctl'),MIHOMO_POOL_CLI=str(p/'pool'),
    MIHOMO_HOT_POOL_CLI=str(p/'hot'),MIHOMO_CONFIGURE_BIN=str(p/'configure'),
    MIHOMO_UNIFIED_NODE_CLI=str(p/'missing-unified-cli'),
    MIHOMO_READY_GUARD_BIN=str(p/'guard'),MIHOMO_READY_POSTCHECK_BIN=str(p/'post'),
    MIHOMO_READY_AUTO_CANARY=canary,MIHOMO_SERVICE_GATE_MODE='balanced',
    MIHOMO_STANDBY_CURL_BIN=str(p/'curl'),MIHOMO_AUTO_TRANSIT_ROUTING=str(p/'transit'),
    MIHOMO_AUTO_FAILOPEN=str(p/'failopen'),EVENTS=str(p/'events'),
    NODE_FILE=str(p/'node'),SELECTED=selected,AWG_OK=healthy,
    ROUTES_OK=routes,READY=ready,TUN_OK=tun)
   r=subprocess.run(['bash',str(p/'policy'),'standby-repair'],env=env,
                    capture_output=True,text=True,timeout=16)
   return r,(p/'events').read_text(),(p/'node').read_text().strip()
 def assert_safe(self,events):
  self.assertNotIn('ROUTING_CHANGED',events)
  self.assertNotIn('BAD_LEGACY_POSTCHECK',events)
 def test_qualified_tun_and_unchanged_awg(self):
     r,log,node=self.run_case()
     self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(node,'standby')
     self.assertNotIn('curl:',log);self.assertNotIn('systemctl:stop',log);self.assert_safe(log)
 def test_no_ready_does_not_disable_transit(self):
  r,log,node=self.run_case(ready='no')
  self.assertNotEqual(r.returncode,0)
  self.assertEqual(node,'original')
  self.assertIn('STANDBY_REPAIR=NO_VERIFIED_NODE_AWG_UNCHANGED',r.stderr)
  self.assertIn('systemctl:stop awg-mihomo.service',log)
  self.assertNotIn('config:',log)
  self.assert_safe(log)
 def test_failed_tun_rejected(self):
     r,log,node=self.run_case(tun='no')
     self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(node,'standby')
     self.assertNotIn('curl:',log);self.assert_safe(log)
 def test_wrong_transport_refused(self):
  r,log,node=self.run_case(selected='mihomo')
  self.assertNotEqual(r.returncode,0)
  self.assertEqual(node,'original')
  self.assertNotIn('config:',log)
  self.assert_safe(log)
 def test_unhealthy_awg_refused(self):
  r,log,node=self.run_case(healthy='no')
  self.assertNotEqual(r.returncode,0)
  self.assertEqual(node,'original')
  self.assertNotIn('config:',log)
  self.assert_safe(log)
 def test_route_mismatch_refused(self):
  r,log,node=self.run_case(routes='no')
  self.assertNotEqual(r.returncode,0)
  self.assertEqual(node,'original')
  self.assertNotIn('config:',log)
  self.assert_safe(log)
 def test_canary_off_refused(self):
  r,log,node=self.run_case(canary='0')
  self.assertNotEqual(r.returncode,0)
  self.assertEqual(node,'original')
  self.assertNotIn('config:',log)
  self.assert_safe(log)
if __name__=='__main__':unittest.main(verbosity=2)
