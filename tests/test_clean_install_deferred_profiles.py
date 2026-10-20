#!/usr/bin/env python3
"""Isolated clean-install completion tests: no VPN profile before install exits."""
from pathlib import Path
import os,subprocess,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
INS=(ROOT/"install.sh").read_text()
A=INS.index('if (( UPGRADE_EXISTING == 0 )); then\n  STAGE="завершение установки без VPN-профилей"')
B=INS.index("\n\n# Fresh installs PREPARE conservative transport AUTO only.",A)
POST=INS[A:B]
C=INS.index('if (( UPGRADE_EXISTING == 0 )); then\n  STAGE="завершение безопасной установки"')
D=INS.index("elif (( ACTIVATE_TRANSIT_AFTER_INSTALL == 1 )); then",C)
POST_MODE=INS[C:D]+"fi\n"

class BlankInstallTests(unittest.TestCase):
 def scenario(self,transport="unconfigured",mode="selective",conf=False,env=False,sub=False,upgrade=False):
  with tempfile.TemporaryDirectory(prefix="awg-empty-installer-") as d:
   base=Path(d);cfg=base/"private";(cfg/"transports"/"mihomo").mkdir(parents=True)
   config=base/"awg0.conf"
   (base/"transport").write_text(transport+"\n")
   (base/"mode").write_text(mode+"\n")
   if conf:config.write_text("synthetic-config")
   if env:(cfg/"transports"/"mihomo"/"provider.env").write_text("synthetic-source")
   if sub:(base/"subscription.yaml").write_text("synthetic-provider")
   # Substitute only the absolute test fixture subscription path, never
   # execute against the actual test Pi's root-protected provider files.
   fixture=(POST+"\n"+POST_MODE).replace(
    "/var/lib/awg-pbr/mihomo/providers/subscription.yaml",str(base/"subscription.yaml"))
   shell='''set -Eeuo pipefail
UPGRADE_EXISTING="$TEST_UPGRADE"
PBR_DIR="$TEST_PBR"
CONF_FILE="$TEST_CONF"
TRANSPORT_FILE="$TEST_TRANSPORT"
MODE_FILE="$TEST_MODE"
STAGE="init"
log(){ :; }
ok(){ :; }
die(){ echo "SAFE_ABORT"; exit 77; }
''' +fixture+'\necho EMPTY_INSTALL_STATE_OK\n'
   p=subprocess.run(["bash","-c",shell],capture_output=True,text=True,timeout=4,
    env={**os.environ,
     "TEST_UPGRADE":"1" if upgrade else "0","TEST_PBR":str(cfg),
     "TEST_CONF":str(config),"TEST_TRANSPORT":str(base/"transport"),
     "TEST_MODE":str(base/"mode")})
   return p.returncode,p.stdout.strip(),(base/"transport").read_text().strip(),(base/"mode").read_text().strip()
 def test_clean_empty_finishes_unconfigured_selective(self):
  rc,out,trans,mode=self.scenario()
  self.assertEqual(rc,0,out)
  self.assertEqual((trans,mode),("unconfigured","selective"))
  self.assertIn("EMPTY_INSTALL_STATE_OK",out)
 def test_previous_awg_profile_aborts(self):
  rc,out,_,_=self.scenario(conf=True)
  self.assertEqual(rc,77);self.assertIn("SAFE_ABORT",out)
 def test_previous_provider_credentials_abort(self):
  for kw in (dict(env=True),dict(sub=True)):
   with self.subTest(kw=kw):
    rc,out,_,_=self.scenario(**kw)
    self.assertEqual(rc,77);self.assertIn("SAFE_ABORT",out)
 def test_premature_transport_selection_aborts(self):
  for t in ("awg","mihomo"):
   with self.subTest(t=t):
    self.assertEqual(self.scenario(transport=t)[0],77)
 def test_premature_transit_aborts(self):
  self.assertEqual(self.scenario(mode="transit")[0],77)
 def test_installer_no_credential_collection(self):
  self.assertNotIn('"$FIRST_RUN_CLI" wizard',INS)
  self.assertNotIn('ask "Режим работы"',INS)
  self.assertIn('install_project_helper src/awg-first-run "$FIRST_RUN_CLI"',INS)
  self.assertIn('install_project_helper src/awg-menu /usr/local/sbin/awg-menu',INS)
  self.assertIn('install_project_helper src/awg-mihomo-node-policy "$MIHOMO_NODE_POLICY_CLI"',INS)
  for dep in ("ffmpeg","/usr/bin/ffprobe","awg-mihomo-stage18-ram-runtime",
              "awg-mihomo-ready-live-match","awg-hot-pool-continuity.py"):
   self.assertIn(dep,INS)
 def test_no_no_profile_awg_auto_start(self):
  self.assertIn('if [[ -f "$CONF_FILE" ]]; then',INS)
  self.assertIn('ACTIVE_TRANSPORT="$(cat "$TRANSPORT_FILE"',INS)
  self.assertIn('[[ "$(cat "$TRANSPORT_FILE")" == unconfigured ]]',INS)
if __name__=="__main__":unittest.main()
