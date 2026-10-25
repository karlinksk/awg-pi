#!/usr/bin/env python3
"""Read-only, no-extraction validator for private AWG Pi Gateway backups.

Prints only categorical status, counts and public component names. Never
prints archive content, subscribed node names, keys, URLs or credentials.
Does not assert bare-metal recovery, media-image validity or live rollback.
"""
import argparse
import gzip
import os
import re
import zlib
from pathlib import Path
import stat
import sys
import tarfile

# Exact archive entries required for the full current test-Pi installation.
# A conditional AWG-only or Mihomo-only initial setup can legitimately omit
# pieces; report that as a non-complete installed-state snapshot, not success.
REQUIRED = {
    "etc/awg-pbr",
    "etc/awg-pbr/mode",
    "etc/awg-pbr/transport",
    "etc/awg-pbr/transports/mihomo",
    "etc/amnezia/amneziawg",
    "etc/dnsmasq.d/99-awg-pbr.conf",
    "etc/systemd/system/awg-dc-remote@.service",
    "etc/systemd/system/awg-mihomo-hot-pool.service",
    "etc/systemd/system/awg-mihomo-hot-pool.timer",
    "etc/systemd/system/awg-mihomo-stage18-ram-runtime.service",
    "etc/systemd/system/awg-mihomo-stage18-ram-runtime.timer",
    "etc/systemd/system/awg-mihomo-pool-refresh.service",
    "etc/systemd/system/awg-mihomo-pool-refresh.timer",
    "etc/systemd/system.conf.d/99-awg-gateway-watchdog.conf",
    "usr/local/bin/mihomo",
    "usr/local/bin/awg-dc",
    "usr/local/sbin/awg-update",
    "usr/local/sbin/awg-route",
    "usr/local/sbin/awg-mihomo-pool",
    "usr/local/sbin/awg-mihomo-hot-pool",
    "usr/local/sbin/awg-mihomo-hot-service-scan",
    "usr/local/sbin/awg-hot-pool-continuity.py",
    "usr/local/sbin/awg-mihomo-hot-continuity-run",
    "usr/local/sbin/awg-mihomo-ready-live-match",
    "usr/local/sbin/awg-mihomo-ready-postcheck-tun",
    "usr/local/sbin/awg-mihomo-stage18-ram-runtime",
    "var/lib/awg-pbr/mihomo",
    "var/lib/awg-pbr/hot-pool",
    "var/lib/awg-pbr/hot-pool/continuity",
    "var/lib/awg-pbr/stage18-runtime",
    "usr/local/lib/awg-pi",
}
# Dynamic cache: directory alone is not proof the cache payload was preserved.
REQUIRE_NONEMPTY_SUBTREE = (
    "var/lib/awg-pbr/hot-pool/continuity/",
    "var/lib/awg-pbr/stage18-runtime/",
)

def inventory(archive_members, manifest_source, *, live_root=Path("/")):
    """Compare each currently installed manifest target against the archive."""
    try:
        text = Path(manifest_source).read_text()
        block = re.search(r"local -a backup_targets=\(\n(.*?)\n  \)", text, re.S)
        if block is None:
            return [], ["MANIFEST_SOURCE_INVALID"], 0
        paths = re.findall(r"(?m)^    ((?:etc|usr|var)/[^\s\\]+)\s*\\$", block.group(1))
        if len(paths) < 70 or len(paths) != len(set(paths)):
            return [], ["MANIFEST_SOURCE_INVALID"], 0
        present = [p for p in paths
                   if (live_root / p).exists() or (live_root / p).is_symlink()]
        return sorted(set(present) - archive_members), [], len(present)
    except (OSError, UnicodeError):
        return [], ["MANIFEST_SOURCE_UNREADABLE"], 0

