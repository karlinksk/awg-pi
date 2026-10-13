#!/usr/bin/env python3
"""Stage39: integrated transaction coordinator, FIXTURE ONLY.

Unifies Stage36 snapshot, Stage37 shared maintenance lock and Stage38 exact
restore. It cannot target real Pi configs, netfilter, systemd, MikroTik or NAS.
An immutable local mock lockdown marker is NOT proof of real nftables safety.
"""
from __future__ import annotations
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent

def load(name, module):
    spec = importlib.util.spec_from_file_location(module, HERE/name)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

snap = load("awg-mihomo-stage36-snapshot.py", "stage39_snapshot")
restore = load("awg-mihomo-stage38-restore-fixture.py", "stage39_restore")
JOURNAL = "stage39-transaction.json"
READY = "stage39-commit-marker"
PHASES = ("backup", "journal", "lockdown", "candidate", "verified", "confirmed")

class Refused(Exception):
    pass

def marker_path(root):
    return root / "fixture-lockdown.guard"

def state_path(root):
    return root / JOURNAL

def journal_read(root):
    path = state_path(root)
    if path.is_symlink():
        raise Refused("symlink journal")
    raw, meta = snap.read_input(path, os.geteuid())
    if (meta.st_mode & 0o777) != 0o600:
        raise Refused("journal permission invalid")
    obj = json.loads(raw)
    if not isinstance(obj, dict) or obj.get("schema") != 1 or obj.get("status") not in ("pending", "confirmed"):
        raise Refused("invalid journal")
    return obj

def write_journal(root, status="pending"):
    snap.atomic_write(state_path(root), json.dumps({"schema": 1, "status": status}, sort_keys=True).encode())

def safe_lockdown(root):
    # Real production work would need an independently verified nftables chain.
    # This writes only a local mock fixture sentinel.
    snap.atomic_write(marker_path(root), restore.GUARD)
    st = marker_path(root).stat()
    if (st.st_mode & 0o777) != 0o600:
        raise Refused("failed to protect guard")

def fake_healthy(root):
    """Only synthetic, written-by-test state; not a real network probe."""
    path = root / "fixture-health.txt"
    value, _ = snap.read_input(path, os.geteuid())
    return value == b"READY:HTTPS:DIRECT:GUARD\n"

def test_candidate(root):
    candidate = root / "fixture-candidate"
    value, _ = snap.read_input(candidate, os.geteuid())
    if value != b"STAGE39_NATIVE_FALLBACK_TEST_ONLY\n":
        raise Refused("invalid test candidate")
    return value

def crash_if(point, asked):
    if point == asked:
        os._exit(42)

def start(root, fault):
    if state_path(root).exists() or (root / "recovery").exists():
        raise Refused("existing transaction or orphan backup")
    if not fake_healthy(root):
        raise Refused("fixture preflight unhealthy")
    fake = test_candidate(root)
    owner = os.geteuid()
    count = snap.capture(root / "source", root / "recovery", owner)
    snap.verify(root / "recovery", owner)
    crash_if("backup", fault)
    write_journal(root)
    crash_if("journal", fault)
    safe_lockdown(root)
    crash_if("lockdown", fault)
    # Only the synthetic config path is modified. Backup remains immutable.
    config = root / "source" / snap.SOURCE_FILES[0]
    if config.is_symlink():
        raise Refused("fixture symlink config")
    snap.atomic_write(config, fake)
    crash_if("candidate", fault)
    if not fake_healthy(root):
        raise Refused("post-stage health failed")
    crash_if("verified", fault)
    return count

def restore_and_verify(root, fault):
    owner = os.geteuid()
    safe_lockdown(root)
    snap.verify(root / "recovery", owner)
    crash_if("verify-backup", fault)
    # Stage38 exact_restore shares the caller's maintenance lock.
    count = restore.exact_restore(root, owner)
    crash_if("restored", fault)
    if not fake_healthy(root):
        raise Refused("fake restored health rejected; retain lockdown")
    return count

def cleanup_confirmed(root):
    # Confirmed marker always precedes removal of backup and journal.
    if (root/"recovery").exists():
        shutil.rmtree(root/"recovery")
        snap.fsync_dir(root)
    state_path(root).unlink(missing_ok=True)
    snap.fsync_dir(root)

def recover(root, fault):
    existing = state_path(root).exists() or state_path(root).is_symlink()
    if not existing:
        if (root/"recovery").exists():
            safe_lockdown(root)
            return "ORPHAN_QUARANTINED"
        return "IDLE"
    try:
        journal = journal_read(root)
    except (ValueError, OSError, json.JSONDecodeError, Refused):
        safe_lockdown(root)
        return "CORRUPT_JOURNAL_QUARANTINED"
    if journal["status"] == "confirmed":
        cleanup_confirmed(root)
        return "COMMIT_CLEANUP"
    try:
        restore_and_verify(root, fault)
    except (OSError, ValueError, snap.Reject, restore.Denied, Refused, json.JSONDecodeError):
        return "ROLLBACK_UNSAFE_QUARANTINED"
    # KEEP recovery and journal for inspection until operator explicit ACK.
    return "RESTORED_GUARD_HELD"

def confirm(root):
    if journal_read(root)["status"] != "pending":
        raise Refused("not pending")
    owner = os.geteuid()
    restore.require_quarantine(root, owner)
    snap.verify(root/"recovery", owner)
    if not fake_healthy(root):
        raise Refused("not healthy")
    if snap.read_input(root/"source"/snap.SOURCE_FILES[0], owner)[0] != test_candidate(root):
        raise Refused("candidate not installed")
    write_journal(root, "confirmed")
    cleanup_confirmed(root)
    return "CONFIRMED"

def main():
    p = argparse.ArgumentParser(description="Stage39 synthetic fixture-only transaction")
    p.add_argument("--fixture-root", required=True)
    act = p.add_mutually_exclusive_group(required=True)
    act.add_argument("--start", action="store_true")
    act.add_argument("--recover", action="store_true")
    act.add_argument("--confirm", action="store_true")
    p.add_argument("--crash-after", choices=(*PHASES, "verify-backup", "restored"))
    opts = p.parse_args()
    try:
        root = snap.fixture_root(opts.fixture_root)
        owner = os.geteuid()
        fd = snap.acquire_maintenance_lock(root/".maintenance.lock", owner)
        try:
            if opts.start:
                value = f"PENDING entries={start(root, opts.crash_after)}"
            elif opts.recover:
                value = recover(root, opts.crash_after)
            else:
                value = confirm(root)
        finally:
            os.close(fd)
        print("STAGE39_FIXTURE=" + value)
        return 0 if value not in ("ORPHAN_QUARANTINED", "CORRUPT_JOURNAL_QUARANTINED", "ROLLBACK_UNSAFE_QUARANTINED") else 2
    except (OSError, ValueError, Refused, snap.Reject, restore.Denied, json.JSONDecodeError) as exc:
        print("STAGE39_REJECTED=" + type(exc).__name__, file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
