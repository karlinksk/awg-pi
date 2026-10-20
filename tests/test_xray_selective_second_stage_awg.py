#!/usr/bin/env python3
"""Rootless behavior tests for the exact Selective second-stage AWG predicate.

No operating-system state is changed; all helper commands are mocked.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"scripts/awg-xray-selective-one-shot-failover.sh").read_text()
PREFIX="automatic_awg_recovery_verified(){\n"
CHECK=PREFIX+SOURCE.split(PREFIX,1)[1].split("\n}\n",1)[0]+"\n}\n"

class SelectiveAWGSecondStage(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        mock=self.root/"transport"
        mock.write_text("#!/bin/sh\n[ \"$1\" = get ] && printf '%s\\n' \"$TRANSPORT\"\n")
        mock.chmod(0o755)
        self.backend=str(mock)
    def probe(self,**kwargs):
        env=dict(os.environ,TRANSPORT="awg",XRAY_UP="0",MIHOMO_UP="0",
                 BAD_SERVICE="",BAD_TABLE="",API_OK="1",RULE_OK="1")
        env.update({k:str(v) for k,v in kwargs.items()})
        script=CHECK+r'''
backend="$MOCK_BACKEND"
up(){
  if [[ "$1" == "$BAD_SERVICE" ]];then return 1;fi
  if [[ "$1" == awg-xray-vless ]];then [[ "$XRAY_UP" == 1 ]];return;fi
  if [[ "$1" == awg-mihomo ]];then [[ "$MIHOMO_UP" == 1 ]];return;fi
  return 0
}
ip(){
  if [[ "$2" == rule ]];then
    if [[ "$RULE_OK" == 1 ]];then
      echo '100: from all fwmark 0x100 lookup 100'
    else
      echo '0: from all lookup local'
    fi
    return 0
  fi
  local table="$5"
  if [[ "$table" == "$BAD_TABLE" ]];then
    echo 'default dev mihomo0 scope link'
  else
    echo 'default dev awg0 scope link'
  fi
}
api(){ [[ "$1" == awg0 && "$API_OK" == 1 ]]; }
automatic_awg_recovery_verified
'''
        env["MOCK_BACKEND"]=self.backend
        return subprocess.run(["bash","-c",script],env=env,capture_output=True,text=True,timeout=5)
    def test_healthy_auto_awg_routes_and_https_is_success(self):
        p=self.probe()
        self.assertEqual(p.returncode,0,p.stderr)
    def test_name_only_awg_without_routes_fails(self):
        for table in ("100","101"):
            with self.subTest(table=table):
                self.assertNotEqual(self.probe(BAD_TABLE=table).returncode,0)
    def test_selective_mark_absent_fails_even_with_correct_awg_routes(self):
        self.assertNotEqual(self.probe(RULE_OK="0").returncode,0)

    def test_selector_did_not_switch(self):
        self.assertNotEqual(self.probe(TRANSPORT="mihomo").returncode,0)
    def test_xray_still_running_cannot_claim_fallback(self):
        self.assertNotEqual(self.probe(XRAY_UP="1").returncode,0)
    def test_mihomo_still_running_cannot_claim_fallback(self):
        self.assertNotEqual(self.probe(MIHOMO_UP="1").returncode,0)
    def test_management_or_dns_or_monitor_down_refuses(self):
        for service in ("ssh","dnsmasq","awg-selection-monitor","awg-quick@awg0"):
            with self.subTest(service=service):
                self.assertNotEqual(self.probe(BAD_SERVICE=service).returncode,0)
    def test_https_failure_refuses(self):
        self.assertNotEqual(self.probe(API_OK="0").returncode,0)

if __name__=="__main__":
    unittest.main()
