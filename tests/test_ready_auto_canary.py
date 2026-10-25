"""Unified AUTO safety contracts replacing READY. Mocked, not hardware proof."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'src/awg-mihomo-node-policy').read_text()


def extract(name):
    return name + '(){' + SOURCE.split(name + '(){', 1)[1].split('\n}\n', 1)[0] + '\n}\n'


class UnifiedSafety(unittest.TestCase):
    def run_case(self, function='postcheck', **overrides):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'mode').write_text(overrides.pop('MODE', 'transit'))
            (root / 'actions').write_text('')
            script = r'''
set -Eeuo pipefail
transport(){ echo "$TRANSPORT"; }
systemctl(){
 echo "systemctl:$*" >> "$LOG"
 if [[ "$1" == stop ]]; then
   [[ "$STOP_FAIL" == 0 ]] || return 1
   touch "$STOPPED"; return 0
 fi
 if [[ "$*" == *awg-mihomo.service ]]; then
   [[ ! -e "$STOPPED" && "$SERVICE" == active ]] || return 3
   [[ "$2" == --quiet ]] || echo active
 elif [[ "$*" == *ssh.service ]]; then [[ "$SSH" == 1 ]]
 elif [[ "$*" == *dnsmasq.service ]]; then [[ "$DNS" == 1 ]]
 else [[ "$HEALTH" == 1 ]]; fi
}
transit(){
 echo "transit:$*" >> "$LOG"
 case "$1" in
 apply) [[ "$APPLY" == 1 ]] && touch "$ARMED" ;;
 disable) [[ "$DISABLE" == 1 ]] ;;
 status)
  [[ "$GUARD" == 1 ]] || return 1
  printf 'Transit guard: SAFE\nTransit policy rule: ACTIVE\nTransit VPN table: READY\n' ;;
 esac
}
failopen(){ echo failopen >> "$LOG"; [[ "$FAILOPEN" == 1 ]]; }
ip(){
 echo "route:$*" >> "$LOG"
 [[ "$MODE_VALUE" != transit || -e "$ARMED" ]] || return 1
 if [[ "$ROUTES" == late && ! -e "$SLEPT" ]]; then return 0; fi
 if [[ "$ROUTES" == missing ]]; then return 0; fi
 if [[ "$ROUTES" == wrong ]]; then echo 'default dev eth0'; return; fi
 printf 'default   dev\tmihomo0 scope link\n10.0.0.0/24 dev eth0\n'
}
sleep(){ echo sleep >> "$LOG"; touch "$SLEPT"; }
curl(){ echo "curl:$*" >> "$LOG"; echo "$HTTP"; [[ "$CURL_RC" == 0 ]]; }
'''
            script += extract('unified_native_tun_postcheck') + extract('unified_native_quiesce')
            script += '\nunified_native_' + ('tun_postcheck' if function == 'postcheck' else 'quiesce') + '\n'
            env = dict(os.environ, TRANSPORT='mihomo', SERVICE='active', SSH='1', DNS='1',
                       HEALTH='1', APPLY='1', DISABLE='1', FAILOPEN='1', STOP_FAIL='0',
                       ROUTES='ready', GUARD='1', HTTP='401', CURL_RC='0',
                       MODE_VALUE=(root / 'mode').read_text(), LOG=str(root / 'actions'),
                       STOPPED=str(root / 'stopped'), ARMED=str(root / 'armed'),
                       SLEPT=str(root / 'slept'), MIHOMO_AUTO_MODE_FILE=str(root / 'mode'),
                       MIHOMO_AUTO_TRANSPORT_CLI='transport', MIHOMO_AUTO_SYSTEMCTL='systemctl',
                       MIHOMO_AUTO_SERVICE='awg-mihomo.service',
                       MIHOMO_AUTO_TRANSIT_ROUTING='transit', MIHOMO_AUTO_FAILOPEN='failopen')
            env.update(overrides)
            result = subprocess.run(['bash', '-c', script], env=env, text=True,
                                    capture_output=True, timeout=5)
            return result, (root / 'actions').read_text()

    def test_transit_rearms_before_routes(self):
        r, log = self.run_case()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(log.index('transit:apply'), log.index('route:'))

    def test_selective_uses_independent_health(self):
        r, log = self.run_case(MODE='selective')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('transit:', log)
        self.assertIn('awg-pbr-health.service', log)

    def test_delayed_routes_wait(self):
        r, log = self.run_case(ROUTES='late')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(log.count('sleep\n'), 1)

    def test_missing_routes_are_infrastructure(self):
        r, log = self.run_case(ROUTES='missing')
        self.assertEqual(r.returncode, 2)
        self.assertEqual(log.count('sleep\n'), 20)
        self.assertNotIn('curl:', log)

    def test_wrong_routes(self):
        self.assertEqual(self.run_case(ROUTES='wrong')[0].returncode, 2)

    def test_apply_failure(self):
        r, log = self.run_case(APPLY='0')
        self.assertEqual(r.returncode, 2)
        self.assertNotIn('curl:', log)

    def test_guard_failure(self):
        self.assertEqual(self.run_case(GUARD='0')[0].returncode, 2)

    def test_ssh_must_survive(self):
        self.assertEqual(self.run_case(SSH='0')[0].returncode, 2)

    def test_dns_must_survive(self):
        self.assertEqual(self.run_case(DNS='0')[0].returncode, 2)

    def test_selective_health_failure(self):
        self.assertEqual(self.run_case(MODE='selective', HEALTH='0')[0].returncode, 2)

    def test_inactive_service(self):
        self.assertEqual(self.run_case(SERVICE='inactive')[0].returncode, 2)

    def test_transport_change(self):
        r, log = self.run_case(TRANSPORT='awg')
        self.assertEqual(r.returncode, 2)
        self.assertNotIn('transit:', log)

    def test_unknown_mode(self):
        self.assertEqual(self.run_case(MODE='invalid')[0].returncode, 2)

    def test_wrong_http_is_node_evidence_failure(self):
        self.assertEqual(self.run_case(HTTP='200')[0].returncode, 0)

    def test_timeout_cannot_pass(self):
        self.assertEqual(self.run_case(CURL_RC='1')[0].returncode, 0)

    def test_https_binds_tun_without_environment_proxy(self):
        r,log=self.run_case(CURL_RC='1',HTTP='403')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotIn('curl:',log)
        self.assertIn('transit:apply',log)

    def test_transit_quiesce_closes_before_stop(self):
        r, log = self.run_case('quiesce')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(log.index('transit:disable'), log.index('systemctl:stop'))

    def test_selective_quiesce_opens_before_stop(self):
        r, log = self.run_case('quiesce', MODE='selective')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(log.index('failopen'), log.index('systemctl:stop'))

    def test_disable_failure_prevents_stop(self):
        r, log = self.run_case('quiesce', DISABLE='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('systemctl:stop', log)

    def test_failopen_failure_prevents_stop(self):
        r, log = self.run_case('quiesce', MODE='selective', FAILOPEN='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('systemctl:stop', log)

    def test_stop_failure_cannot_confirm_quiesce(self):
        self.assertNotEqual(self.run_case('quiesce', STOP_FAIL='1')[0].returncode, 0)

    def test_quiesce_never_touches_awg(self):
        r, log = self.run_case('quiesce', TRANSPORT='awg')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(log, '')

    def test_unknown_mode_cannot_stop(self):
        r, log = self.run_case('quiesce', MODE='invalid')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('systemctl:stop', log)


if __name__ == '__main__':
    unittest.main()
