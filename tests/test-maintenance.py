import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('manage', 'src/awg-manage.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
KEY = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='
PROFILE = f'''[Interface]
PrivateKey = {KEY}
Address = 10.8.0.2/32
Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4
DNS = 8.8.8.8
Table = auto
[Peer]
PublicKey = {KEY}
Endpoint = 192.0.2.1:51820
AllowedIPs = 0.0.0.0/0
'''
V3_PROFILE = PROFILE.replace('S1 = 0', 'S1 = 12').replace('S2 = 0', 'S2 = 12')
for legacy in ('H1 = 1\n', 'H2 = 2\n', 'H3 = 3\n', 'H4 = 4\n'):
    V3_PROFILE = V3_PROFILE.replace(legacy, '')
V3_PROFILE = V3_PROFILE.replace('[Peer]', f'''S3 = 12
S4 = 12
I1 = <r 2><b 0x01020304>
HeaderProtectionKey = {KEY}
ContentPaddingAddition = 0-10
RekeyAfterTime = 100-120
RekeyTimeout = 3-7
RejectAfterTime = 150-180
KeepaliveTimeout = 5-15
MaxHandshakeAttempts = 15-20
RandomTrailers = on
DisableCookies = on
[Peer]''').replace('AllowedIPs = 0.0.0.0/0', 'AllowedIPs = 0.0.0.0/0, ::/0')
V3_PROFILE += 'PersistentKeepalive = 25-35\n'

WG_PROFILE = f'''[Interface]
PrivateKey = {KEY}
Address = 10.9.0.2/32
[Peer]
PublicKey = {KEY}
Endpoint = 192.0.2.55:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
'''


class Maintenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for key in ('ENV', 'DNS', 'NFT', 'CLIENTS', 'DOMAINS', 'BACKUPS', 'CONF_DIR', 'MODE'):
            p = patch.object(m, key, str(self.root / key))
            p.start()
            self.addCleanup(p.stop)
        Path(m.CONF_DIR).mkdir()
        Path(m.MODE).write_text('selective\n')
        self.env = dict(LAN_IF='eth0', PI_IP='192.168.1.2', LAN_CIDR='192.168.1.0/24',
                        ROUTER_IP='192.168.1.1', VPN_IF='awg0', HEALTH_MARK='0x101',
                        HEALTH_TABLE='101', UPSTREAM_DNS='9.9.9.9', VPN_MARK='0x100')
        Path(m.ENV).write_text(''.join(f"{k}='{v}'\n" for k, v in self.env.items()))
        Path(m.DNS).write_text('interface=eth0\nlisten-address=192.168.1.2\nlisten-address=127.0.0.1\nserver=9.9.9.9\n')
        Path(m.NFT).write_text('old nft\n')
        Path(m.CLIENTS).write_text('192.168.1.28\n')
        Path(m.DOMAINS).write_text('old domains\n')
        Path(m.MODE).write_text('selective\n')
        self.active = Path(m.CONF_DIR) / 'awg0.conf'
        self.active.write_text(PROFILE)
        self.previous = self.active.with_suffix('.conf.previous')
        self.new = self.root / 'new.conf'
        self.new.write_text(PROFILE.replace('192.0.2.1:', '192.0.2.2:'))
        self.calls = []
        self.fail_once = None
        p = patch.object(m, 'run', side_effect=self.mock_run)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(m, 'preflight')
        self.preflight = p.start()
        self.addCleanup(p.stop)
        p = patch.object(m, 'tunnel_ok', return_value=True)
        self.health = p.start()
        self.addCleanup(p.stop)
        self.new_net = dict(LAN_IF='eth1', PI_IP='192.168.2.33', LAN_CIDR='192.168.2.0/24', ROUTER_IP='192.168.2.1')
        p = patch.object(m, 'discover', return_value=self.new_net)
        self.discover = p.start()
        self.addCleanup(p.stop)

    def mock_run(self, *args, **kwargs):
        self.calls.append(args)
        if self.fail_once == args:
            self.fail_once = None
            raise RuntimeError('injected failure')
        if args[0] == m.SETUP:
            Path(m.NFT).write_text('new nft')
        return subprocess.CompletedProcess(args, 0, '1.1.1.1\n' if args[0] == 'dig' else '', '')

    def args(self, **kw):
        return argparse.Namespace(**dict(dict(yes=True, keep_clients=True, action='replace', file=str(self.new)), **kw))

    def test_profile_sanitization(self):
        clean, endpoint = m.profile(PROFILE)
        self.assertNotIn('DNS =', clean)
        self.assertIn('Table = off', clean)
        self.assertEqual(endpoint, '192.0.2.1:51820')
        self.assertIn('PrivateKey = ' + KEY, clean)

    def test_profile_rejects_unsafe_and_invalid(self):
        for bad in (PROFILE.replace('DNS =', 'PostUp ='), PROFILE.replace(KEY, 'bad'),
                    PROFILE.replace('Address = 10.8.0.2/32\n', ''), PROFILE + '[Peer]\n',
                    PROFILE.replace('0.0.0.0/0', '10.0.0.0/8'),
                    PROFILE.replace('Address = 10.8.0.2/32', 'Address = garbage')):
            with self.subTest(bad=bad[:20]), self.assertRaises(ValueError):
                m.profile(bad)

    def test_plain_wireguard_profile_is_supported_by_shared_backend(self):
        clean, endpoint = m.profile(WG_PROFILE)
        self.assertIn('Table = off', clean)
        self.assertNotIn('Jc =', clean)
        self.assertEqual(endpoint, '192.0.2.55:51820')

    def test_v31_profile_preserves_native_fields_and_dual_stack(self):
        clean, _ = m.profile(V3_PROFILE)
        self.assertNotIn('H1 =', clean)
        for line in V3_PROFILE.splitlines():
            if line and not line.startswith(('DNS =', 'Table =')):
                self.assertIn(line, clean)
        self.assertIn('Table = off', clean)
        self.assertNotIn('DNS =', clean)

    def test_invalid_header_key_and_unknown_fields_fail_before_preflight(self):
        for bad in (V3_PROFILE.replace('HeaderProtectionKey = ' + KEY, 'HeaderProtectionKey = invalid'),
                    V3_PROFILE.replace('RandomTrailers', 'UnknownSetting'),
                    V3_PROFILE + 'AdvancedSecurity = on\n'):
            self.new.write_text(bad)
            with self.assertRaises(ValueError):
                m.replace_config(self.args(), self.env)
            self.assertEqual(self.calls, [])
            self.preflight.assert_not_called()

    def test_v31_replace_then_rollback_accepts_existing_v31_profile(self):
        self.active.write_text(V3_PROFILE)
        m.replace_config(self.args(), self.env)
        self.assertEqual(self.previous.read_text(), V3_PROFILE)
        m.replace_config(self.args(action='rollback', file=None), self.env)
        clean, _ = m.profile(V3_PROFILE)
        self.assertEqual(self.active.read_text(), clean)

    def test_dns_change_updates_env_and_dnsmasq_transactionally(self):
        args = self.args(action='set', servers='1.1.1.1, 9.9.9.9')
        m.dns_reconfigure(args, self.env)
        self.assertEqual(m.read_env()['UPSTREAM_DNS'], '1.1.1.1,9.9.9.9')
        dns = Path(m.DNS).read_text()
        self.assertIn('server=1.1.1.1\n', dns)
        self.assertIn('server=9.9.9.9\n', dns)
        self.assertEqual(dns.count('server='), 2)
        self.assertIn(('dnsmasq', '--test'), self.calls)
        self.assertIn(('systemctl', 'restart', 'dnsmasq.service'), self.calls)
        self.assertIn(('dig', '+time=3', '+tries=1', '+short', 'A',
                       'example.com', '@192.168.1.2'), self.calls)

    def test_dns_invalid_or_cancelled_has_no_side_effects(self):
        before = {m.ENV: Path(m.ENV).read_bytes(), m.DNS: Path(m.DNS).read_bytes()}
        with self.assertRaises(ValueError):
            m.dns_reconfigure(self.args(action='set', servers='bad,1.1.1.1'), self.env)
        self.assertEqual(self.calls, [])
        with patch.object(m, 'confirm', side_effect=m.UserCancelled('cancelled')):
            with self.assertRaises(m.UserCancelled):
                m.dns_reconfigure(self.args(action='set', servers='1.1.1.1'), self.env)
        for path, value in before.items():
            self.assertEqual(Path(path).read_bytes(), value)
        self.assertFalse(Path(m.BACKUPS).exists())

    def test_dns_apply_failure_restores_files_and_dnsmasq(self):
        before = {m.ENV: Path(m.ENV).read_bytes(), m.DNS: Path(m.DNS).read_bytes()}
        self.fail_once = ('dnsmasq', '--test')
        with self.assertRaises(RuntimeError):
            m.dns_reconfigure(self.args(action='set', servers='1.1.1.1'), self.env)
        for path, value in before.items():
            self.assertEqual(Path(path).read_bytes(), value)
        restarts = [call for call in self.calls if call == ('systemctl', 'restart', 'dnsmasq.service')]
        self.assertEqual(len(restarts), 1)

    def test_dns_status_reports_env_and_dnsmasq(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            m.dns_status(self.env)
        text = out.getvalue()
        self.assertIn('Upstream DNS: 9.9.9.9', text)
        self.assertIn('dnsmasq servers: 9.9.9.9', text)

    def test_dns_parser_deduplicates_and_rejects_self_or_too_many(self):
        self.assertEqual(m.parse_dns_servers('1.1.1.1,1.1.1.1,9.9.9.9', self.env),
                         ['1.1.1.1', '9.9.9.9'])
        for value in ('127.0.0.1', '192.168.1.2', '224.0.0.1',
                      '1.1.1.1,2.2.2.2,3.3.3.3,4.4.4.4,5.5.5.5'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.parse_dns_servers(value, self.env)

    def test_network_success_preserves_settings_and_clients(self):
        m.reconfigure(self.args(), self.env)
        self.assertEqual(m.read_env()['PI_IP'], '192.168.2.33')
        self.assertEqual(m.read_env()['UPSTREAM_DNS'], '9.9.9.9')
        self.assertIn('listen-address=192.168.2.33', Path(m.DNS).read_text())
        self.assertIn('server=9.9.9.9', Path(m.DNS).read_text())
        self.assertEqual(Path(m.CLIENTS).read_text(), '192.168.1.28\n')
        self.assertEqual(self.active.read_text(), PROFILE)
        self.assertIn((m.SETUP,), self.calls)
        self.assertIn((m.ROUTE, 'reload'), self.calls)

    def test_network_old_clients_need_explicit_acknowledgement(self):
        with self.assertRaises(ValueError):
            m.reconfigure(self.args(keep_clients=False), self.env)
        self.assertEqual(self.calls, [])
        self.assertFalse(Path(m.BACKUPS).exists())

    def test_network_failures_restore_all_files(self):
        files = [m.ENV, m.DNS, m.NFT, m.DOMAINS, m.CLIENTS]
        before = {f: Path(f).read_bytes() for f in files}
        for failed in [('dnsmasq', '--test'), (m.SETUP,), ('systemctl', 'restart', 'dnsmasq.service'),
                       ('ping', '-4', '-n', '-c1', '-W3', '192.168.2.1'), (m.ROUTE, 'reload')]:
            with self.subTest(failed=failed):
                self.fail_once = failed
                with self.assertRaises(RuntimeError):
                    m.reconfigure(self.args(), self.env)
                for f in files:
                    self.assertEqual(Path(f).read_bytes(), before[f])

    def test_confirmation_cancellation_has_no_side_effects(self):
        with patch.object(m, 'confirm', side_effect=ValueError('cancelled')):
            with self.assertRaises(ValueError):
                m.reconfigure(self.args(), self.env)
            with self.assertRaises(ValueError):
                m.replace_config(self.args(), self.env)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.active.read_text(), PROFILE)

    def test_network_status_warns(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            m.network_status(self.env)
        self.assertIn('WARNING:', out.getvalue())
        self.discover.return_value = {k: self.env[k] for k in self.new_net}
        with contextlib.redirect_stdout(io.StringIO()) as out:
            m.network_status(self.env)
        self.assertEqual(out.getvalue(), '')

    def test_first_awg_profile_install_uses_same_validation_path(self):
        self.active.unlink()
        self.previous.unlink(missing_ok=True)
        m.replace_config(self.args(), self.env)
        self.assertIn('192.0.2.2:', self.active.read_text())
        self.assertIn('Table = off', self.active.read_text())
        self.assertFalse(self.previous.exists())
        self.preflight.assert_called_once()
        self.assertEqual(
            sum(call == ('systemctl', 'start', 'awg-quick@awg0.service') for call in self.calls),
            1,
        )

    def test_failed_first_awg_profile_returns_to_no_profile(self):
        self.active.unlink()
        self.previous.unlink(missing_ok=True)
        self.health.return_value = False
        with self.assertRaises(RuntimeError):
            m.replace_config(self.args(), self.env)
        self.assertFalse(self.active.exists())
        self.assertFalse(self.previous.exists())
        self.assertEqual(
            sum(call == ('systemctl', 'start', 'awg-quick@awg0.service') for call in self.calls),
            1,
        )

    def test_rollback_without_previous_profile_is_explicit_and_safe(self):
        self.previous.unlink(missing_ok=True)
        with self.assertRaisesRegex(
                ValueError,
                'Откат недоступен: предыдущий AWG-профиль отсутствует'):
            m.replace_config(self.args(action='rollback', file=None), self.env)
        self.assertEqual(self.calls, [])
        self.preflight.assert_not_called()
        self.assertEqual(self.active.read_text(), PROFILE)
        self.assertFalse(Path(m.BACKUPS).exists())

    def test_config_success_and_manual_rollback(self):
        before = {f: Path(f).read_bytes() for f in [m.ENV, m.DNS, m.NFT, m.CLIENTS, m.DOMAINS]}
        m.replace_config(self.args(), self.env)
        self.assertIn('192.0.2.2:', self.active.read_text())
        self.assertEqual(self.previous.read_text(), PROFILE)
        self.assertIn('Table = off', self.active.read_text())
        if os.name == 'posix':
            self.assertEqual(self.active.stat().st_mode & 0o777, 0o600)
        stop = self.calls.index(('systemctl', 'stop', 'awg-quick@awg0.service'))
        self.assertLess(self.calls.index((m.FAILOPEN,)), stop)
        m.replace_config(self.args(action='rollback', file=None), self.env)
        self.assertIn('192.0.2.1:', self.active.read_text())
        self.assertIn('192.0.2.2:', self.previous.read_text())
        for f, value in before.items():
            self.assertEqual(Path(f).read_bytes(), value)

    def test_preflight_failure_leaves_live_state_untouched(self):
        self.preflight.side_effect = RuntimeError('rejected by core')
        with self.assertRaises(RuntimeError):
            m.replace_config(self.args(), self.env)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.active.read_text(), PROFILE)

    def test_check_does_not_change_files_or_services(self):
        with patch.object(m, 'confirm') as confirm:
            m.replace_config(self.args(action='check'), self.env)
        confirm.assert_not_called()
        self.preflight.assert_called_once()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.active.read_text(), PROFILE)
        self.assertFalse(Path(m.BACKUPS).exists())

    def test_config_transport_failure_restores_previous(self):
        self.health.side_effect = [False, True]
        self.previous.write_text('earlier backup')
        with self.assertRaises(RuntimeError):
            m.replace_config(self.args(), self.env)
        self.assertEqual(self.active.read_text(), PROFILE)
        self.assertEqual(self.previous.read_text(), 'earlier backup')
        self.assertIn(('systemctl', 'start', m.HEALTH), self.calls)

    def test_config_start_failure_rolls_back(self):
        self.fail_once = ('systemctl', 'start', 'awg-quick@awg0.service')
        with self.assertRaises(RuntimeError):
            m.replace_config(self.args(), self.env)
        self.assertEqual(self.active.read_text(), PROFILE)
        self.assertFalse(self.previous.exists())

    def test_config_failure_reasserts_original_active_profile(self):
        self.health.side_effect = [False, True]
        with patch.object(m.Transaction, 'restore', autospec=True):
            with self.assertRaises(RuntimeError):
                m.replace_config(self.args(), self.env)
        self.assertEqual(self.active.read_text(), PROFILE)

    def test_failed_recovery_keeps_direct(self):
        self.health.return_value = False
        with self.assertRaises(RuntimeError):
            m.replace_config(self.args(), self.env)
        self.assertEqual(self.active.read_text(), PROFILE)
        self.assertNotIn(('systemctl', 'start', m.HEALTH), self.calls)
        self.assertEqual(self.calls[-1], (m.FAILOPEN,))


class Discovery(unittest.TestCase):
    def test_preflight_validates_quick_and_core_without_live_interface(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'awg0.conf'
            config.write_text(PROFILE)
            calls = []
            def run(*args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, PROFILE)
            with patch.object(m, 'run', side_effect=run), patch('socket.getaddrinfo'):
                m.preflight(config, {'VPN_IF': 'awg0'})
            self.assertEqual(calls[0][:2], ('awg-quick', 'strip'))
            self.assertEqual(calls[1][:3], ('unshare', '--net', '--'))
            self.assertIn('awg setconf', calls[1][5])
            self.assertNotIn('Endpoint', (Path(temp) / 'core.conf').read_text())
            self.assertEqual(config.read_text(), PROFILE)

    def test_route_and_address_selection(self):
        routes = [{'gateway': '192.168.112.1', 'dev': 'eth0', 'metric': 100}]
        addresses = [{'addr_info': [{'local': '192.168.112.33', 'prefixlen': 24}]}]
        def run(*args):
            return subprocess.CompletedProcess(args, 0, json.dumps(routes if 'route' in args else addresses))
        with patch.object(m, 'run', side_effect=run):
            result = m.discover({'VPN_IF': 'awg0'})
            self.assertEqual(result['LAN_CIDR'], '192.168.112.0/24')
            self.assertEqual(result['PI_IP'], '192.168.112.33')
            routes.append(dict(routes[0]))
            with self.assertRaises(ValueError):
                m.discover({'VPN_IF': 'awg0'})

    def test_transport_accepts_https_fallback_and_requires_fresh_handshake(self):
        env = dict(HEALTH_MARK='0x101', HEALTH_TABLE='101', VPN_IF='awg0')
        calls = []
        stamp, ping_code, https_code = 100, 0, 1
        probe_rules = 1
        probe_rule = ('priority', '89', 'fwmark', '257', 'lookup', '101')

        def run(*args, **kwargs):
            nonlocal probe_rules
            calls.append(args)
            if args[:4] == ('ip', '-4', 'rule', 'del') and args[4:] == probe_rule:
                if probe_rules:
                    probe_rules -= 1
                    code, out = 0, ''
                else:
                    code, out = 2, ''
            elif args[:4] == ('ip', '-4', 'rule', 'add') and args[4:] == probe_rule:
                code, out = (2, '') if probe_rules else (0, '')
                if code == 0:
                    probe_rules = 1
            elif args[0] == 'ping':
                code, out = ping_code, ''
            elif args[0] == m.HTTPS_PROBE:
                code, out = https_code, ''
            elif args[0] == 'awg':
                code, out = 0, f'publickey {stamp}\n'
            else:
                code, out = 0, ''
            return subprocess.CompletedProcess(args, code, out)

        with patch.object(m, 'run', side_effect=run), patch.object(m.time, 'sleep'), patch.object(m.time, 'time', return_value=101):
            self.assertTrue(m.tunnel_ok(env, 100))
            self.assertEqual(probe_rules, 0)
            first_add = calls.index(('ip', '-4', 'rule', 'add', *probe_rule))
            self.assertIn(('ip', '-4', 'rule', 'del', *probe_rule), calls[:first_add])
            self.assertIn(('ping', '-4', '-n', '-I', 'awg0', '-m', '257', '-c1', '-W2', '9.9.9.9'), calls)
            stamp = 99
            self.assertFalse(m.tunnel_ok(env, 100))
            stamp, ping_code, https_code = 100, 1, 0
            self.assertTrue(m.tunnel_ok(env, 100))
            self.assertIn((m.HTTPS_PROBE, '257', 'awg0'), calls)
            https_code = 1
            self.assertFalse(m.tunnel_ok(env, 100))
            self.assertEqual(probe_rules, 0)
            self.assertEqual(calls[-1][:4], ('ip', '-4', 'rule', 'del'))


if __name__ == '__main__':
    unittest.main()
