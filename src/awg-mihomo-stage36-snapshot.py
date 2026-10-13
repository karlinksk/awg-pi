#!/usr/bin/env python3
"""Stage36: one-shot local recovery snapshot writer, NOT an installer/rollback.

Live mode is root-only, guarded, and intentionally not installed by install.sh.
Fixture mode uses fake inputs in a private directory and no real credentials.
No service/route/MikroTik/NAS operations exist in this module.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

SOURCE_FILES = (
    "etc/awg-pbr/transports/mihomo/config.yaml",
    "var/lib/awg-pbr/mihomo/providers/subscription.yaml",
    "etc/awg-pbr/transports/mihomo/provider.env",
    "etc/awg-pbr/transports/mihomo/node-name",
    "etc/awg-pbr/transports/mihomo/endpoint-ip",
    "etc/awg-pbr/transports/mihomo/expected-egress-ip",
    "etc/awg-pbr/transports/mihomo/node-policy.mode",
    "etc/awg-pbr/transports/mihomo/native-fallback.mode",
    "etc/awg-pbr/selection.env",
    "etc/awg-pbr/transport",
    "etc/awg-pbr/mode",
)
REQUIRED = set(SOURCE_FILES[:2])
RECOVERY = Path("/var/lib/awg-pbr/native-fallback-recovery")
MAX_FILE_BYTES = 16 * 1024 * 1024
READY = b"AWG_STAGE36_READY_1\n"


class Reject(Exception):
    pass


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(prefix=".stage36-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        if path.is_symlink():
            raise Reject("symlink destination")
        os.replace(name, path)
        fsync_dir(path.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def trusted_parent(path, uid):
    st = path.lstat()
    if (not stat.S_ISDIR(st.st_mode) or path.is_symlink() or st.st_uid != uid
            or (stat.S_IMODE(st.st_mode) & 0o022)):
        raise Reject("untrusted recovery parent")


def private_dir(path, uid):
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or stat.S_IMODE(st.st_mode) != 0o700 or path.is_symlink():
        raise Reject("unsafe private directory")


def hash_data(data):
    return hashlib.sha256(data).hexdigest()


def read_input(path, owner=None):
    if path.is_symlink():
        raise Reject("symlink input")
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_BYTES:
        raise Reject("invalid input type/size")
    if owner is not None and st.st_uid != owner:
        raise Reject("untrusted input ownership")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        now = os.fstat(fd)
        if (now.st_dev, now.st_ino) != (st.st_dev, st.st_ino):
            raise Reject("raced source file")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            value = stream.read(MAX_FILE_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(value) > MAX_FILE_BYTES:
        raise Reject("large source")
    return value, st


def capture(source_root, recovery, owner):
    trusted_parent(recovery.parent, owner)
    if recovery.exists() or recovery.is_symlink():
        raise Reject("recovery already exists; never overwrite")
    recovery.mkdir(mode=0o700)
    fsync_dir(recovery.parent)
    private_dir(recovery, owner)
    manifest = {}
    for i, logical in enumerate(SOURCE_FILES):
        src = source_root / logical
        # Nonexisting parent is allowed for optional records.
        if not src.exists() and not src.is_symlink():
            if logical in REQUIRED:
                raise Reject("required source missing")
            manifest[logical] = {"present": False}
            continue
        if src.parent.is_symlink() or src.parent.resolve() != src.parent:
            raise Reject("source directory symlink")
        value, st = read_input(src, owner)
        name = f"{i:02d}.bin"
        atomic_write(recovery / name, value)
        manifest[logical] = {
            "present": True,
            "file": name,
            "sha256": hash_data(value),
            "mode": stat.S_IMODE(st.st_mode),
            "uid": st.st_uid,
            "gid": st.st_gid,
        }
    metadata = {"version": 1, "files": manifest}
    atomic_write(recovery / "manifest.json", json.dumps(metadata, sort_keys=True).encode())
    # READY is last, after fsync of snapshots and manifest.
    atomic_write(recovery / "READY", READY)
    fsync_dir(recovery.parent)
    return len([x for x in manifest.values() if x["present"]])


def verify(recovery, owner):
    trusted_parent(recovery.parent, owner)
    private_dir(recovery, owner)
    marker, _ = read_input(recovery / "READY", owner)
    if marker != READY:
        raise Reject("recovery marker invalid")
    serialized, _ = read_input(recovery / "manifest.json", owner)
    meta = json.loads(serialized)
    records = meta.get("files")
    if meta.get("version") != 1 or not isinstance(records, dict) or set(records) != set(SOURCE_FILES):
        raise Reject("unexpected manifest contents")
    entries = 0
    for i, logical in enumerate(SOURCE_FILES):
        item = records[logical]
        if not isinstance(item, dict):
            raise Reject("record invalid")
        if item.get("present") is False:
            if logical in REQUIRED:
                raise Reject("required backup missing")
            continue
        if item.get("present") is not True or item.get("file") != f"{i:02d}.bin":
            raise Reject("mismatched backup")
        if type(item.get("mode")) is not int or type(item.get("uid")) is not int or type(item.get("gid")) is not int:
            raise Reject("invalid file metadata")
        if item["uid"] != owner or not 0 <= item["mode"] <= 0o777:
            raise Reject("unsafe restore metadata")
        file = recovery / item["file"]
        blob, st = read_input(file, owner)
        if stat.S_IMODE(st.st_mode) != 0o600 or hash_data(blob) != item.get("sha256"):
            raise Reject("backup contents corrupted")
        entries += 1
    # Forbid unexpected payloads that could sneak into trusted backup area.
    expected = {"READY", "manifest.json", *(f"{i:02d}.bin" for i, n in enumerate(SOURCE_FILES) if records[n]["present"] is True)}
    present = {p.name for p in recovery.iterdir()}
    if present != expected:
        raise Reject("unexpected backup payload")
    return entries


def fixture_root(path):
    raw = Path(path).absolute()
    root = raw.resolve(strict=True)
    if root != raw or root.parent not in (Path("/tmp").resolve(), Path.home().resolve()) or not root.name.startswith("awg-stage36-"):
        raise Reject("not a private fixture")
    private_dir(root, os.geteuid())
    private_dir(root / "source", os.geteuid())
    return root


def prepare_fixture(root):
    root = fixture_root(root)
    return root / "source", root / "recovery", os.geteuid()


def production_paths():
    if os.geteuid() != 0:
        raise Reject("root required for live backup")
    # Single exact destination; never accept a caller-selected real path.
    parent = RECOVERY.parent
    if parent.is_symlink() or parent.resolve() != parent:
        raise Reject("unexpected recovery parent")
    trusted_parent(parent, 0)
    for p in (Path("/etc/awg-pbr"), Path("/etc/awg-pbr/transports"), Path("/etc/awg-pbr/transports/mihomo"),
              Path("/var/lib/awg-pbr/mihomo"), Path("/var/lib/awg-pbr/mihomo/providers")):
        if p.is_symlink() or p.resolve() != p or p.stat().st_uid != 0:
            raise Reject("source directory untrusted")
    return Path("/"), RECOVERY, 0


def acquire_maintenance_lock(path, owner):
    if path.is_symlink():
        raise Reject("maintenance lock symlink")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != owner
                or (stat.S_IMODE(st.st_mode) & 0o022)):
            raise Reject("maintenance lock ownership or mode unsafe")
        # Existing awg-selection-monitor honors this exact advisory lock.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except Exception:
        os.close(fd)
        raise


def main():
    p = argparse.ArgumentParser(description="Snapshot/verify ONLY; no production cutover or restore")
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fixture-root")
    modes.add_argument("--production", action="store_true")
    p.add_argument("--snapshot", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--acknowledge-production-snapshot", action="store_true")
    args = p.parse_args()
    try:
        if args.snapshot == args.verify:
            raise Reject("choose exactly one operation")
        if args.production:
            if args.snapshot and not args.acknowledge_production_snapshot:
                raise Reject("explicit live snapshot approval required")
            source, path, uid = production_paths()
        else:
            if args.acknowledge_production_snapshot:
                raise Reject("invalid fixture option")
            source, path, uid = prepare_fixture(args.fixture_root)
        # Serialize backup with both its own writer and the existing
        # awg-maintenance.lock. Full cutover must hold the same lock
        # across subsequent config/service/route transitions.
        lockfile = source.parent / ".stage36-snapshot.lock" if not args.production else RECOVERY.parent / ".stage36-snapshot.lock"
        fd = os.open(lockfile, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            maintenance_path = Path("/run/awg-maintenance.lock") if args.production else source.parent / ".maintenance.lock"
            md = acquire_maintenance_lock(maintenance_path, uid)
            try:
                if args.snapshot:
                    result = capture(source, path, uid)
                else:
                    result = verify(path, uid)
            finally:
                os.close(md)
        finally:
            os.close(fd)
        print(f"STAGE36_{'SNAPSHOT' if args.snapshot else 'VERIFY'}=PASS entries={result}")
        return 0
    except (OSError, ValueError, Reject, json.JSONDecodeError) as e:
        print("STAGE36_REJECTED=" + type(e).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
