#!/usr/bin/env python3
"""Independent, short-lived systemd timer cleanup for AWG DPI research sandbox.

WARNING: only the exact research namespace and ownership marker may be removed.
Never touch host routing, service configurations, nftables or production Mihomo.
Timers must pass the run-id; a stale timer cannot kill a newer experiment.
"""
from __future__ import annotations
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

NS = "awg-dpi-test"
MARKER = Path("/run/awg-dpi-test-owner")
EXPECTED_OWNER = "awg-dpi-test\nawdpi0\neth0\n"
SAFE_EXE = "/usr/local/bin/mihomo"


def run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=5)


def check_token(token):
    try:
        if not (MARKER / "owner").is_file() or (MARKER / "owner").read_text() != EXPECTED_OWNER:
            return "NOT_OWNED"
        if not (MARKER / "run-id").is_file() or (MARKER / "run-id").read_text().strip() != token:
            return "STALENESS_GUARD"
    except OSError:
        return "MARKER_UNREADABLE"
    return "OWNED"


def pids():
    out = run(["ip", "netns", "pids", NS])
    if out.returncode != 0:
        return []
    return [int(word) for word in out.stdout.split() if word.isdigit()]


def is_test_mihomo(pid):
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    argv = [v.decode("utf-8", errors="replace") for v in raw.split(b"\x00") if v]
    if exe != SAFE_EXE or not argv:
        return False
    # The child must be this experiment's Mihomo, not the production daemon.
    if not any(v.startswith("/run/awg-dpi-test-owner/") for v in argv):
        return False
    return True


def main():
    if os.geteuid() != 0:
        print("WATCHDOG=NOT_ROOT")
        return 2
    if len(sys.argv) != 2 or len(sys.argv[1]) != 24 or not all(c in "0123456789abcdef" for c in sys.argv[1]):
        print("WATCHDOG=INVALID_TOKEN")
        return 2
    token = sys.argv[1]
    status = check_token(token)
    if status != "OWNED":
        print("WATCHDOG=" + status)
        return 0
    occupants = pids()
    unsafe = [pid for pid in occupants if not is_test_mihomo(pid)]
    if unsafe:
        print("WATCHDOG=UNRECOGNIZED_PROCESS_ABORT")
        return 3
    for pid in occupants:
        try: os.kill(pid, signal.SIGTERM)
        except ProcessLookupError: pass
    end = time.monotonic() + 3
    while time.monotonic() < end and pids():
        time.sleep(0.2)
    for pid in pids():
        if not is_test_mihomo(pid):
            print("WATCHDOG=UNRECOGNIZED_PROCESS_ABORT")
            return 3
        try: os.kill(pid, signal.SIGKILL)
        except ProcessLookupError: pass
    if pids():
        print("WATCHDOG=PROCESSES_REMAIN")
        return 3
    sp = __import__("importlib.util")
    src = Path("/home/karlinks/awg-dpi-netns-sandbox.py")
    spec = sp.util.spec_from_file_location("awg_netns_sandbox", src)
    mod = sp.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if check_token(token) != "OWNED":
        print("WATCHDOG=STALE_BEFORE_CLEANUP")
        return 0
    try:
        mod.cleanup()
    except Exception:
        print("WATCHDOG=CLEANUP_FAILED")
        return 4
    print("WATCHDOG=CLEANED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
