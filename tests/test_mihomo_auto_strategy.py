#!/usr/bin/env python3
"""Rootless strategy toggle tests: fake systemctl, no real systemd or routing."""
import os,subprocess,tempfile,unittest
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-node-policy"
ROOT_LINE='[[ '+chr(36)+'{EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"'
class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        src=SOURCE.read_text()
        assert ROOT_LINE in src
        src=src.replace(ROOT_LINE,': # root guard removed only in offline test fixture',1)
        self.policy=self.root/"policy";self.policy.write_text(src);self.policy.chmod(0o700)
        self.mode=self.root/"mode";self.mode.write_text("auto\n")
        self.ready=self.root/"ready";self.ready.write_text("1\n")
        self.order=self.root/"fixed.nodes"
        self.active=self.root/"timer-active";self.active.write_text("1")
        self.enabled=self.root/"timer-enabled";self.enabled.write_text("1")
        self.scan=self.root/"scanner-active";self.scan.write_text("0")
        self.error=self.root/"fail";self.error.write_text("none")
        self.mock=self.root/"mock-systemctl"
        self.mock.write_text("""#!/bin/bash
set -e
case "$1" in
 is-active)
   if [[ "$3" == awg-mihomo-hot-pool.service ]]; then
     [[ "$(cat "$TEST_SCAN")" == 1 ]]
   else
     [[ "$(cat "$TEST_ACTIVE")" == 1 ]]
   fi;;
 is-enabled) [[ "$(cat "$TEST_ENABLED")" == 1 ]];;
 enable)
   [[ "$(cat "$TEST_FAIL")" != enable ]] || exit 7
   printf '1' >"$TEST_ENABLED"
   if [[ "$2" == --now ]]; then printf '1' >"$TEST_ACTIVE"; fi;;
 disable)
   [[ "$(cat "$TEST_FAIL")" != disable ]] || exit 8
   printf '0' >"$TEST_ENABLED"
   if [[ "$2" == --now ]]; then printf '0' >"$TEST_ACTIVE"; fi;;
 start) printf '1' >"$TEST_ACTIVE";;
 stop) printf '0' >"$TEST_ACTIVE";;
 *) exit 11;;
esac
""")
        self.mock.chmod(0o700)
        self.good=self.root/"test-helper";self.good.write_text("#!/bin/sh\nexit 0\n");self.good.chmod(0o700)
        self.env=os.environ.copy()
        self.env.update(
            MIHOMO_NODE_POLICY_MODE_FILE=str(self.mode),
            MIHOMO_NODE_POLICY_ORDER_FILE=str(self.order),
            MIHOMO_READY_AUTO_MODE_FILE=str(self.ready),
            MIHOMO_READY_AUTO_CANARY="1",
            MIHOMO_STRATEGY_SYSTEMCTL=str(self.mock),
            MIHOMO_HOT_TIMER="awg-mihomo-hot-pool.timer",
            MIHOMO_HOT_SERVICE="awg-mihomo-hot-pool.service",
            MIHOMO_HOT_POOL_CLI=str(self.good),MIHOMO_POOL_CLI=str(self.good),
            MIHOMO_READY_GUARD_BIN=str(self.good),MIHOMO_READY_POSTCHECK_BIN=str(self.good),
            MIHOMO_SERVICE_QUICKCHECK_BIN=str(self.good),MIHOMO_NETWORK_GATE_BIN=str(self.good),
            MIHOMO_SERVICE_GATE_MODE="off",
            TEST_SCAN=str(self.scan),TEST_ACTIVE=str(self.active),TEST_ENABLED=str(self.enabled),TEST_FAIL=str(self.error))
    def call(self,*cmd):
        return subprocess.run(["bash",str(self.policy),"auto-strategy",*cmd],
                              env=self.env,text=True,capture_output=True,timeout=5)
    def states(self):
        return tuple(p.read_text().strip() for p in (self.ready,self.active,self.enabled,self.mode))
    def test_classic_then_ready_persistent(self):
        p=self.call("classic");self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(self.states(),("0","0","0","auto"))
        self.assertIn("CLASSIC_AUTO",self.call("status").stdout)
        self.assertEqual(len(self.call("status").stdout.splitlines()),6)
        p=self.call("ready");self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(self.states(),("1","1","1","auto"))
        self.assertIn("HOT_POOL_READY",self.call("status").stdout)
        self.assertEqual(len(self.call("status").stdout.splitlines()),6)
    def test_fixed_chain_not_overwritten(self):
        self.mode.write_text("fixed\n");self.order.write_text("node1\nnode2\n")
        self.assertNotEqual(self.call("classic").returncode,0)
        self.assertEqual(self.order.read_text(),"node1\nnode2\n")
        self.assertEqual(self.states(),("1","1","1","fixed"))
    def test_manual_not_converted_implicitly(self):
        self.mode.write_text("manual\n")
        self.assertNotEqual(self.call("ready").returncode,0)
        self.assertEqual(self.states(),("1","1","1","manual"))
    def test_scanner_active_refuses_switch(self):
        self.scan.write_text("1")
        self.assertNotEqual(self.call("classic").returncode,0)
        self.assertEqual(self.states(),("1","1","1","auto"))
    def test_disable_failure_rolls_back(self):
        self.error.write_text("disable")
        p=self.call("classic")
        self.assertNotEqual(p.returncode,0)
        self.assertIn("FAILED_ROLLED_BACK",p.stderr)
        self.assertEqual(self.states(),("1","1","1","auto"))
    def test_enable_failure_rolls_back(self):
        self.ready.write_text("0\n");self.active.write_text("0");self.enabled.write_text("0")
        self.env["MIHOMO_READY_AUTO_CANARY"]="0"
        self.error.write_text("enable")
        p=self.call("ready")
        self.assertNotEqual(p.returncode,0)
        self.assertIn("FAILED_ROLLED_BACK",p.stderr)
        self.assertEqual(self.states(),("0","0","0","auto"))
    def test_missing_guard_refuses_ready(self):
        self.ready.write_text("0\n");self.active.write_text("0");self.enabled.write_text("0")
        self.env["MIHOMO_READY_AUTO_CANARY"]="0"
        self.env["MIHOMO_READY_GUARD_BIN"]=str(self.root/"missing")
        p=self.call("ready")
        self.assertNotEqual(p.returncode,0)
        self.assertEqual(self.states(),("0","0","0","auto"))
    def test_readonly_status_reports_mixed(self):
        self.ready.write_text("0\n");self.active.write_text("1");self.enabled.write_text("1")
        p=self.call("status");self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("MIXED_CONFIGURATION",p.stdout)
        self.assertEqual(self.states(),("0","1","1","auto"))
if __name__=="__main__":unittest.main()
