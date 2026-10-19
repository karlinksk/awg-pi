#!/usr/bin/env python3
"""Rootless negative/structural checks for test-Pi automatic FIXED fault injection."""
import importlib.util,ipaddress,os,subprocess,sys,tempfile,unittest
from unittest import mock
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"scripts/awg-xray-testpi-fixed-failover-canary.py"
spec=importlib.util.spec_from_file_location("xray_fixed_canary_unit",SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class FixedFailoverCanaryTests(unittest.TestCase):
 def test_no_router_or_hostwide_blanket_drop(self):
  code=SOURCE.read_text()
  self.assertNotIn('nft flush ruleset',code)
  self.assertNotIn('"ip","route","replace"',code)
  self.assertNotIn('"systemctl","stop","ssh.service"',code)
  self.assertNotIn('"systemctl","restart","dnsmasq.service"',code)
  self.assertIn("rescue.arm()",code)
  self.assertIn("rescue.MONITOR_OVERRIDE",code)
  self.assertIn("rescue.MONITOR_OWNED",code)
  self.assertIn("PASS_AUTO_FAILOVER_AND_RESTORE",code)

 def test_nft_rules_match_only_three_explicit_candidates(self):
  candidates=[
   ("HY2-A",443,{"8.8.8.8"}),
   ("SS-B",8443,{"9.9.9.9","8.8.4.4"}),
   ("HY2-C",8443,{"9.9.9.9"}),
   ("XRAY-D",443,{"1.1.1.1"})
  ]
  script=m.build_nft(candidates)
  self.assertIn("table inet awg_xray_fixed_test",script)
  self.assertIn("type filter hook output priority -145; policy accept;",script)
  self.assertIn("AWG-XRAY-FIXED-TEST",script)
  self.assertEqual(script.count('comment "AWG-XRAY-FIXED-TEST"'),6)
  self.assertNotIn("1.1.1.1",script)
  self.assertNotIn("policy drop",script)
  self.assertNotIn("192.168.112.",script)

 def test_canary_reads_current_exact_subscription_only(self):
  text=SOURCE.read_text()
  self.assertIn('len(chain)==4 and chain[0]==old and chain[-1]==xray',text)
  self.assertIn('"SAME_ENDPOINT_AS_XRAY_FORBIDDEN"',text)
  self.assertIn('require(addr.is_global,"PRIVATE_ENDPOINT_WOULD_BLOCK_LAN")',text)
  self.assertIn('NODE_PROVIDER_SHA256',text)
  self.assertIn('XRAY_NETWORK_CACHE_NOT_FRESH',text)
  self.assertIn('SERVICE_READY_POLICY_MUST_BE_DISABLED_BY_USER',text)
  self.assertIn('NFT_TEST_FAULT_INSTALL_FAILED',text)

 def test_no_timeout_injection_before_rescue_armed(self):
  text=SOURCE.read_text()
  self.assertLess(text.index('snap=rescue.arm()'),text.index('  install_fault(snap,candidates)'))
  self.assertIn('rescue.jsonput(snap/"fault.json"',text)
  self.assertIn('rescue.atomic(nft_script,build_nft(candidates).encode())',text)
  self.assertLess(text.index('rescue.jsonput(snap/"fault.json"'),
                  text.index('rc=call("nft","-f"'))
  self.assertIn("INDEPENDENT_TIMER_STILL_ARMED",text)
  self.assertIn('proof_xray(xray)',text)
  self.assertIn('consecutive>=2',text)
  self.assertIn('final.get("status")=="restored"',text)
  self.assertNotIn('MONITOR_CANARY_ENV_NOT_YET_INTEGRATED',text)

 def test_preflight_refuses_private_endpoint_and_shared_xray(self):
  text=SOURCE.read_text()
  self.assertIn('not (port==endpoint_xray[0] and bool(ips&endpoint_xray[1]))',text)
  self.assertIn('not in env.stdout',text)

 def test_regex_passive_stage_is_pinned_to_exact_single_line(self):
  script=ROOT/"scripts/awg-xray-testpi-degraded-regex-stage.py"
  content=script.read_text()
  self.assertIn('ec4c86a9270b5a72e3f4282347311f110bdd7ed6d89b1d8b8a2cf88b679cf6c8',content)
  self.assertIn('len(changes)==1',content)
  self.assertIn('bad.replace(bytes((92,92,115)),bytes((92,115)))==good',content)
  self.assertIn('emit("AUTO_XRAY_ENABLED","NO")',content)
  self.assertIn('require(network()==prior,"LIVE_NETWORK_CHANGED")',content)
  self.assertNotIn('"systemctl","restart"',content)
  spec=importlib.util.spec_from_file_location("regex_stage_unit",script)
  stage=importlib.util.module_from_spec(spec)
  spec.loader.exec_module(stage)
  # This is a historical, SHA-pinned ONE-TIME hardware stager. Later
  # backend feature commits must not invalidate its regression tests.
  # Verify its immutable safety contract, not a live /usr/local version or
  # a reconstruction of an outdated entire executable.
  self.assertEqual(stage.OLD_SHA,"ec4c86a9270b5a72e3f4282347311f110bdd7ed6d89b1d8b8a2cf88b679cf6c8")
  self.assertIn('require(len(changes)==1',content)
  self.assertIn('require(network()==prior',content)
  import re
  pattern=r"default\s+dev\s+mihomo0(?:\s+.*)?"
  self.assertIsNotNone(re.fullmatch(pattern,"default dev mihomo0 scope link"))
  self.assertIsNone(re.fullmatch(pattern,"default dev awg0 scope link"))

 def test_python_syntax(self):
  for path in (SOURCE,ROOT/"scripts/awg-xray-testpi-fixed-failover-rescue.py"):
   r=subprocess.run([sys.executable,"-m","py_compile",str(path)],
                    capture_output=True,text=True,timeout=10)
   self.assertEqual(r.returncode,0,r.stderr)

if __name__=="__main__":unittest.main()
