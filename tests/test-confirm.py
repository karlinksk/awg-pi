"""Exercise real Linux controlling-terminal confirmation, without root or services."""
import argparse
import errno
import importlib.util
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import unittest

if sys.platform == 'linux':
    import pty

SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'awg-manage.py'
spec = importlib.util.spec_from_file_location('manage', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@unittest.skipUnless(sys.platform == 'linux', 'requires a Linux controlling PTY')
class Confirmation(unittest.TestCase):
    def interact(self, answers, expected=0, legacy=False):
        pid, master = pty.fork()
        if pid == 0:
            code = 0
            try:
                # SSH/TUI callers may redirect all standard streams. /dev/tty
                # must still display the prompt and supply the user's answer.
                with open(os.devnull, 'r+b', buffering=0) as null:
                    for fd in (0, 1, 2):
                        os.dup2(null.fileno(), fd)
                if legacy:
                    try:
                        with open('/dev/tty', 'r+'):
                            pass
                    except OSError:
                        os._exit(0)
                    os._exit(4)
                for _ in answers:
                    m.confirm(argparse.Namespace(yes=False), 'Подтвердить?')
            except ValueError as exc:
                code = 2 if 'Операция отменена' in str(exc) else 3
            except BaseException:
                code = 4
            os._exit(code)
        reaped = False
        output = b''
        sent = 0
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        output += os.read(master, 4096)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                    while sent < len(answers) and output.count(b'[y/N]: ') > sent:
                        os.write(master, answers[sent])
                        sent += 1
                done, status = os.waitpid(pid, os.WNOHANG)
                if done:
                    reaped = True
                    self.assertEqual(os.waitstatus_to_exitcode(status), expected, output)
                    if not legacy:
                        self.assertEqual(sent, len(answers), output)
                    return
            self.fail('Confirmation timed out: ' + repr(output))
        finally:
            if not reaped:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            os.close(master)

    def test_legacy_update_mode_cannot_open_terminal(self):
        self.interact([], legacy=True)

    def test_accepts_answers_and_repeated_prompts(self):
        self.interact([x.encode('utf-8') for x in ('y\n', 'YES\n', 'д\n', 'да\n')])

    def test_decline_empty_invalid_and_eof_cancel(self):
        for answer in (b'n\n', b'\n', b'maybe\n', b'\x04'):
            with self.subTest(answer=answer):
                self.interact([answer], expected=2)

    def test_no_terminal_rejects_piped_yes_but_allows_explicit_flag(self):
        script = '''import argparse, importlib.util, sys
spec = importlib.util.spec_from_file_location('manage', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
try:
    m.confirm(argparse.Namespace(yes=sys.argv[2] == 'yes'), 'Confirm?')
except ValueError as exc:
    print(exc)
    sys.exit(2)
'''
        for flag, expected in (('no', 2), ('yes', 0)):
            with self.subTest(flag=flag):
                result = subprocess.run([sys.executable, '-c', script, str(SOURCE), flag],
                                        input='yes\n', capture_output=True, text=True,
                                        encoding='utf-8', start_new_session=True, timeout=10)
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertIn('--yes', result.stdout)


if __name__ == '__main__':
    unittest.main()
