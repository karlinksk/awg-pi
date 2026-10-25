#!/usr/bin/env python3
"""Translate classic dialog list mouse-wheel events to cursor keys.

The SSH terminal reports SGR/X10 mouse events only while explicitly enabled.
Native dialog does not move the list selection for wheel events on this
platform. On a private input PTY, translate wheel to Up/Down and forward
native clicks and keyboard input unchanged. Dialog's result FDs are inherited
unchanged (important for Bash's 3>&1 1>&2 2>&3 idiom). No gateway or system settings are touched.
"""
import fcntl
import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import tty

ENABLE_MOUSE = b"\x1b[?1000;1006h"
DISABLE_MOUSE = b"\x1b[?1000;1006l"
SGR_MOUSE = re.compile(rb"\x1b\[<(\d{1,4});(\d{1,5});(\d{1,5})([Mm])")
UP = b"\x1bOA"
DOWN = b"\x1bOB"


def translate(data, pending=b""):
    """Return (keyboard bytes, unfinished escape bytes).

    An incomplete mouse packet can span multiple tty reads. The caller must
    flush abandoned prefixes after a short idle interval so Escape still works.
    """
    buf = pending + data
    output = bytearray()
    i = 0
    while i < len(buf):
        if buf[i] != 27:
            output.append(buf[i])
            i += 1
            continue
        remaining = buf[i:]
        if len(remaining) < 2:
            break
        if remaining[1:2] != b"[":
            output.append(27)
            i += 1
            continue
        if len(remaining) < 3:
            break
        if remaining.startswith(b"\x1b[<"):
            match = SGR_MOUSE.match(remaining)
            if match:
                button = int(match.group(1)) & 0xC3
                if match.group(4) == b"M" and button in (64, 65):
                    output.extend(UP if button == 64 else DOWN)
                else:
                    output.extend(match.group())  # Retain native mouse clicks.
                i += match.end()
                continue
            if len(remaining) < 40 and b"M" not in remaining and b"m" not in remaining:
                break
            output.append(27)
            i += 1
            continue
        if remaining.startswith(b"\x1b[M"):
            if len(remaining) < 6:
                break
            button = (remaining[3] - 32) & 0xC3
            if button in (64, 65):
                output.extend(UP if button == 64 else DOWN)
            else:
                output.extend(remaining[:6])
            i += 6
            continue
        # Not a mouse packet: preserve arrows and other escape sequences.
        output.append(27)
        i += 1
    return bytes(output), buf[i:]


def write_all(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def run(args):
    if not args:
        return 2
    try:
        terminal = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        # No controlling terminal (e.g. script automation); run normal dialog.
        os.execv("/usr/bin/dialog", ["dialog", *args])
    old_mode = termios.tcgetattr(terminal)
    master, slave = pty.openpty()
    child = None
    pending = b""
    try:
        size = fcntl.ioctl(terminal, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, size)
        # Keep dialog's real stdout/stderr for selected result and screen
        # drawing. Only its stdin is mediated via a private PTY.
        child = subprocess.Popen(
            ["/usr/bin/dialog", *args], stdin=slave,
            stdout=None, stderr=None, close_fds=True,
        )
        os.close(slave)
        slave = -1
        tty.setraw(terminal)
        # Raw input prevents stray terminal echo of rewritten arrow sequences.
        write_all(terminal, ENABLE_MOUSE)
        while child.poll() is None:
            try:
                ready, _, _ = select.select([terminal, master], [], [], 0.055)
            except InterruptedError:
                continue
            if terminal in ready:
                try:
                    raw = os.read(terminal, 4096)
                except InterruptedError:
                    continue
                if not raw:
                    break
                translated, pending = translate(raw, pending)
                if translated:
                    write_all(master, translated)
            elif pending:
                # Escape on its own must not hang waiting for a mouse packet.
                write_all(master, pending)
                pending = b""
            if master in ready:
                try:
                    rendered = os.read(master, 65536)
                except OSError:
                    rendered = b""
                if rendered:
                    write_all(terminal, rendered)
        if child.poll() is None:
            child.terminate()
        return child.wait()
    finally:
        try:
            write_all(terminal, DISABLE_MOUSE)
        finally:
            termios.tcsetattr(terminal, termios.TCSADRAIN, old_mode)
            os.close(terminal)
            if slave >= 0:
                os.close(slave)
            os.close(master)
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    try:
        sys.exit(run(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
