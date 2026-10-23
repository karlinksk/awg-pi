#!/usr/bin/env python3
"""Rootless Selective fail-open pre-activation under a stopped incumbent.

Only disposable mock command paths are invoked; NO device routes or services
are altered by these tests.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"src/awg-mihomo-node-policy").read_text()
FUN=("auto_xray_candidate(){" +
     SOURCE.split("auto_xray_candidate(){",1)[1].split("\n}\n",1)[0] + "\n}\n")

class SelectivePreActivation(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp=Path(td.name)
        self.bin=self.tmp/"bin"
        self.bin.mkdir()
        self.mode=self.tmp/"mode"
        self.mode.write_text("selective\n")
        self.enabled=self.tmp/"vpn-enabled"
        self.enabled.write_text("1\n")
        self.rules=self.tmp/"ip-rules"
        self.rules.write_text("100: from all fwmark 0x100 lookup 100\n")
        self.log=self.tmp/"commands"
        self.log.write_text("")
        self.mock("hostname","echo awg-upgrade")
        self.mock("systemctl",'''case "$1" in
  is-active)
    if [ "$3" = awg-mihomo.service ] && [ "$MOCK_MIHOMO_ACTIVE" = 0 ];then exit 1;fi
    exit 0;;
esac
exit 2''')
        self.mock("transport",'''case "$1" in
  get) echo mihomo;;
  check) if [ "$2" = awg ]; then
           if [ "$MOCK_AWG_HEALTH" = 1 ];then echo healthy;else echo down;fi
         else exit 2; fi;;
  *) exit 2;;
esac''')
        self.mock("ip",'''if [ "$1" = -4 ] && [ "$2" = rule ] && [ "$3" = show ];then
  cat "$MOCK_RULES"
else exit 2;fi''')
        self.mock("failopen",'''printf "FAILOPEN\n" >>"$MOCK_COMMANDS"
if [ "$MOCK_FAILOPEN_RC" != 0 ];then exit "$MOCK_FAILOPEN_RC";fi
: >"$MOCK_RULES"''')
        self.mock("executor",'''printf "EXECUTOR:%s:%s\n" "$2" "$3" >>"$MOCK_COMMANDS"
[ "$MOCK_EXECUTOR_RC" = 0 ]''')
        self.mock("isolated-xray-probe",'[[ "$1" == probe-xray && "$2" == 3 ]] || exit 3\nexit "${MOCK_PROBE_RC:-0}"')
        self.mock("logger",'''printf "LOGGER\n" >>"$MOCK_COMMANDS"''')

    def mock(self,name,body):
        p=self.bin/name
        p.write_text("#!/usr/bin/env bash\n"+body+"\n")
        p.chmod(0o755)
        return p

    def try_switch(self,*,active="0",awg="1",failopen="0",optin="1",
                   selective="1",vpn="1",rules=True,rc="0"):
        self.enabled.write_text(vpn+"\n")
        self.rules.write_text(
            "100: from all fwmark 0x100 lookup 100\n" if rules else "")
        self.log.write_text("")
        env={**os.environ,
            "PATH":str(self.bin)+":"+os.environ["PATH"],
            "MIHOMO_XRAY_AUTO_FAILOVER_CANARY":optin,
            "MIHOMO_XRAY_SELECTIVE_CANARY":selective,
            "MIHOMO_READY_AUTO_CANARY":"0",
            "MIHOMO_STANDBY_REPAIR":"0",
            "MIHOMO_AUTO_MODE_FILE":str(self.mode),
            "MIHOMO_AUTO_VPN_ENABLED_FILE":str(self.enabled),
            "MIHOMO_AUTO_SYSTEMCTL":str(self.bin/"systemctl"),
            "MIHOMO_AUTO_SERVICE":"awg-mihomo.service",
            "MIHOMO_AUTO_TRANSPORT_CLI":str(self.bin/"transport"),
            "MIHOMO_AUTO_FAILOPEN":str(self.bin/"failopen"),
            "MIHOMO_XRAY_NATIVE_RECOVERY_CLI":str(self.bin/"isolated-xray-probe"),
            "MIHOMO_XRAY_TRANSACTION_CLI":str(self.bin/"executor"),
            "MOCK_MIHOMO_ACTIVE":active,
            "MOCK_AWG_HEALTH":awg,
            "MOCK_FAILOPEN_RC":failopen,
            "MOCK_EXECUTOR_RC":rc,
            "MOCK_COMMANDS":str(self.log),
            "MOCK_RULES":str(self.rules)}
        script=FUN+'''auto_xray_candidate FAILED-NATIVE VLESS-CANDIDATE \
 "NODE_ENGINE=XRAY
NODE_INDEX=3
NODE_BASIC_NETWORK=NETWORK_OK"'''
        p=subprocess.run(["bash","-c",script],env=env,capture_output=True,
                         text=True,timeout=5)
        return p,self.log.read_text(),self.rules.read_text()

    def test_dead_mihomo_rule_removed_before_executor(self):
        p,log,rules=self.try_switch()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(rules,"")
        self.assertLess(log.index("FAILOPEN"),log.index("EXECUTOR:"))
        self.assertIn("LOGGER",log)

    def test_already_failopen_does_not_repeat_mutation(self):
        p,log,_=self.try_switch(rules=False)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn("FAILOPEN",log)
        self.assertIn("EXECUTOR:",log)

    def test_live_healthy_mihomo_does_not_failopen(self):
        p,log,rules=self.try_switch(active="1")
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn("FAILOPEN",log)
        self.assertTrue(rules.strip())

    def test_no_awg_refuses_before_route_mutation(self):
        p,log,rules=self.try_switch(awg="0")
        self.assertEqual(p.returncode,1)
        self.assertEqual(log,"")
        self.assertTrue(rules.strip())

    def test_vpn_policy_off_refuses(self):
        p,log,_=self.try_switch(vpn="0")
        self.assertEqual(p.returncode,1)
        self.assertEqual(log,"")

    def test_failed_failopen_blocks_executor(self):
        p,log,_=self.try_switch(failopen="1")
        self.assertEqual(p.returncode,1)
        self.assertNotIn("EXECUTOR:",log)
        self.assertIn("XRAY_SELECTIVE_FAILOPEN_FAILED",p.stderr)

    def test_transaction_abort_still_returns_fallback(self):
        p,log,rules=self.try_switch(rc="1")
        self.assertEqual(p.returncode,1)
        self.assertEqual(rules,"")
        self.assertIn("XRAY_AUTO_TRANSACTION_ABORTED_AWG_FALLBACK",p.stderr)

    def test_selective_flag_absent_never_touches_network(self):
        p,log,rules=self.try_switch(selective="0")
        self.assertEqual(p.returncode,2)
        self.assertEqual(log,"")
        self.assertTrue(rules.strip())

    def test_auto_flag_absent_never_touches_network(self):
        p,log,rules=self.try_switch(optin="0")
        self.assertEqual(p.returncode,2)
        self.assertEqual(log,"")
        self.assertTrue(rules.strip())

if __name__=="__main__":
    unittest.main()
