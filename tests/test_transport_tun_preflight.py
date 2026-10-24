"""Transport readiness uses local core state and keeps route rollback."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SOURCE=(Path(__file__).resolve().parents[1]/'src/awg-transport').read_text()

class TransportReadiness(unittest.TestCase):
    def probe(self, service=0, interface=0, api=0, selected="Native", xray=0):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);log=p/'calls'
            for name,rc in [('systemctl',service),('ip',interface),('curl',api)]:
                f=p/name
                f.write_text('#!/bin/sh\nprintf "%s\\n" "'+name+':$*" >> "$LOG"\nexit '+str(rc)+'\n')
                if name=='curl':
                    f.write_text(f.read_text().replace('exit '+str(rc),"printf '%s\\n' '{\"now\":\""+selected+"\"}'\nexit "+str(rc)))
                if name=='systemctl':
                    f.write_text(f.read_text().replace('exit '+str(rc),'if [ "$3" = awg-xray-vless.service ]; then exit '+str(xray)+'; fi\nexit '+str(rc)))
                f.chmod(0o755)
            function='check_mihomo(){'+SOURCE.split('check_mihomo(){',1)[1].split('\n}\n',1)[0]+'\n}\n'
            script=function+f'''
SYSTEMCTL_BIN={p/'systemctl'}
IP_BIN={p/'ip'}
CURL_BIN={p/'curl'}
MIHOMO_SERVICE=awg-mihomo.service
MIHOMO_TUN_IF=mihomo0
MIHOMO_API=http://127.0.0.1:9090
MIHOMO_API_TIMEOUT=2
check_mihomo
'''
            r=subprocess.run(['bash','-c',script],capture_output=True,text=True,env={**os.environ,'LOG':str(log)},timeout=5)
            return r,log.read_text()
    def test_local_core_ready_without_openai(self):
        r,log=self.probe();self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('http://127.0.0.1:9090/version',log)
        self.assertNotIn('https://',log)
    def test_inactive_core_rejected(self):
        r,log=self.probe(service=3);self.assertNotEqual(r.returncode,0);self.assertNotIn('curl:',log)
    def test_missing_tun_rejected(self):
        r,log=self.probe(interface=1);self.assertNotEqual(r.returncode,0);self.assertNotIn('curl:',log)
    def test_unreachable_controller_rejected(self):
        self.assertNotEqual(self.probe(api=7)[0].returncode,0)
    def test_api_ignores_environment_proxy(self):
        self.assertIn('--noproxy *',self.probe()[1])
    def test_switch_still_uses_preflight_and_rollback(self):
        f=SOURCE.split('select_transport(){',1)[1]
        self.assertIn('preflight_target_transport "$target"',f)
        self.assertIn('trap rollback ERR',f)
        self.assertIn('AWG_MAINTENANCE=1 "$AWG_ROUTE_BIN" reload',f)
    def test_no_extra_https_gate_on_switch_or_recovery(self):
        self.assertNotIn('mihomo_tun_https_ok',SOURCE)
        self.assertNotIn('api.openai.com',SOURCE)

    def test_selected_xray_requires_its_own_service(self):
        self.assertNotEqual(self.probe(selected="AWG-XRAY-VLESS-LOCAL",xray=3)[0].returncode,0)
    def test_native_does_not_depend_on_dormant_xray(self):
        self.assertEqual(self.probe(selected="Native",xray=3)[0].returncode,0)
    def test_missing_selected_target_is_unready(self):
        self.assertNotEqual(self.probe(selected="")[0].returncode,0)
