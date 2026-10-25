#!/usr/bin/env python3
"""Rootless wheel-input tests; no live menu, configuration or route changes."""
import fcntl
import importlib.util
import os
from pathlib import Path
import pty
import select
import shutil
import struct
import subprocess
import sys
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "extras/awg-classic-wheel.py"
MENU = (ROOT / "src/awg-menu").read_text()
INSTALLER = (ROOT / "install.sh").read_text()
spec = importlib.util.spec_from_file_location("awg_classic_wheel", HELPER)
wheel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wheel)


class ClassicWheel(unittest.TestCase):
    def test_sgr_wheel_both_directions_and_partial_packets(self):
        up = b"\x1b[<64;34;9M"
        down = b"\x1b[<65;34;9M"
        for seq, expected in (
            (up, wheel.UP),
            (down, wheel.DOWN),
            (down + up, wheel.DOWN + wheel.UP),
            (b"\x1b[<69;34;9M", wheel.DOWN),
            (b"\x1b[<0;34;9M", b"\x1b[<0;34;9M"),
            (b"\x1b[<65;34;9m", b"\x1b[<65;34;9m"),
            (b"\x1bOB", b"\x1bOB"),
        ):
            with self.subTest(seq=seq):
                self.assertEqual(wheel.translate(seq), (expected, b""))
        result, buffered = wheel.translate(down[:5])
        self.assertEqual(result, b"")
        result, buffered = wheel.translate(down[5:], buffered)
        self.assertEqual((result, buffered), (wheel.DOWN, b""))
        self.assertEqual(wheel.translate(b"\x1b[<64;34;9M\x1b"), (wheel.UP, b"\x1b"))

    def test_x10_legacy_wheel(self):
        up = b"\x1b[M" + bytes([64 + 32, 40 + 32, 10 + 32])
        down = b"\x1b[M" + bytes([65 + 32, 40 + 32, 10 + 32])
        self.assertEqual(wheel.translate(up + down), (wheel.UP + wheel.DOWN, b""))

    def test_installer_wires_helper_and_matrix_keeps_own_input(self):
        self.assertIn(
            "install_project_python_helper extras/awg-classic-wheel.py "
            "/usr/local/lib/awg-pi/awg-classic-wheel.py", INSTALLER
        )
        self.assertIn('AWG_MENU_MATRIX_INNER:-0', MENU)
        self.assertIn('/usr/bin/python3 -B /usr/local/lib/awg-pi/awg-classic-wheel.py', MENU)
        self.assertNotIn('args=(--no-mouse', MENU)

    @unittest.skipUnless(shutil.which("dialog"), "real dialog unavailable")
    def test_real_dialog_wheel_moves_selection_without_mouse_capture(self):
        for name, seq, result in (
            ("initial", b"", b"one"),
            ("one_down", b"\x1b[<65;43;12M", b"two"),
            ("two_down", b"\x1b[<65;43;12M" * 2, b"three"),
            ("down_then_up", b"\x1b[<65;43;12M\x1b[<64;43;12M", b"one"),
        ):
            with self.subTest(name=name):
                output, rc = self.invoke(seq)
                self.assertEqual(rc, 0, repr(output[-250:]))
                self.assertIn(result + b"\x1b[22;81H", output)
                self.assertIn(wheel.ENABLE_MOUSE, output)
                self.assertIn(wheel.DISABLE_MOUSE, output)

    def invoke(self, wheel_keys, *, swapped=False):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ,
                    struct.pack("HHHH", 28, 90, 0, 0))

        def controlling_tty():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        args = [sys.executable, str(HELPER), "--stdout",
                "--menu", "Mouse wheel", "15", "70", "8",
                "one", "One", "two", "Two", "three", "Three"]
        if swapped:
            args.remove("--stdout")  # dialog reports choice on stderr
            dialog_args = " ".join(
                ("'" + arg.replace("'", "'\\''") + "'") for arg in args
            )
            args = ["bash", "-c", (
                "selected=$(" + dialog_args + " 3>&1 1>&2 2>&3);"
                "printf 'SELECTED=%s\\n' \"$selected\""
            )]
        proc = subprocess.Popen(
            args, stdin=slave, stdout=slave, stderr=slave,
            env={**os.environ, "TERM": "xterm-256color"}, preexec_fn=controlling_tty
        )
        os.close(slave)
        captured = bytearray()

        def capture(seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                ready, _, _ = select.select(
                    [master], [], [], max(0, deadline - time.monotonic()))
                if ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    captured.extend(data)

        try:
            capture(.28)
            if wheel_keys:
                os.write(master, wheel_keys)
                capture(.14)
            os.write(master, b"\r")
            capture(.30)
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=2)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            os.close(master)
        return bytes(captured), proc.returncode

    @unittest.skipUnless(shutil.which("dialog"), "real dialog unavailable")
    def test_result_survives_bash_fd_swap(self):
        output, rc = self.invoke(b"\x1b[<65;43;12M", swapped=True)
        self.assertEqual(rc, 0, repr(output[-240:]))
        self.assertIn(b"SELECTED=two", output)


if __name__ == "__main__":
    unittest.main()
