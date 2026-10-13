#!/usr/bin/env python3
"""Stage31: fixture-only transaction/recovery prototype. NEVER edits production.

Intentional restriction: all writable paths must live below one private /tmp
tmpfs fixture, owned by this process. This code has no production apply mode.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

import yaml

ITEMS=("config.yaml","mode","service-state","route-state","transport","direct-state")
PHASES=("snapshot","quarantine","install","verify")
JOURNAL="transaction.json"


class TransactionError(Exception):
    pass


def hash_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(65536),b""):
            h.update(block)
    return h.hexdigest()


def private_root(root):
    root=Path(root).absolute()
    resolved=root.resolve(strict=True)
    if not resolved.is_relative_to(Path("/tmp").resolve()) or resolved==Path("/tmp"):
        raise TransactionError("fixture must be inside /tmp")
    mount=subprocess.run(["findmnt","-n","-o","FSTYPE","-T",str(resolved)],capture_output=True,text=True,timeout=5)
    if mount.returncode or mount.stdout.strip()!="tmpfs":
        raise TransactionError("fixture requires tmpfs")
    for p in (root,root/"live"):
        st=p.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o700:
            raise TransactionError("fixture directory owner/mode invalid")
        if p.is_symlink():
            raise TransactionError("fixture link refused")
    for name in (*ITEMS,"candidate.yaml"):
        f=root/(name if name=="candidate.yaml" else "live/"+name)
        if f.is_symlink():
            raise TransactionError("symlink refused")
        if f.exists() and not stat.S_ISREG(f.lstat().st_mode):
            raise TransactionError("nonregular file refused")
    return root


def atomic_bytes(path,data):
    path=Path(path)
    fd,tmp=tempfile.mkstemp(prefix=".stage31-",dir=str(path.parent))
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_json(path,value):
    atomic_bytes(path,json.dumps(value,sort_keys=True,separators=(",",":")).encode())


def read_fixture_candidate(root):
    data=yaml.safe_load((root/"candidate.yaml").read_text(encoding="utf-8"))
    if not isinstance(data,dict) or data.get("tun",{}).get("enable") is not True:
        raise TransactionError("candidate is not production-shaped")
    groups=[g for g in data.get("proxy-groups",[]) if isinstance(g,dict) and g.get("name")=="AWG-MIHOMO"]
    if len(groups)!=1 or groups[0].get("type")!="fallback":
        raise TransactionError("candidate lacks native fallback")
    proxy_names=groups[0].get("proxies")
    if not isinstance(proxy_names,list) or not 2<=len(proxy_names)<=4 or len(set(proxy_names))!=len(proxy_names):
        raise TransactionError("invalid candidate list")
    defined=[p.get("name") for p in data.get("proxies",[]) if isinstance(p,dict)]
    if sorted(defined)!=sorted(proxy_names):
        raise TransactionError("candidate members not explicit")
    return data


def require_preflight(root):
    if (root/"live"/"transport").read_text().strip()!="mihomo":
        raise TransactionError("test transport not Mihomo")
    if (root/"live"/"direct-state").read_text().strip()!="verified":
        raise TransactionError("fixture DIRECT preflight rejected")
    if (root/"live"/"route-state").read_text().strip()!="transit-safe":
        raise TransactionError("fixture guard is not safe")
    if (root/"live"/"service-state").read_text().strip()!="active":
        raise TransactionError("fixture Mihomo service not active")
    read_fixture_candidate(root)


def snapshot(root):
    backups=root/"backup"
    backups.mkdir(mode=0o700)
    entries={}
    for name in ITEMS:
        file=root/"live"/name
        if file.exists():
            data=file.read_bytes()
            atomic_bytes(backups/name,data)
            entries[name]={"present":True,"sha256":hash_file(backups/name)}
        else:
            entries[name]={"present":False}
    atomic_json(root/JOURNAL,{"version":1,"phase":"snapshot","entries":entries})


def restore(root):
    journal_path=root/JOURNAL
    if not journal_path.exists():
        return False
    journal=json.loads(journal_path.read_text())
    if journal.get("version")!=1 or set(journal.get("entries",{}))!=set(ITEMS):
        raise TransactionError("invalid recovery journal")
    backups=root/"backup"
    # Check the entire recovery set before mutating any live file.
    for name,meta in journal["entries"].items():
        if meta.get("present"):
            source=backups/name
            if not source.is_file() or source.is_symlink() or hash_file(source)!=meta.get("sha256"):
                raise TransactionError("backup integrity failed")
    for name,meta in journal["entries"].items():
        target=root/"live"/name
        if target.is_symlink():
            raise TransactionError("unsafe recovery target")
        if meta.get("present"):
            atomic_bytes(target,(backups/name).read_bytes())
        elif target.exists():
            target.unlink()
    for name,meta in journal["entries"].items():
        target=root/"live"/name
        if meta.get("present") and hash_file(target)!=meta["sha256"]:
            raise TransactionError("rollback verification failed")
        if not meta.get("present") and target.exists():
            raise TransactionError("rollback left a formerly absent file")
    shutil.rmtree(backups)
    journal_path.unlink()
    return True


def set_phase(root,phase):
    journal=json.loads((root/JOURNAL).read_text())
    journal["phase"]=phase
    atomic_json(root/JOURNAL,journal)


def apply(root,fail_after=None,crash_after=None):
    if (root/JOURNAL).exists() or (root/"backup").exists():
        raise TransactionError("unfinished transaction requires explicit recovery")
    require_preflight(root)
    try:
        snapshot(root)
        checkpoint(root,"snapshot",fail_after,crash_after)
        atomic_bytes(root/"live"/"route-state",b"lockdown\n")
        checkpoint(root,"quarantine",fail_after,crash_after)
        atomic_bytes(root/"live"/"config.yaml",(root/"candidate.yaml").read_bytes())
        atomic_bytes(root/"live"/"mode",b"native\n")
        checkpoint(root,"install",fail_after,crash_after)
        read_fixture_candidate(root)
        if (root/"live"/"mode").read_text().strip()!="native":
            raise TransactionError("candidate verification failed")
        atomic_bytes(root/"live"/"route-state",b"transit-safe\n")
        checkpoint(root,"verify",fail_after,crash_after)
        # Commit is last. Journal removal means no recovery is pending.
        (root/JOURNAL).unlink()
        shutil.rmtree(root/"backup")
    except Exception:
        restore(root)
        raise


def checkpoint(root,phase,fail_after,crash_after):
    set_phase(root,phase)
    if crash_after==phase:
        os._exit(42)
    if fail_after==phase:
        raise TransactionError("injected fault after "+phase)


def main():
    parser=argparse.ArgumentParser(description="Fixture only; cannot modify real Pi")
    parser.add_argument("--fixture-root",required=True)
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--apply",action="store_true")
    actions.add_argument("--recover",action="store_true")
    parser.add_argument("--fail-after",choices=PHASES)
    parser.add_argument("--crash-after",choices=PHASES)
    args=parser.parse_args()
    try:
        root=private_root(args.fixture_root)
        fd=os.open(root/"transaction.lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.apply:
                apply(root,args.fail_after,args.crash_after)
                print("STAGE31_FIXTURE_COMMIT=PASS")
            else:
                recovered=restore(root)
                print("STAGE31_FIXTURE_RECOVERY="+("PASS" if recovered else "NOT_REQUIRED"))
        finally:
            os.close(fd)
    except (OSError,ValueError,TransactionError,json.JSONDecodeError,yaml.YAMLError) as exc:
        # Do not disclose filesystem contents, configuration or credentials.
        print("STAGE31_FIXTURE_ERROR="+type(exc).__name__,file=sys.stderr)
        return 2
    return 0


if __name__=="__main__":
    raise SystemExit(main())
