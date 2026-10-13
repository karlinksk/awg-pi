#!/usr/bin/env python3
"""Stage33: crash-consistent backup publication protocol; fixture only.

This is NOT a durable backup on Pi: the ONLY accepted root is in private /tmp
tmpfs. File and directory fsync are modeled but cannot prove power-loss
persistence on tmpfs. No writes outside the fixture are possible.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

FILES=("config.yaml","mode","service-state","route-state","transport","direct-state")
MAX_BYTES=8*1024*1024


class BackupError(Exception):
    pass


def fixture_root(path):
    root=Path(path).resolve(strict=True)
    if not root.is_relative_to(Path("/tmp").resolve()) or root==Path("/tmp"):
        raise BackupError("fixture path required")
    if not root.is_dir() or stat.S_IMODE(root.stat().st_mode)!=0o700 or root.stat().st_uid!=os.getuid():
        raise BackupError("unsafe fixture owner or mode")
    for name in ("live","recovery"):
        p=root/name
        if p.is_symlink():
            raise BackupError("fixture symlink")
        if p.exists() and (not p.is_dir() or stat.S_IMODE(p.stat().st_mode)!=0o700):
            raise BackupError("private directory required")
    return root


def fsync_directory(directory):
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_file(directory,name,data):
    # The caller owns the directory with 0700 and supplies only fixed names.
    if not name or "/" in name or name.startswith("."):
        raise BackupError("invalid destination")
    tmpfd,tmp=tempfile.mkstemp(dir=directory,prefix=".tmp-stage33-")
    try:
        os.fchmod(tmpfd,0o600)
        with os.fdopen(tmpfd,"wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,Path(directory)/name)
        fsync_directory(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def hash_data(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path):
    if path.is_symlink():
        raise BackupError("symbolic link refused")
    st=path.lstat()
    if not stat.S_ISREG(st.st_mode):
        raise BackupError("nonregular file refused")
    if st.st_size>MAX_BYTES:
        raise BackupError("file too large")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        cur=os.fstat(fd)
        if (cur.st_dev,cur.st_ino)!=(st.st_dev,st.st_ino):
            raise BackupError("source changed")
        with os.fdopen(fd,"rb") as f:
            fd=-1
            data=f.read(MAX_BYTES+1)
    finally:
        if fd>=0: os.close(fd)
    if len(data)>MAX_BYTES:
        raise BackupError("too many bytes")
    return data


def generate(root,abort_after=None):
    root=fixture_root(root)
    live=root/"live"
    if not live.is_dir() or live.is_symlink():
        raise BackupError("missing source fixture")
    recovery=root/"recovery"
    if recovery.exists():
        raise BackupError("recovery target already exists")
    recovery.mkdir(mode=0o700)
    fsync_directory(root)
    hashes={}
    for name in FILES:
        source=live/name
        if source.exists() or source.is_symlink():
            data=read_regular(source)
            atomic_file(recovery,name,data)
            hashes[name]={"sha256":hash_data(data),"present":True}
        else:
            hashes[name]={"present":False}
        if abort_after==name:
            raise BackupError("simulated interrupted backup")
    meta={"version":1,"files":hashes}
    atomic_file(recovery,"manifest.json",json.dumps(meta,sort_keys=True).encode())
    if abort_after=="manifest":
        raise BackupError("simulated interrupted backup")
    # READY marker is published LAST, only after manifest + copied files
    # have each been fsynced and recovery dir entry persisted.
    atomic_file(recovery,"READY",b"STAGE33_FIXTURE_SNAPSHOT_READY\n")
    fsync_directory(root)
    return len([f for f in hashes.values() if f["present"]])


def validate(root):
    root=fixture_root(root)
    recovery=root/"recovery"
    if recovery.is_symlink() or not recovery.is_dir():
        raise BackupError("no recovery data")
    marker=recovery/"READY"
    if not marker.exists() or read_regular(marker)!=b"STAGE33_FIXTURE_SNAPSHOT_READY\n":
        raise BackupError("backup not published")
    manifest=json.loads(read_regular(recovery/"manifest.json"))
    if manifest.get("version")!=1 or set(manifest.get("files",{}))!=set(FILES):
        raise BackupError("invalid manifest")
    for name,item in manifest["files"].items():
        source=recovery/name
        if item.get("present") is True:
            if hash_data(read_regular(source))!=item.get("sha256"):
                raise BackupError("backup hash mismatch")
        elif item.get("present") is False:
            if source.exists() or source.is_symlink():
                raise BackupError("unexpected backup file")
        else:
            raise BackupError("invalid record")
    return manifest


def recover_replica(root):
    # Restore ONLY into a new private fixture replica, never to live state.
    root=fixture_root(root)
    manifest=validate(root)
    replica=root/"restored-replica"
    if replica.exists():
        raise BackupError("replica must be new")
    replica.mkdir(mode=0o700)
    fsync_directory(root)
    for name,item in manifest["files"].items():
        if item["present"]:
            atomic_file(replica,name,read_regular(root/"recovery"/name))
    # Independent full verification of the recovered mock state.
    for name,item in manifest["files"].items():
        target=replica/name
        if item["present"]:
            if hash_data(read_regular(target))!=item["sha256"]:
                raise BackupError("replica differs")
        elif target.exists():
            raise BackupError("unexpected restored file")
    return True


def main():
    parser=argparse.ArgumentParser(description="Private /tmp fixture test only")
    parser.add_argument("--fixture-root",required=True)
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--snapshot",action="store_true")
    actions.add_argument("--verify",action="store_true")
    actions.add_argument("--rehearse-restore",action="store_true")
    parser.add_argument("--abort-after",choices=(*FILES,"manifest"))
    options=parser.parse_args()
    try:
        if options.snapshot:
            result=generate(options.fixture_root,options.abort_after)
            print(f"STAGE33_FIXTURE_BACKUP=READY files={result}")
        elif options.verify:
            validate(options.fixture_root)
            print("STAGE33_FIXTURE_BACKUP=VERIFIED")
        else:
            recover_replica(options.fixture_root)
            print("STAGE33_FIXTURE_REPLICA=RESTORED_VERIFIED")
    except (BackupError,OSError,ValueError,KeyError,json.JSONDecodeError) as e:
        print("STAGE33_FIXTURE_ERROR="+type(e).__name__,file=sys.stderr)
        return 2
    return 0

if __name__=="__main__":
    raise SystemExit(main())
