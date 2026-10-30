"""Disposable binaries, fake systemd/fetch only; never invokes a live updater."""
import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ELEVATE = '[[ ${EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"'


class SafeEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.bin = self.p / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        AWG_COMMON_FILE=str(ROOT / 'src/awg-common'),
                        AWG_LOCK_FILE=str(self.p / 'lock'),
                        AWG_MODE_FILE=str(self.p / 'mode'),
                        AWG_TRANSPORT_FILE=str(self.p / 'transport'),
                        AWG_ENV_FILE=str(self.p / 'no-env'),
                        AWG_ENGINE_BACKUP_ROOT=str(self.p / 'backups'),
                        AWG_CORE_BIN_ROOT=str(self.bin),
                        MIHOMO_TARGET=str(self.bin / 'mihomo'),
                        AWG_XRAY_BINARY=str(self.bin / 'xray'),
                        SYSTEMCTL_BIN=str(self.bin / 'systemctl'),
                        AWG_ROUTE_BIN=str(self.bin / 'route'),
                        TEST_LOG=str(self.p / 'calls'))
        self.script('systemctl', '''echo "systemctl $*" >>"$TEST_LOG"
if [[ "$1" == show ]]; then echo "${TEST_STATE-inactive}"; exit 0; fi
if [[ "$1" == is-active ]]; then [[ "${TEST_STATE:-inactive}" == active ]]; exit $?; fi
exit 99
''')
        self.script('route', '''echo "route $*" >>"$TEST_LOG"
printf 'Mode ID: transit\nTransit guard: %s\n' "${TEST_GUARD-SAFE}"
''')
        self.script('sudo', 'echo UNEXPECTED_SUDO >&2; exit 99\n')
        self.script('dpkg', 'echo arm64\n')

    def script(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\n' + body)
        path.chmod(0o755)
        return path

    def run_bash(self, body, **extra):
        return subprocess.run(['bash', '-c', 'set -Eeuo pipefail\n' + body],
                              env=dict(self.env, **extra), text=True, capture_output=True)

    def helper(self, body, **extra):
        return self.run_bash('source "$AWG_COMMON_FILE"\n' + body, **extra)

    def updater(self, name, *args, **extra):
        # Rootless copy: only omit privilege handoff; all production logic stays.
        path = self.p / name
        path.write_text((ROOT / 'src' / name).read_text().replace(ELEVATE, ':'))
        path.chmod(0o755)
        return subprocess.run(['bash', str(path), *args], env=dict(self.env, **extra),
                              text=True, capture_output=True)

    def test_active_and_unknown_services_refused_before_mutation(self):
        for state in ('active', 'activating', 'deactivating', 'reloading', '', 'unknown'):
            with self.subTest(state=state):
                r = self.helper('awg_engine_lock\nawg_engine_inactive awg test.service',
                                TEST_STATE=state)
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertFalse((self.p / 'backups').exists())

    def test_selected_awg_mihomo_and_xray_dependency_refused(self):
        for engine, selected in [('awg', 'awg'), ('mihomo', 'mihomo'), ('xray', 'mihomo')]:
            (self.p / 'transport').write_text(selected)
            r = self.helper(f'awg_engine_inactive {engine} test.service')
            self.assertEqual(r.returncode, 3)
            self.assertIn('REFUSED_SELECTED_TRANSPORT', r.stderr)

    def test_missing_or_invalid_configured_transport_refused(self):
        (self.p / 'no-env').touch()
        r = self.helper('awg_engine_inactive awg test.service')
        self.assertNotEqual(r.returncode, 0)
        (self.p / 'transport').write_text('garbage')
        self.assertNotEqual(self.helper('awg_engine_inactive awg test.service').returncode, 0)

    def test_transit_requires_known_guard_without_route_writes(self):
        (self.p / 'mode').write_text('transit')
        for guard, success in [('SAFE', True), ('LOCKDOWN', True), ('UNSAFE', False), ('', False)]:
            r = self.helper('awg_engine_inactive awg test.service', TEST_GUARD=guard)
            self.assertEqual(r.returncode == 0, success, r.stderr)
        calls = (self.p / 'calls').read_text()
        self.assertNotIn('stop', calls)
        self.assertNotIn('start', calls)
        self.assertNotIn('disable', calls)

    def test_busy_shared_lock_prevents_update(self):
        with (self.p / 'lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = self.helper('awg_engine_lock')
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('BUSY', r.stderr)

    def publish(self, tail):
        (self.p / 'old').write_text('original')
        (self.p / 'candidate').write_text('new')
        return self.helper('awg_engine_lock\n'
                           'awg_engine_publish test "$TEST_DIR/candidate" "$TEST_DIR/old" '
                           '"$TEST_DIR/candidate" "$TEST_DIR/missing"\n' + tail,
                           TEST_DIR=str(self.p))

    def test_failed_postcheck_restores_bytes_and_absence(self):
        r = self.publish('false')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.p / 'old').read_text(), 'original')
        self.assertFalse((self.p / 'missing').exists())
        self.assertIn('ENGINE_ROLLBACK=RESTORED', r.stderr)
        self.assertFalse(list(self.p.glob('*.update.*')))

    def test_term_restores_without_service_or_route_changes(self):
        r = self.publish('kill -TERM $$')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.p / 'old').read_text(), 'original')
        self.assertFalse((self.p / 'missing').exists())
        self.assertFalse((self.p / 'calls').exists())

    def test_commit_retains_verified_backup_and_publishes_both(self):
        r = self.publish('awg_engine_commit')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.p / 'old').read_text(), 'new')
        self.assertEqual((self.p / 'missing').read_text(), 'new')
        backup = next((self.p / 'backups').iterdir())
        self.assertEqual((backup / '0').read_text(), 'original')
        self.assertFalse((backup / 'PENDING').exists())
        checked = subprocess.run(['sha256sum', '-c', str(backup / 'SHA256SUMS')],
                                 capture_output=True)
        self.assertEqual(checked.returncode, 0)

    def test_partial_publish_failure_restores_already_replaced_file(self):
        self.script('mv', '''if [[ "$*" == *missing && ! -e "$TEST_ONCE" ]]; then
  touch "$TEST_ONCE"; exit 1
fi
exec /usr/bin/mv "$@"
''')
        self.env['TEST_ONCE'] = str(self.p / 'once')
        r = self.publish('awg_engine_commit')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.p / 'old').read_text(), 'original')
        self.assertFalse((self.p / 'missing').exists())
        self.assertIn('ENGINE_ROLLBACK=RESTORED', r.stderr)

    def test_corrupted_backup_is_not_restored_or_reported_success(self):
        r = self.publish('printf corrupt >"$AWG_ENGINE_BACKUP/0"\nfalse')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('FAILED_BACKUP_HASH', r.stderr)
        self.assertTrue(list((self.p / 'backups').glob('*/PENDING')))

    def test_symlink_target_is_not_replaced(self):
        (self.p / 'candidate').write_text('new')
        (self.p / 'real').write_text('old')
        (self.p / 'link').symlink_to(self.p / 'real')
        r = self.helper('awg_engine_publish test "$TEST_DIR/candidate" "$TEST_DIR/link"',
                        TEST_DIR=str(self.p))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.p / 'real').read_text(), 'old')

    def test_awg_active_refusal_never_fetches_or_calls_failopen(self):
        self.script('git', 'echo UNEXPECTED_GIT >&2; exit 99\n')
        for mode in ('selective', 'transit'):
            (self.p / 'mode').write_text(mode)
            r = self.updater('awg-core-update', '--yes', TEST_STATE='active')
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn('UNEXPECTED_GIT', r.stderr)
        source = (ROOT / 'src/awg-core-update').read_text()
        self.assertNotIn('/awg-pbr-failopen', source)
        self.assertNotIn('systemctl stop', source)
        self.assertNotIn('ls-remote', source)

    def test_mihomo_direct_install_cannot_bypass_active_guard(self):
        r = self.updater('awg-mihomo-install', TEST_STATE='active')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('REFUSED_RUNNING_OR_UNKNOWN', r.stderr)

    def test_mihomo_bad_sha_cannot_be_overridden(self):
        archive = self.p / 'bad.gz'
        archive.write_bytes(b'not a pinned release')
        r = self.updater('awg-mihomo-install', '--file', str(archive),
                         MIHOMO_INSTALL_ASSET_SHA256='0' * 64)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('SHA256 mismatch', r.stderr)
        self.assertFalse((self.bin / 'mihomo').exists())

    def test_xray_active_refusal(self):
        r = self.updater('awg-xray-install', 'ensure', TEST_STATE='active')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('REFUSED_RUNNING_SERVICE', r.stderr)
        self.assertFalse((self.bin / 'xray').exists())

    def xray_fixture(self, version='26.3.27'):
        archive = self.p / 'xray.zip'
        binary = (f"#!/bin/sh\necho 'Xray {version} (fixture)'; exit 0\n#").encode()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('xray', binary + b'x' * 10000000)
        fetch = self.script('fetch', '''while (( $# )); do
  if [[ "$1" == --output ]]; then cp "$TEST_ARCHIVE" "$2"; exit 0; fi
  shift
done
exit 1
''')
        self.env.update(AWG_XRAY_FETCH=str(fetch), TEST_ARCHIVE=str(archive))

    def test_xray_hash_failure_keeps_old_binary(self):
        self.xray_fixture()
        self.script('xray', "echo 'Xray 0.0.1 (old)'\n")
        old = (self.bin / 'xray').read_bytes()
        r = self.updater('awg-xray-install', 'ensure')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('HASH_MISMATCH', r.stderr)
        self.assertEqual((self.bin / 'xray').read_bytes(), old)

    def test_xray_verified_candidate_publishes_without_starting_service(self):
        self.xray_fixture()
        self.script('xray', "echo 'Xray 0.0.1 (old)'\n")
        # Only substitute the synthetic archive at the cryptographic boundary.
        # Assert that production asked for the exact pinned archive hash.
        self.script('sha256sum', '''if [[ "$1" == -c && "$2" == - ]]; then
  read -r expected path
  [[ "$expected" == 4d30283ae614e3057f730f67cd088a42be6fdf91f8639d82cb69e48cde80413c ]] || exit 1
  cmp -s "$path" "$TEST_ARCHIVE"; exit $?
fi
exec /usr/bin/sha256sum "$@"
''')
        r = self.updater('awg-xray-install', 'ensure')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('PINNED_VERIFIED', r.stdout)
        self.assertNotIn('start ', (self.p / 'calls').read_text())
        self.assertTrue(list((self.p / 'backups').glob('*/SHA256SUMS')))

    def test_pins_and_installer_delivery(self):
        installer = (ROOT / 'install.sh').read_text()
        core = (ROOT / 'src/awg-core-update').read_text()
        for pin in ('b5928efb6ca19f0153958460c3d141f04abc5c2e',
                    'ee0f0a9aa34ff0a0da4b3433b9512781cfe02843'):
            self.assertIn(pin, installer)
            self.assertIn(pin, core)
        for source in ('awg-common', 'awg-core-update', 'awg-mihomo-install',
                       'awg-xray-install', 'awg-update', 'awg-menu'):
            self.assertIn('src/' + source, installer)

    def test_all_reports_each_engine_once_despite_core_failure(self):
        source = (ROOT / 'src/awg-update').read_text().replace(ELEVATE, ':')
        for name in ('core-update', 'mihomo-install', 'xray-install'):
            source = source.replace('/usr/local/sbin/awg-' + name, str(self.bin / name))
            self.script(name, 'echo "' + name + ' $*" >>"$TEST_LOG"\n'
                        '[[ "$1" == status ]] && exit 0\n' +
                        ('exit 7\n' if name == 'core-update' else 'exit 0\n'))
        self.script('curl', 'echo \'{"tag_name":"v1.3.0"}\'\n')
        self.script('jq', 'echo v1.3.0\n')
        path = self.p / 'update-copy'
        path.write_text(source)
        r = subprocess.run(['bash', str(path), '--yes', 'all'],
                           env=dict(self.env, AWG_UPDATE_REEXEC='1'),
                           text=True, capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        for engine in ('core', 'mihomo', 'xray'):
            self.assertIn('ENGINE_RESULT=' + engine, r.stdout)
        calls = (self.p / 'calls').read_text()
        self.assertEqual(calls.count('core-update --yes'), 1)
        self.assertEqual(calls.count('mihomo-install ensure'), 1)
        self.assertEqual(calls.count('xray-install ensure'), 1)
        self.assertNotIn('systemctl', calls)


if __name__ == '__main__':
    unittest.main()
