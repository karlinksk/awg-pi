#!/usr/bin/env python3
"""Stage35: ext4-capable crash-recovery integration FIXTURE, no production operations.

Only accepts one private test directory directly inside /tmp or $HOME, named
awg-stage35-*. Never reads /etc, /var, RouterOS, NAS, or any VPN credentials.
Independent processes model on-disk journal survival; no actual reboot.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

NAMES = ("config.yaml", "mode", "service-state", "route-state", "transport", "direct-state")
MANIFEST = "manifest.json"
READY = "READY"
JOURNAL = "transaction.json"
READY_VALUE = b"STAGE35_RECOVERY_READY\n"
MAX_BYTES = 1024 * 1024


class Unsafe(Exception):
    pass


def confined(path):
    raw = Path(path).absolute()
    root = raw.resolve(strict=True)
    allowed = (Path("/tmp").resolve(), Path.home().resolve())
    if root != raw or root.parent not in allowed or not root.name.startswith("awg-stage35-"):
        raise Unsafe("restricted to immediate, private fixture directory")
    st = root.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise Unsafe("invalid root ownership or mode")
    if root.is_symlink():
        raise Unsafe("symlinked root")
    for name in ("live", "backup"):
        p = root / name
        if p.is_symlink():
            raise Unsafe("symlinked fixture directory")
        if p.exists():
            meta = p.lstat()
            if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) != 0o700:
                raise Unsafe("fixture subdirectory must be private")
    return root


def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, content):
    fd, name = tempfile.mkstemp(prefix=".stage35-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if path.is_symlink():
            raise Unsafe("symlink target refused")
        os.replace(name, path)
        syncdir(path.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def regular(path):
    if path.is_symlink():
        raise Unsafe("symlink input refused")
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_BYTES:
        raise Unsafe("invalid backup source")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != (meta.st_dev, meta.st_ino):
            raise Unsafe("source changed before read")
        with os.fdopen(fd, "rb") as f:
            fd = -1
            data = f.read(MAX_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > MAX_BYTES:
        raise Unsafe("source too large")
    return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sentinels(root):
    """Synthetic immutable references; never accesses network devices."""
    result = {}
    for n in ("mikrotik.fixture", "nas.fixture"):
        result[n] = sha(regular(root / n))
    return result


def verify_sentinels(root, baseline):
    if sentinels(root) != baseline:
        raise Unsafe("independent external device fixtures changed")


def make_snapshot(root):
    if (root / "backup").exists() or (root / JOURNAL).exists():
        raise Unsafe("previous transaction needs resolution")
    source = root / "live"
    if not source.is_dir():
        raise Unsafe("fixture not prepared")
    backup = root / "backup"
    backup.mkdir(mode=0o700)
    syncdir(root)
    hashes = {}
    for name in NAMES:
        data = regular(source / name)
        atomic(backup / name, data)
        hashes[name] = sha(data)
    atomic(backup / MANIFEST, json.dumps({"version":1,"hashes":hashes},sort_keys=True).encode())
    atomic(backup / READY, READY_VALUE)
    syncdir(root)


def verify_snapshot(root):
    backup = root / "backup"
    if not backup.is_dir() or regular(backup / READY) != READY_VALUE:
        raise Unsafe("incomplete backup")
    metadata = json.loads(regular(backup / MANIFEST))
    if metadata.get("version") != 1 or set(metadata.get("hashes", {})) != set(NAMES):
        raise Unsafe("invalid manifest")
    restored = {}
    for name in NAMES:
        data = regular(backup / name)
        if sha(data) != metadata["hashes"][name]:
            raise Unsafe("backup digest mismatch")
        restored[name] = data
    if restored["mode"].strip() != b"legacy" or restored["transport"].strip() != b"mihomo":
        raise Unsafe("recovery state not a supported known-good fixture")
    if restored["route-state"].strip() != b"transit-safe" or restored["direct-state"].strip() != b"verified":
        raise Unsafe("backup lacks safe forwarding")
    if restored["service-state"].strip() != b"active" or not restored["config.yaml"]:
        raise Unsafe("recovery service unhealthy")
    return restored


def journal(root):
    data = json.loads(regular(root / JOURNAL))
    if data.get("version") != 1 or data.get("phase") not in ("pending", "committed"):
        raise Unsafe("unknown transaction state")
    return data


def arm(root, boot_id, fault=None):
    if (root / JOURNAL).exists():
        raise Unsafe("transaction already pending")
    orig = sentinels(root)
    make_snapshot(root)
    verify_snapshot(root)
    atomic(root / JOURNAL, json.dumps({"version":1,"phase":"pending","boot":boot_id},sort_keys=True).encode())
    if fault == "journal":
        os._exit(42)
    atomic(root / "live" / "route-state", b"lockdown\n")
    if fault == "lockdown":
        os._exit(42)
    atomic(root / "live" / "config.yaml", b"fallback: fixture-new\n")
    atomic(root / "live" / "mode", b"native\n")
    if fault == "install":
        os._exit(42)
    atomic(root / "live" / "route-state", b"transit-safe\n")
    if fault == "candidate":
        os._exit(42)
    verify_sentinels(root, orig)
    return "PENDING_CONFIRMATION"


def restore(root, fault=None):
    orig = sentinels(root)
    j = root / JOURNAL
    if not j.exists():
        if (root / "backup").exists():
            # A power failure after publishing READY but before the pending
            # journal must never allow the dependent forwarding stack to run.
            atomic(root / "live" / "route-state", b"lockdown\n")
            raise Unsafe("orphan backup requires review; lockdown retained")
        return "IDLE"
    try:
        phase = journal(root)["phase"]
    except (ValueError, KeyError, Unsafe, json.JSONDecodeError):
        atomic(root / "live" / "route-state", b"lockdown\n")
        raise Unsafe("invalid journal; lockdown retained")
    if phase == "committed":
        # Do not interrupt healthy traffic while cleaning a confirmed commit.
        cleanup(root)
        verify_sentinels(root, orig)
        return "COMMITTED_CLEANUP"
    # In production this must be enforced by nftables before any forwarded
    # traffic, not by a mock text file. NEVER restore/enable prematurely.
    atomic(root / "live" / "route-state", b"lockdown\n")
    saved = verify_snapshot(root)
    if fault == "verify":
        os._exit(42)
    for name in NAMES:
        if name == "route-state":
            continue
        atomic(root / "live" / name, saved[name])
        if fault == "restore:" + name:
            os._exit(42)
    verify_sentinels(root, orig)
    atomic(root / "live" / "route-state", saved["route-state"])
    if fault == "policy":
        os._exit(42)
    # Cleanup only after full byte-for-byte verification.
    for name in NAMES:
        if regular(root / "live" / name) != saved[name]:
            atomic(root / "live" / "route-state", b"lockdown\n")
            raise Unsafe("post-restore byte mismatch")
    cleanup(root)
    return "RECOVERED"


def cleanup(root):
    if (root / "backup").is_dir():
        shutil.rmtree(root / "backup")
        syncdir(root)
    if (root / JOURNAL).exists():
        (root / JOURNAL).unlink()
        syncdir(root)


def confirm(root):
    status = journal(root)
    if status["phase"] != "pending":
        raise Unsafe("not pending")
    if regular(root / "live" / "mode").strip() != b"native":
        raise Unsafe("new mode not healthy")
    if regular(root / "live" / "route-state").strip() != b"transit-safe":
        raise Unsafe("forwarding not safe")
    if regular(root / "live" / "direct-state").strip() != b"verified":
        raise Unsafe("direct route unsafe")
    if regular(root / "live" / "service-state").strip() != b"active":
        raise Unsafe("service unhealthy")
    verify_snapshot(root)
    atomic(root / JOURNAL, json.dumps({"version":1,"phase":"committed","boot":status["boot"]},sort_keys=True).encode())
    cleanup(root)
    return "CONFIRMED"


def main():
    ap = argparse.ArgumentParser(description="FIXTURE ONLY; never install or deploy")
    ap.add_argument("--fixture-root", required=True)
    actions = ap.add_mutually_exclusive_group(required=True)
    actions.add_argument("--arm", action="store_true")
    actions.add_argument("--boot-recover", action="store_true")
    actions.add_argument("--confirm", action="store_true")
    ap.add_argument("--boot-id", default="FIXTURE_BOOT")
    ap.add_argument("--crash-after", choices=("journal","lockdown","install","candidate","verify","policy",*("restore:"+n for n in NAMES if n!="route-state")))
    opt = ap.parse_args()
    try:
        root = confined(opt.fixture_root)
        lock = root / ".transaction.lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if opt.arm:
                value=arm(root,opt.boot_id,opt.crash_after)
            elif opt.boot_recover:
                value=restore(root,opt.crash_after)
            else:
                value=confirm(root)
        finally:
            os.close(fd)
        print("STAGE35_FIXTURE="+value)
        return 0
    except (Unsafe,OSError,ValueError,KeyError,json.JSONDecodeError,BlockingIOError) as exc:
        print("STAGE35_REJECTED="+type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
