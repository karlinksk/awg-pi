#!/usr/bin/env python3
"""Offline clean-install / upgrade strategy contract without executing installer or touching Pi."""
import os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INS=(ROOT/"install.sh").read_text()
UPD=(ROOT/"src/awg-update").read_text()
START=INS.split("# Fresh installs PREPARE conservative transport AUTO only.",1)[1].split("\n",1)[1].split('ACTIVE_TRANSPORT="$(cat "$TRANSPORT_FILE"',1)[0]
TIMER=INS.split("# Base pool-refresh and Stage18 runtime are provider-guarded; only Hot Pool",1)[1].split("\n",1)[1].split('ACTIVE_TRANSPORT="$(cat "$TRANSPORT_FILE"',1)[0]
class AutoInstallerTests(unittest.TestCase):
 def run_case(self,mode="auto",upgrade=False):
  with tempfile.TemporaryDirectory(prefix="auto-strategy-installer-") as directory:
   root=Path(directory); pbr=root/"etc"/"awg-pbr";cfg=pbr/"transports"/"mihomo";cfg.mkdir(parents=True)
   if mode is not None:(cfg/"node-policy.mode").write_text(mode+"\n")
   ready=root/"ready";enabled=root/"hot-enabled";active=root/"hot-active"
   log=root/"systemctl-log"; log.write_text("")
   policy=root/"policy"
   policy.write_text(r'''#!/bin/bash
if [[ "$1" == ready-auto ]]; then echo "$2" >"$TEST_READY"; exit 0; fi
exit 17
''')
   policy.chmod(0o700)
   # No systemd, routes, network or release install scripts are run.
   bash=r'''set -Eeuo pipefail
PBR_DIR="$TEST_PBR"
UPGRADE_EXISTING="$TEST_UPGRADE"
SELECTION_CLI=/bin/true
MIHOMO_NODE_POLICY_CLI="$TEST_POLICY"
ok(){ :; }
die(){ printf 'INSTALLER_ERROR=%s\n' "$1" >&2; exit 23; }
systemctl(){
 printf '%s\n' "$*" >>"$TEST_CALLS"
 case "$1" in
  enable)
   [[ "$2" == --now ]] || exit 31
   if [[ "$3" == awg-mihomo-hot-pool.timer ]];then
     echo 1 >"$TEST_ENABLED";echo 1 >"$TEST_ACTIVE"
   fi;;
  disable)
   [[ "$2" == --now ]] || exit 32
   if [[ "$3" == awg-mihomo-hot-pool.timer ]];then
     echo 0 >"$TEST_ENABLED";echo 0 >"$TEST_ACTIVE"
   fi;;
  is-active)
   [[ "$2" == --quiet ]] || exit 33
   if [[ "$3" == awg-mihomo-hot-pool.service ]]; then return 1; fi
   if [[ "$3" != awg-mihomo-hot-pool.timer ]]; then return 0; fi
   [[ -f "$TEST_ACTIVE" ]] && [[ "$(cat "$TEST_ACTIVE")" == 1 ]];;
  is-enabled)
   [[ "$2" == --quiet && "$3" == awg-mihomo-hot-pool.timer ]] || exit 34
   [[ -f "$TEST_ENABLED" ]] && [[ "$(cat "$TEST_ENABLED")" == 1 ]];;
  *) exit 35;;
 esac
}
'''
   script=bash+"\n"+START+"\n"+TIMER
   result=subprocess.run(["bash","-c",script],capture_output=True,text=True,timeout=4,
        env=dict(os.environ,TEST_PBR=str(pbr),TEST_UPGRADE=str(int(upgrade)),
        TEST_POLICY=str(policy),TEST_READY=str(ready),TEST_ENABLED=str(enabled),
        TEST_ACTIVE=str(active),TEST_CALLS=str(log)))
   return result,(ready.read_text().strip() if ready.exists() else "UNTOUCHED"),\
     log.read_text(),(enabled.read_text().strip() if enabled.exists() else "UNTOUCHED")
 def test_default_auto_keeps_ready_and_hot_pool_off(self):
  for mode in ("auto",None):
   with self.subTest(mode=mode):
    r,ready,calls,enabled=self.run_case(mode)
    self.assertEqual(r.returncode,0,r.stderr)
    self.assertEqual((ready,enabled),("UNTOUCHED","UNTOUCHED"))
    self.assertNotIn("enable --now awg-mihomo-hot-pool.timer",calls)
    self.assertIn("enable --now awg-mihomo-pool-refresh.timer",calls)
 def test_clean_install_does_not_choose_fixed_until_postinstall(self):
  self.assertNotIn('"$FIRST_RUN_CLI" wizard',INS)
  self.assertNotIn('"$MIHOMO_NODE_POLICY_CLI" mode fixed',INS)
  self.assertIn('No VPN onboarding during clean install',INS)
  self.assertIn('Deferred VPN and Operating Mode configuration',INS)
  r,ready,calls,enabled=self.run_case("auto")
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual((ready,enabled),("UNTOUCHED","UNTOUCHED"))
 def test_upgrade_never_overwrites_active_settings(self):
  for mode in ("fixed","auto",None):
   r,ready,calls,enabled=self.run_case(mode,upgrade=True)
   self.assertEqual(r.returncode,0,r.stderr)
   self.assertEqual((ready,calls,enabled),("UNTOUCHED","","UNTOUCHED"))
 def test_clean_install_no_profile_import_and_no_transit_activation(self):
  self.assertIn('[[ ! -e "$CONF_FILE" ]]',INS)
  self.assertIn('! -e /var/lib/awg-pbr/mihomo/providers/subscription.yaml',INS)
  self.assertIn('! -e "$PBR_DIR/transports/mihomo/provider.env"',INS)
  self.assertIn('[[ "$(cat "$MODE_FILE")" == selective &&',INS)
  self.assertIn('"$(cat "$TRANSPORT_FILE")" == unconfigured ]]',INS)
  self.assertNotIn('ask "Режим работы" "1"',INS)
  self.assertIn('sudo awg-menu',INS)
 def test_upgrade_checks_chain_ready_gate_and_timer(self):
  self.assertIn('"$PBR_DIR/transports/mihomo/service-eligibility.mode"',INS)
  for s in ('node-policy.mode','node-policy.nodes','ready-auto.mode'):
   self.assertIn(s,INS)
  self.assertIn('UPGRADE_HOT_TIMER_ENABLEMENT="$(systemctl is-enabled',INS)
  self.assertIn('UPGRADE_HOT_TIMER_RUNTIME="$(systemctl is-active',INS)
  self.assertIn('[[ "$_current_hot_enablement" == "$UPGRADE_HOT_TIMER_ENABLEMENT"',INS)
  self.assertIn('"$_current_hot_runtime" == "$UPGRADE_HOT_TIMER_RUNTIME"',INS)
  self.assertIn('hot-pool-timer-state',UPD)
  self.assertIn('systemctl disable --now awg-mihomo-hot-pool.timer',UPD)
  self.assertIn('systemctl enable --now awg-mihomo-hot-pool.timer',UPD)
 def test_source_helpers_precede_onboarding_and_timer(self):
  self.assertLess(INS.index('install_project_helper src/awg-menu /usr/local/sbin/awg-menu'),
                  INS.index("# Fresh installs PREPARE conservative transport AUTO only."))
  self.assertLess(INS.index('install_project_helper src/awg-mihomo-node-policy "$MIHOMO_NODE_POLICY_CLI"'),
                  INS.index("# Fresh installs PREPARE conservative transport AUTO only."))
  self.assertIn('auto-strategy status|ready|classic',(ROOT/"src/awg-mihomo-node-policy").read_text())
  self.assertIn('mihomo_auto_strategy_menu(){',(ROOT/"src/awg-menu").read_text())
if __name__=="__main__":unittest.main()
