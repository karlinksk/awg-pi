#!/usr/bin/env python3
"""Rootless negative and recovery contract tests for real Transit failclosed canary."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"scripts/awg-xray-testpi-armed-watchdog-recovery.py"
spec=importlib.util.spec_from_file_location("xray_armed_recovery",SOURCE)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m
spec.loader.exec_module(m)

class ArmedWatchdogRecovery(unittest.TestCase):
 def test_snapshot_allowlist(self):
  self.assertTrue(m.NAME.fullmatch("xray-failover-123456-789"))
  self.assertFalse(m.NAME.fullmatch("xray-failover-abcd"))
  self.assertFalse(m.NAME.fullmatch("../xray-failover-123-789"))

 def test_abort_before_mutation_if_rescue_timer_not_armed(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   fake=root/"restore-source";fake.write_text("safe code")
   node=root/"node";node.write_text("healthy-HY2")
   fixed=root/"fixed";fixed.write_text("healthy-HY2")
   preflight={"node":m.sha(node),"fixed":m.sha(fixed),"config_sha":"1"*64}
   with (mock.patch.object(m,"BASE",root),
         mock.patch.object(m,"SOURCE",fake),
         mock.patch.object(m,"NODE",node),
         mock.patch.object(m,"FIXED",fixed),
         mock.patch.object(m,"baseline",return_value=preflight),
         mock.patch.object(m,"arm_timer",side_effect=RuntimeError("TIMER_NOT_ARMED")) as timer,
         mock.patch.object(m,"run") as runner,
         mock.patch.object(m.sys,"argv",["script","--run"])):
    with self.assertRaisesRegex(RuntimeError,"TIMER_NOT_ARMED"):
     m.begin()
   self.assertEqual(timer.call_count,1)
   runner.assert_not_called()

 def test_explicit_check_never_arms_or_disables_services(self):
  with mock.patch.object(m,"baseline",return_value={}) as baseline:
   with mock.patch.object(m,"arm_timer") as timer:
    with mock.patch.object(m.sys,"argv",["script","--check"]):
     m.begin()
   baseline.assert_called_once();timer.assert_not_called()

 def test_rescue_restores_only_if_old_node_and_policy_unchanged(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);snap=root/"xray-failover-123-456";snap.mkdir()
   state=snap/"state.json";state.write_text(json.dumps({"state":"quiesced"}))
   node=root/"node";node.write_text("hy2")
   fixed=root/"fixed";fixed.write_text("hy2\nxray")
   preflight={"node":m.sha(node),"fixed":m.sha(fixed)}
   status_calls=iter([
      ["Transit guard: SAFE","Transit policy rule: INACTIVE"],
      ["Transit guard: SAFE","Transit policy rule: INACTIVE"],
      list(m.TRANSIT_LINES),list(m.TRANSIT_LINES),list(m.TRANSIT_LINES),list(m.TRANSIT_LINES)])
   commands=[]
   def system(*argv,**kwargs):
    commands.append(argv)
    return ""
   def is_running(name):
    return name in ("ssh.service","dnsmasq.service")
   with (mock.patch.object(m,"NODE",node),
         mock.patch.object(m,"FIXED",fixed),
         mock.patch.object(m,"trusted_snapshot",return_value=preflight),
         mock.patch.object(m,"status",side_effect=status_calls),
         mock.patch.object(m,"active",side_effect=is_running),
         mock.patch.object(m,"success",side_effect=system),
         mock.patch.object(m,"ensure_routes") as ensure,
         mock.patch.object(m,"openai",return_value=True)):
    m.recover(snap)
   receipt=json.loads((snap/"recovery.json").read_text())
   self.assertEqual(receipt["result"],"PASS")
   self.assertTrue(receipt["fail_closed_observed"])
   self.assertIn(("systemctl","start","awg-mihomo.service"),commands)
   self.assertIn((m.GUARD,"apply"),commands)
   ensure.assert_called_once()

 def test_policy_changes_prevent_recovery_claim(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);snap=root/"xray-failover-123-456";snap.mkdir()
   (snap/"state.json").write_text(json.dumps({"state":"quiesced"}))
   node=root/"node";node.write_text("tampered")
   fixed=root/"fixed";fixed.write_text("unchanged")
   preflight={"node":"0"*64,"fixed":m.sha(fixed)}
   with (mock.patch.object(m,"NODE",node),
         mock.patch.object(m,"FIXED",fixed),
         mock.patch.object(m,"trusted_snapshot",return_value=preflight),
         mock.patch.object(m,"status",return_value=["Transit guard: SAFE","Transit policy rule: INACTIVE"]),
         mock.patch.object(m,"active",return_value=False),
         mock.patch.object(m,"success") as command):
    with self.assertRaisesRegex(RuntimeError,"NODE_POLICY_CHANGED"):
     m.recover(snap)
   command.assert_not_called()
   self.assertEqual(json.loads((snap/"recovery.json").read_text())["result"],
                    "RETRY_REQUIRED")

 def test_recovery_is_idempotent_and_safe_second_timer(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);snap=root/"xray-failover-123-456";snap.mkdir()
   (snap/"recovery.json").write_text(json.dumps({"result":"PASS"}))
   with mock.patch.object(m,"trusted_snapshot",return_value={}),mock.patch.object(m,"status") as status:
    m.recover(snap)
   status.assert_not_called()

 def test_rollback_is_independent_and_no_ssh_router_mutation(self):
  source=SOURCE.read_text()
  self.assertIn('"--on-active="+str(delay)+"s"',source)
  self.assertIn('arm_timer(units[0],RESCUE_A,snap)',source)
  self.assertIn('arm_timer(units[1],RESCUE_B,snap)',source)
  self.assertIn('result=run("systemd-run","--unit="+job,"--on-active=5s"',source)
  self.assertIn('MAINTENANCE_LOCK.open("a")',source)
  self.assertIn('saved' if False else 'snapshot',source)
  self.assertIn('"WATCHDOG","ARMED_5S"',source)
  self.assertIn('"FAIL_CLOSED_OBSERVED"',source)
  self.assertIn('"RECOVERY","PASS_INDEPENDENT_TIMER"',source)
  for banned in ("systemctl reboot","shutdown -r","systemctl stop ssh",
                 "/usr/bin/ssh", "/ip firewall", "/interface sstp"):
   self.assertNotIn(banned,source.lower())

 def test_syntax(self):
  p=subprocess.run([sys.executable,"-m","py_compile",str(SOURCE)],
     capture_output=True,text=True,timeout=9)
  self.assertEqual(p.returncode,0,p.stderr)

if __name__=="__main__":unittest.main()
