#!/usr/bin/env python3
"""Rootless tests for test-Pi independent Xray FIXED rescue (no systemd/net)."""
import importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"scripts/awg-xray-testpi-fixed-failover-rescue.py"
spec=importlib.util.spec_from_file_location("fixed_xray_rescue_test",SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class IndependentRescueTests(unittest.TestCase):
 def test_source_syntax(self):
  p=subprocess.run([sys.executable,"-B","-m","py_compile",str(SOURCE)],
                   capture_output=True,text=True,timeout=12)
  self.assertEqual(p.returncode,0,p.stderr)

 def test_snapshot_name_and_original_manifest_required(self):
  self.assertTrue(m.SNAP_RX.fullmatch("xray-auto-rescue-1792428005-2233"))
  for bad in ("/xray-auto-rescue-1-2","xray-auto-rescue-suffix",
              "xray-failover-1-2","../xray-auto-rescue-1-2"):
   self.assertIsNone(m.SNAP_RX.fullmatch(bad))
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);snap=base/"xray-auto-rescue-1-22";snap.mkdir()
   (snap/"manifest.json").write_text(json.dumps({
     "purpose":"Xray FIXED test-Pi independent restoration",
     "old":"HY2 A","xray":"VLESS B","saved":{"node-name":"0"*64,
       "provider.env":"0"*64,"config.yaml":"0"*64}
   }))
   with mock.patch.object(m,"BASE",base),mock.patch.object(m,"baseline_root"):
    with self.assertRaisesRegex(RuntimeError,"UNTRUSTED_SNAPSHOT"):
     m.check_snapshot(snap)

 def test_preflight_healthy_original_no_mutation(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d)
   for name in m.FILES:(home/name).write_text("safe")
   prov=home/"provider.yaml";prov.write_text("proxies: []")
   with mock.patch.object(m,"HOME",home),mock.patch.object(m,"PROVIDER",prov),mock.patch.object(m,"baseline_root"),mock.patch.object(m,"active",
       side_effect=lambda name:name!="awg-xray-vless.service"),mock.patch.object(
       m,"SELECTED",Path("/a-nonexistent-file-for-tests")),mock.patch.object(
       m,"BRIDGE",Path("/a-nonexistent-bridge-for-tests")),mock.patch.object(
       m,"RUNTIME_BRIDGE",Path("/a-nonexistent-runtime-bridge-for-tests")),mock.patch.object(
       m,"healthy_guard",return_value=True),mock.patch.object(m,"routes",
       return_value=("default dev mihomo0","default dev mihomo0")),mock.patch.object(
       m,"openai",return_value=True),mock.patch.object(m,"qualified_current",
       return_value=("HY2","VLESS")),mock.patch.object(m,"ok",
       return_value="NEXT LEFT LAST PASSED UNIT"):
    self.assertEqual(m.preflight(),("HY2","VLESS"))

 def test_scheduled_recovery_has_two_independent_timers_before_fault(self):
  source=SOURCE.read_text()
  a=source.index('for unit,delay in zip(units,(TIMER_A,TIMER_B))')
  b=source.index('jsonput(snap/"state.json",{"status":"armed"')
  self.assertLess(a,b)
  self.assertIn('"--on-active="+str(delay)+"s"',source)
  self.assertIn('TIMER_A=180',source)
  self.assertIn('TIMER_B=330',source)
  self.assertIn('"/usr/bin/python3","-B",str(script),"--recover",str(snap)',source)
  self.assertIn('if current=="cancelled":return' if False else
                'if state.get("status")=="cancelled":return',source)
  self.assertIn('if state.get("result")=="PASS":return',source)
  self.assertIn('not active("awg-xray-vless.service")',source)

 def test_a_completed_recovery_is_idempotent(self):
  with tempfile.TemporaryDirectory() as d:
   s=Path(d)/"xray-auto-rescue-1-2";s.mkdir()
   (s/"state.json").write_text(json.dumps({"status":"restored","result":"PASS"}))
   with mock.patch.object(m,"check_snapshot",return_value={"old":"HY2"}):
    with mock.patch.object(m,"run") as run:
     m.restore(s)
    run.assert_not_called()

 def test_no_fault_no_changes_to_healthy_original(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);s=base/"xray-auto-rescue-1-2";s.mkdir()
   state=s/"state.json";state.write_text(json.dumps({"status":"armed","result":None}))
   node=base/"node";node.write_text("HY2")
   with (mock.patch.object(m,"CURRENT",node),
         mock.patch.object(m,"MAINT",base/"maintenance.lock"),
         mock.patch.object(m,"SELECTED",base/"selected"),
         mock.patch.object(m,"BRIDGE",base/"bridge"),
         mock.patch.object(m,"check_snapshot",return_value={"old":"HY2","xray":"VLESS"}),
         mock.patch.object(m,"active",side_effect=lambda x:x in ("awg-mihomo.service","awg-selection-monitor.service")),
         mock.patch.object(m,"healthy_guard",return_value=True),
         mock.patch.object(m,"openai",return_value=True),
         mock.patch.object(m,"run") as run):
    m.restore(s)
   self.assertEqual(json.loads(state.read_text())["result"],"PASS")
   self.assertEqual(json.loads(state.read_text())["status"],"unchanged")
   run.assert_not_called()

 def test_fault_is_removed_even_if_original_recovers_before_first_rescue(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);snap=base/"xray-auto-rescue-1-2";snap.mkdir()
   (snap/"state.json").write_text(json.dumps({"status":"armed","result":None}))
   (snap/"fault.json").write_text(json.dumps({
    "kind":"nft_endpoint_blackhole","table":"awg_xray_fixed_test"}))
   current=base/"node-name";current.write_text("HY2")
   calls=[]
   def shell(*args,**kwargs):
    calls.append(args)
    if args[:3]==("nft","list","table"):
     return mock.Mock(returncode=0,stdout='table inet awg_xray_fixed_test { chain block_output { comment "AWG-XRAY-FIXED-TEST" } }')
    return mock.Mock(returncode=0,stdout="")
   with (mock.patch.object(m,"CURRENT",current),
         mock.patch.object(m,"MAINT",base/"maintenance.lock"),
         mock.patch.object(m,"BRIDGE",base/"bridge"),
         mock.patch.object(m,"SELECTED",base/"selected"),
         mock.patch.object(m,"check_snapshot",return_value={"old":"HY2","xray":"VLESS"}),
         mock.patch.object(m,"run",side_effect=shell),
         mock.patch.object(m,"ok",side_effect=lambda *args,**kwargs:calls.append(args) or ""),
         mock.patch.object(m,"active",side_effect=lambda n:n in ("awg-mihomo.service","awg-selection-monitor.service")),
         mock.patch.object(m,"healthy_guard",return_value=True),
         mock.patch.object(m,"openai",return_value=True)):
    m.restore(snap)
   result=json.loads((snap/"state.json").read_text())
   self.assertEqual(result["status"],"unchanged")
   self.assertIn(("nft","delete","table","inet","awg_xray_fixed_test"),calls)
   self.assertNotIn(("systemctl","stop","awg-mihomo.service"),calls)

 def test_active_xray_recovery_keeps_transit_closed_until_real_https(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);s=base/"xray-auto-rescue-1-2";s.mkdir()
   (s/"state.json").write_text(json.dumps({"status":"armed","result":None}))
   home=base/"etc";home.mkdir()
   (home/"node-name").write_text("VLESS")
   (home/"config.yaml").write_text("proxies: [HY2]\n")
   saved={"node-name":b"HY2\n","config.yaml":b"proxies: [HY2]\n"}
   for name,data in saved.items():(s/(name+".previous")).write_bytes(data)
   calls=[]
   def command(*args,**kwargs):
    calls.append(args)
    return ""
   def is_active(unit):
    return unit in ("ssh.service","awg-selection-monitor.service")
   with (mock.patch.object(m,"HOME",home),mock.patch.object(m,"CURRENT",home/"node-name"),
         mock.patch.object(m,"MAINT",base/"maintenance.lock"),
         mock.patch.object(m,"SELECTED",base/"selected"),
         mock.patch.object(m,"BRIDGE",base/"bridge"),
         mock.patch.object(m,"RUNTIME_BRIDGE",base/"runtime"),
         mock.patch.object(m,"check_snapshot",return_value={
           "old":"HY2","xray":"VLESS","saved":{"node-name":m.sha(s/"node-name.previous"),
                             "config.yaml":m.sha(s/"config.yaml.previous")},
           "provider_sha256":"0"*64,"chain_sha256":"0"*64}),
         mock.patch.object(m,"PROVIDER",base/"provider"),
         mock.patch.object(m,"CHAIN",base/"chain"),
         mock.patch.object(m,"sha",return_value="0"*64),
         mock.patch.object(m,"failclosed",side_effect=lambda:calls.append(("CLOSED",))),
         mock.patch.object(m,"ok",side_effect=command),
         mock.patch.object(m,"active",side_effect=is_active),
         mock.patch.object(m,"reinstate_routes"),
         mock.patch.object(m,"controller_now",return_value="HY2"),
         mock.patch.object(m,"openai",return_value=False),
         mock.patch.object(m.time,"sleep")):
    with self.assertRaisesRegex(RuntimeError,"ORIGINAL_TUN_HTTPS_NOT_READY"):
     m.restore(s)
   self.assertEqual(calls[0],("CLOSED",))
   self.assertIn(("systemctl","stop","awg-xray-vless.service"),calls)
   self.assertNotIn(("/usr/local/sbin/awg-transit-routing","apply"),calls)

 def test_router_ssh_dns_not_mutated_and_foreign_override_rejected(self):
  src=SOURCE.read_text()
  for forbidden in ('"systemctl","stop","ssh.service"',
     '"systemctl","restart","dnsmasq.service"',
     '"ip","rule","del"',"/interface sstp","/ip firewall"):
   self.assertNotIn(forbidden,src)
  self.assertIn("b.read_bytes()==OWNED_OVERRIDE",src)
  self.assertIn('"PROVIDER_OR_FIXED_CHANGED_KEEP_FAIL_CLOSED"',src)
  self.assertIn('healthy_guard() and openai()',src)
  self.assertIn('failclosed()',src)

if __name__=="__main__":unittest.main()
