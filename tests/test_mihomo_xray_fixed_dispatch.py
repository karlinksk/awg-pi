#!/usr/bin/env python3
"""Rootless FIXED engine-dispatch tests, with no network/systemd side effects."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"src/awg-mihomo-node-policy").read_text()
FUNCTION="failover_fixed(){"+SOURCE.split("failover_fixed(){",1)[1].split("\n}\n",1)[0]+"\n}\n"

class XrayFixedDispatch(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.base=Path(t.name)
        self.bin=self.base/"bin";self.bin.mkdir()
        (self.base/"mode").write_text("transit\n")
        (self.base/"chain").write_text("HY2-A\nVLESS-B\nHY2-C\n")
        self.log=self.base/"calls"
        self.log.write_text("")
        self.mkbin("hostname",'echo awg-upgrade')
        self.mkbin("resolver",'''[ "$1" = resolve ] || exit 2
case "$2" in
  VLESS-B) printf 'NODE_ENGINE=XRAY\\nNODE_BASIC_NETWORK=%s\\n' "$MOCK_XRAY_HEALTH" ;;
  *) printf 'NODE_ENGINE=MIHOMO\\n' ;;
esac''')
        self.mkbin("transaction",'''printf 'transaction:%s:%s:%s\\n' "$AWG_XRAY_EXPERIMENTAL_APPLY" "$2" "$3" >> "$MOCK_LOG"
[ "$MOCK_XRAY_RC" = 0 ]''')
        self.mkbin("configure",'''printf 'mihomo:%s\\n' "$*" >> "$MOCK_LOG"
[ "$MOCK_MIHOMO_RC" = 0 ]''')

    def mkbin(self,name,body):
        path=self.bin/name
        path.write_text("#!/usr/bin/env bash\n"+body+"\n");path.chmod(0o755)

    def execute(self,canary="0",health="NETWORK_OK",mihomo_rc="0",xray_rc="0",hostname=None,current="HY2-A"):
        if hostname is not None:self.mkbin("hostname","echo "+hostname)
        env={**os.environ,
          "PATH":str(self.bin)+":"+os.environ["PATH"],
          "MIHOMO_NODE_POLICY_ORDER_FILE":str(self.base/"chain"),
          "MIHOMO_AUTO_MODE_FILE":str(self.base/"mode"),
          "MIHOMO_SERVICE_GATE_MODE":"off",
          "MIHOMO_UNIFIED_NODE_CLI":str(self.bin/"resolver"),
          "MIHOMO_XRAY_TRANSACTION_CLI":str(self.bin/"transaction"),
          "MIHOMO_CONFIGURE":str(self.bin/"configure"),
          "MIHOMO_XRAY_FIXED_FAILOVER_CANARY":canary,
          "MOCK_LOG":str(self.log),
          "MOCK_XRAY_HEALTH":health,
          "MOCK_MIHOMO_RC":mihomo_rc,
          "MOCK_XRAY_RC":xray_rc
        }
        script=FUNCTION+'''
service_candidate_allowed(){ return 0; }
failover_fixed "$1"
'''
        return subprocess.run(["bash","-c",script,"test",current],env=env,
                              capture_output=True,text=True,timeout=8)

    def test_off_by_default_never_activates_xray(self):
        r=self.execute()
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("XRAY_TRANSACTION_NOT_CERTIFIED",r.stderr)
        self.assertEqual(self.log.read_text().strip(),"mihomo:node select-auto HY2-C")

    def test_explicit_optin_pins_transit_and_uses_only_xray_transaction(self):
        r=self.execute(canary="1")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("MIHOMO_NODE_FAILOVER=HY2-A->VLESS-B",r.stdout)
        self.assertEqual(self.log.read_text().strip(),
                         "transaction:TEST_PI_AUTHORIZED:HY2-A:VLESS-B")

    def test_network_untested_cannot_trigger_live_xray(self):
        r=self.execute(canary="1",health="UNTESTED")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("XRAY_EXPERIMENTAL_PREFLIGHT_REJECTED",r.stderr)
        self.assertEqual(self.log.read_text().strip(),"mihomo:node select-auto HY2-C")

    def test_wrong_host_refuses_live_xray(self):
        r=self.execute(canary="1",hostname="other")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotIn("transaction:",self.log.read_text())

    def test_selective_never_calls_transit_xray(self):
        (self.base/"mode").write_text("selective\n")
        r=self.execute(canary="1")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotIn("transaction:",self.log.read_text())

    def test_failed_transaction_must_not_reactivate_known_dead_node(self):
        r=self.execute(canary="1",xray_rc="1")
        self.assertNotEqual(r.returncode,0)
        self.assertIn("XRAY_TRANSACTION_ABORTED_REVIEW_REQUIRED",r.stderr)
        self.assertEqual(self.log.read_text().strip(),
                         "transaction:TEST_PI_AUTHORIZED:HY2-A:VLESS-B")

    def test_earlier_mihomo_candidate_wins_before_xray(self):
        (self.base/"chain").write_text("HY2-A\nHY2-C\nVLESS-B\n")
        r=self.execute(canary="1")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.log.read_text().strip(),"mihomo:node select-auto HY2-C")

    def test_no_wrap_from_last_node(self):
        r=self.execute(canary="1",current="HY2-C")
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(self.log.read_text(),"")

    def test_xray_not_sent_to_mihomo_selector(self):
        r=self.execute(canary="1")
        self.assertNotIn("mihomo:",self.log.read_text())
        self.assertIn("transaction:",self.log.read_text())

    def test_passive_stage_is_hash_pinned_and_never_changes_service(self):
        stage=(ROOT/"scripts/awg-xray-testpi-fixed-dispatch-stage.py").read_text()
        self.assertIn("OLD_SHA=\"47f007a489",stage)
        self.assertIn('result("OPTIN_DEFAULT","OFF")',stage)
        self.assertIn('result("AUTO_XRAY_ENABLED","NO")',stage)
        self.assertIn('require(state()==before,"LIVE_STATE_CHANGED")',stage)
        self.assertIn('result("SERVICES_RESTARTED","NO")',stage)
        self.assertIn('result("ROUTES_CHANGED","NO")',stage)
        self.assertIn('atomic_install(LIVE,old)',stage)
        self.assertIn('systemctl","show","--property=Environment"',stage)
        for banned in ('"systemctl","restart"', '"systemctl","stop"',
                       'awg-transit-routing","disable"', '"systemctl","enable"'):
            self.assertNotIn(banned,stage)

    def test_no_optin_enabled_in_installer_or_menu(self):
        for path in (ROOT/"install.sh",ROOT/"src/awg-menu"):
            self.assertNotIn("MIHOMO_XRAY_FIXED_FAILOVER_CANARY=1",path.read_text())
        self.assertIn('MIHOMO_NODE_FAILOVER=XRAY_TRANSACTION_NOT_CERTIFIED',SOURCE)
        self.assertIn('XRAY_TRANSACTION_ABORTED_REVIEW_REQUIRED',SOURCE)

if __name__=="__main__":unittest.main()