def evaluate(archive, *, enforce_owner=True, manifest_source=None, live_root=Path("/")):
    archive = Path(archive)
    error = []
    members = set()
    files = 0
    processed_bytes = 0
    if not archive.is_file() or archive.is_symlink():
        return {"error": ["ARCHIVE_NOT_REGULAR_FILE"], "members": 0, "files": 0,
                "bytes": 0, "missing": sorted(REQUIRED), "subtrees": []}
    a = archive.stat()
    directory = archive.parent.stat()
    if enforce_owner and not (
        a.st_uid == 0 and directory.st_uid == 0
        and stat.S_IMODE(a.st_mode) == 0o600
        and stat.S_IMODE(directory.st_mode) == 0o700
    ):
        error.append("UNSAFE_OWNER_OR_PERMISSIONS")
    try:
        with tarfile.open(archive, "r|gz") as tf:
            for m in tf:
                name = m.name.removeprefix("./").rstrip("/")
                # Never extract archive entries or follow symlink targets.
                if name.startswith("/") or ".." in name.split("/"):
                    error.append("UNSAFE_ARCHIVE_MEMBER_PATH")
                    continue
                members.add(name)
                if m.isfile():
                    files += 1
                    stream = tf.extractfile(m)
                    if stream is None:
                        error.append("UNREADABLE_ARCHIVE_MEMBER")
                        continue
                    with stream:
                        while block := stream.read(1024 * 1024):
                            processed_bytes += len(block)
        # Reading each file and exhausting the stream validates gzip checksum.
    except (OSError, EOFError, tarfile.TarError, ValueError):
        error.append("ARCHIVE_STREAM_INTEGRITY")
    # A tar reader may stop at the two end-of-archive blocks *before* the gzip
    # trailer. Drain the entire gzip stream to independently verify the CRC32
    # and uncompressed size; truncated/corrupt archives must fail closed.
    try:
        with gzip.open(archive, "rb") as stream:
            while stream.read(1024 * 1024):
                pass
    except (OSError, EOFError, zlib.error, ValueError):
        error.append("ARCHIVE_STREAM_INTEGRITY")
    missing = sorted(REQUIRED - members)
    inventory_missing, inventory_errors, inventory_total = (
        inventory(members, manifest_source, live_root=live_root)
        if manifest_source is not None else ([], [], 0))
    error.extend(inventory_errors)
    subtrees = [
        prefix.rstrip("/") for prefix in REQUIRE_NONEMPTY_SUBTREE
        if not any(n.startswith(prefix) for n in members)
    ]
    return {"error": sorted(set(error)), "members": len(members),
            "files": files, "bytes": processed_bytes, "missing": missing,
            "subtrees": subtrees, "inventory_missing": inventory_missing,
            "inventory_total": inventory_total}

def verify(archive, *, enforce_owner=True, manifest_source=None, live_root=Path("/")):
    results = evaluate(archive, enforce_owner=enforce_owner,
                       manifest_source=manifest_source, live_root=live_root)
    print("BACKUP_ARCHIVE_STREAM=" + ("PASS" if "ARCHIVE_STREAM_INTEGRITY" not in results["error"] else "FAIL"))
    print("BACKUP_MEMBER_COUNT=" + str(results["members"]))
    print("BACKUP_FILE_COUNT=" + str(results["files"]))
    print("BACKUP_UNCOMPRESSED_FILE_BYTES=" + str(results["bytes"]))
    print("BACKUP_REQUIRED=" + str(len(REQUIRED)-len(results["missing"])) + "/" + str(len(REQUIRED)))
    print("BACKUP_REQUIRED_MANIFEST=" + ("PASS" if not results["missing"] else "FAIL"))
    print("BACKUP_CACHE_PAYLOAD=" + ("PASS" if not results["subtrees"] else "FAIL"))
    print("BACKUP_SECURITY=" + ("PASS" if not results["error"] else "FAIL"))
    if manifest_source is not None:
        print("BACKUP_INSTALLED_MANIFEST=" + ("PASS" if not results["inventory_missing"] and not any("MANIFEST_SOURCE" in x for x in results["error"]) else "FAIL"))
        print("BACKUP_INSTALLED_TARGETS=" + str(results["inventory_total"]))
    for missing in results["missing"]:
        print("MISSING_REQUIRED_PATH=" + missing)
    for subtree in results["subtrees"]:
        print("MISSING_CACHE_PAYLOAD=" + subtree)
    for item in results["inventory_missing"]:
        print("MISSING_INSTALLED_TARGET=" + item)
    for issue in results["error"]:
        print("BACKUP_ERROR=" + issue)
    # The timer enabled/disabled state is saved as a sibling of gateway-state.tgz.
    state = Path(archive).parent / "hot-pool-timer-state"
    try:
        st = state.stat()
        ok = (state.is_file() and not state.is_symlink()
              and (not enforce_owner or st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o600)
              and state.read_text().strip() in ("enabled", "disabled", "masked", "static"))
    except (OSError, UnicodeError):
        ok = False
    print("BACKUP_HOT_POOL_TIMER_STATE=" + ("PASS" if ok else "FAIL"))
    passed = not (results["missing"] or results["subtrees"] or results["error"] or results["inventory_missing"]) and ok
    print("BACKUP_COMPLETE_COMPONENT_CHECK=" + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Private gateway-state.tgz archive")
    parser.add_argument("--manifest", type=Path, default=Path("/usr/local/sbin/awg-backup-review"),
                        help="Root-owned pinned backup helper that generated the archive")
    args = parser.parse_args()
    sys.exit(verify(args.archive, manifest_source=args.manifest))
