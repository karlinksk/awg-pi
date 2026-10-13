#!/usr/bin/env python3
"""Stage38: exact-file rollback core, fixture-only, no live restore mode.

The verifier consumes the Stage36 immutable READY backup and restores exact
file presence, bytes and mode into a private fake filesystem. An external
synthetic lockdown marker is required. No actual netfilter/systemd or VPN
paths can be accessed with the provided CLI.
"""
import argparse
import fcntl
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile

LIB = Path(__file__).with_name("awg-mihomo-stage36-snapshot.py")
spec = importlib.util.spec_from_file_location("stage36", LIB)
snap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snap)

GUARD = b"STAGE38_FIXTURE_LOCKDOWN\n"


class Denied(Exception):
    pass


def assert_under_fixture(root, path, owner):
    root = root / "source"
    target = path.relative_to(root)
    p = root
    if not target.parts:
        raise Denied("empty restore target")
    for comp in target.parts[:-1]:
        p = p / comp
        if p.is_symlink() or not p.is_dir():
            raise Denied("unsafe restore parent")
        info = p.lstat()
        if info.st_uid != owner or (stat.S_IMODE(info.st_mode) & 0o022):
            raise Denied("restore parent not trusted")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Denied("unsafe restore destination")


def require_quarantine(root, owner):
    path = root / "fixture-lockdown.guard"
    blob, st = snap.read_input(path, owner)
    if blob != GUARD or stat.S_IMODE(st.st_mode) != 0o600:
        raise Denied("no trusted mock lockdown")


def safe_write(path, blob, mode, owner, group):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".stage38-")
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, owner, group)
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        if path.is_symlink():
            raise Denied("symlink appeared before rename")
        os.replace(tmp, path)
        snap.fsync_dir(path.parent)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def validate_plan(root, owner):
    count = snap.verify(root / "recovery", owner)
    import json
    contents, _ = snap.read_input(root / "recovery" / "manifest.json", owner)
    manifest = json.loads(contents)["files"]
    result = []
    for idx, logical in enumerate(snap.SOURCE_FILES):
        source = root / "source" / logical
        assert_under_fixture(root, source, owner)
        spec = manifest[logical]
        if spec["present"]:
            file = root / "recovery" / spec["file"]
            blob, _ = snap.read_input(file, owner)
            result.append((source, blob, spec["mode"], spec["uid"], spec["gid"]))
        else:
            result.append((source, None, None, None, None))
    return count, result


def exact_restore(root, owner, interrupt_after=None):
    require_quarantine(root, owner)
    count, planned = validate_plan(root, owner)
    for idx, (dest, blob, mode, uid, gid) in enumerate(planned):
        if blob is None:
            if dest.exists():
                if dest.is_symlink():
                    raise Denied("symlink appeared during restore")
                dest.unlink()
                snap.fsync_dir(dest.parent)
        else:
            safe_write(dest, blob, mode, uid, gid)
        if interrupt_after == idx:
            os._exit(42)
    # Validate the restored file state against the immutable manifest.
    for dest, blob, mode, uid, gid in planned:
        if blob is None:
            if dest.exists() or dest.is_symlink():
                raise Denied("formerly absent file survived")
        else:
            data, info = snap.read_input(dest, owner)
            if data != blob or stat.S_IMODE(info.st_mode) != mode or info.st_gid != gid:
                raise Denied("restore validation failed")
    # Recovery does not remove backups/guard or reopen protected Transit.
    return count


def main():
    ap = argparse.ArgumentParser(description="PRIVATE FILE-RESTORE FIXTURE; no production mode")
    ap.add_argument("--fixture-root", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--restore", action="store_true")
    mode.add_argument("--verify", action="store_true")
    ap.add_argument("--crash-after-index", type=int, choices=range(0, len(snap.SOURCE_FILES)))
    args = ap.parse_args()
    try:
        root = snap.fixture_root(args.fixture_root)
        owner = os.geteuid()
        maint = snap.acquire_maintenance_lock(root / ".maintenance.lock", owner)
        try:
            if args.verify:
                count = snap.verify(root / "recovery", owner)
                result = "VERIFIED"
            else:
                count = exact_restore(root, owner, args.crash_after_index)
                result = "RESTORED_GUARD_HELD"
        finally:
            os.close(maint)
        print(f"STAGE38_FIXTURE={result} entries={count}")
        return 0
    except (OSError, ValueError, Denied, snap.Reject) as ex:
        print("STAGE38_REJECTED=" + type(ex).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
