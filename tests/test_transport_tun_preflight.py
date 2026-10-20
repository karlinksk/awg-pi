"""Rootless Mihomo Pi-bound TUN HTTPS transport acceptance regression."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
SOURCE=(Path(__file__).resolve().parents[1]/"src/awg-transport").read_text()
class TransportTunQualification(unittest.TestCase):
 def run_gate(self,code="401",fail=False,interface_ok=True):
  with tempfile.TemporaryDirectory(prefix="awg-tun-preflight-") as td:
   p=Path(td); ip=p/"ip"; curl=p/"curl"; sleep=p/"sleep"
   ip.write_text('''#!/bin/sh
printf 'ip:%s\\n' "$*" >> "$LOG"
test "$IFACE_OK" = yes
''')
   curl.write_text('''#!/bin/sh
printf 'curl:%s\\n' "$*" >> "$LOG"
test "$FAIL_CONNECT" = no || exit 35
echo "$HTTP_CODE"
''')
   sleep.write_text("#!/bin/sh\nexit 0\n")
   for cmd in (ip,curl,sleep):cmd.chmod(0o755)
   log=p/"log"
   start=SOURCE.index("mihomo_tun_https_ok(){")
   end=SOURCE.index("\n}\n",start)+2
   script=SOURCE[start:end]+"""
IP_BIN="$IP"
CURL_BIN="$CURL"
SLEEP_BIN="$SLEEP"
MIHOMO_TUN_IF=mihomo0
MIHOMO_TUN_HTTPS_URL=https://api.openai.com/v1/models
mihomo_tun_https_ok
"""
   env=dict(os.environ,IP=str(ip),CURL=str(curl),SLEEP=str(sleep),
       LOG=str(log),HTTP_CODE=code,
       FAIL_CONNECT="yes" if fail else "no",
       IFACE_OK="yes" if interface_ok else "no")
   r=subprocess.run(["bash","-c",script],env=env,text=True,
                    capture_output=True,timeout=5)
   return r,log.read_text() if log.exists() else ""
 def test_success_requires_pi_bound_401(self):
  r,log=self.run_gate()
  self.assertEqual(r.returncode,0,r.stderr)
  self.assertIn("ip:link show mihomo0",log)
  self.assertIn("--noproxy *",log)
  self.assertIn("--interface mihomo0",log)
  self.assertIn("-q -4",log)
  self.assertIn("https://api.openai.com/v1/models",log)
  self.assertEqual(log.count("curl:"),1)
 def test_proxy_only_tls_eof_rejected(self):
  r,log=self.run_gate(fail=True)
  self.assertNotEqual(r.returncode,0)
  self.assertEqual(log.count("curl:"),2)
 def test_http_403_not_reported_as_success(self):
  r,log=self.run_gate(code="403")
  self.assertNotEqual(r.returncode,0)
  self.assertEqual(log.count("curl:"),2)
 def test_interface_down_rejected(self):
  r,log=self.run_gate(interface_ok=False)
  self.assertNotEqual(r.returncode,0)
  self.assertNotIn("curl:",log)
 def test_guard_before_router_mutation_and_after_switch(self):
  start=SOURCE.index("select_transport(){")
  select=SOURCE[start:SOURCE.index("\ncmd=",start)]
  pre=select.index('if [[ "$target" == mihomo ]] && ! mihomo_tun_https_ok; then')
  stop_health=select.index('"$SYSTEMCTL_BIN" stop "$HEALTH_SERVICE"')
  route_reload=select.index('AWG_MAINTENANCE=1 "$AWG_ROUTE_BIN" reload')
  self.assertLess(pre,stop_health)
  self.assertLess(pre,route_reload)
  self.assertIn('atomic_transport_set "$target"',select)
  self.assertIn('if [[ "$target" == mihomo ]]; then mihomo_tun_https_ok; fi',select)
  self.assertIn("trap rollback ERR",select)
  self.assertIn("active transport unchanged.",select)
 def test_normal_runtime_health_checks_tun_once(self):
  func=SOURCE[SOURCE.index("check_mihomo(){"):SOURCE.index("\ncheck_transport(){")]
  self.assertIn("mihomo_tun_https_ok 1",func)
  self.assertIn("for ((attempt=1;attempt<=attempts;attempt++))",func)
 def test_recover_selected_mihomo_also_requires_tun(self):
  f=SOURCE[SOURCE.index("recover_selected_transport(){"):
           SOURCE.index("\nselect_transport(){")]
  self.assertIn('if [[ "$target" == mihomo ]] && ! mihomo_tun_https_ok; then',f)
if __name__=="__main__":unittest.main(verbosity=2)
