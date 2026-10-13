#!/usr/bin/env python3
"""Expiring operator observation of actual logged-in ChatGPT reply via one node.
Never claims autonomous browser validation. Does not store browser credentials.
"""
from __future__ import annotations
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import stat
import tempfile
import time

PROOF = Path("/run/awg-pbr/mihomo-smart/browser-proof.json")
PROVIDER = Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
MAX_AGE = 1800
CLAIM = "operator_observed_authenticated_chat_reply"
class Reject(Exception):
    pass

def valid_name(name):
    return (isinstance(name,str) and 0 < len(name) <= 300
            and not any(ch in name for ch in ("\x00","\r","\n")))

def valid_egress(value):
    try:
        return str(ipaddress.IPv4Address(value)) if ipaddress.ip_address(value).is_global else ""
    except (ValueError, TypeError, ipaddress.AddressValueError):
        return ""

def secure_dir(directory, uid):
    if directory.is_symlink():
        raise Reject("UNTRUSTED_DIR")
    info=directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid!=uid
            or stat.S_IMODE(info.st_mode)!=0o700):
        raise Reject("UNTRUSTED_DIR")

def read_regular(path,uid=None,max_size=1_000_000):
    if path.is_symlink():
        raise Reject("SYMLINK")
    st=path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_size>max_size
            or (uid is not None and
                (st.st_uid!=uid or stat.S_IMODE(st.st_mode)!=0o600))):
        raise Reject("UNTRUSTED_FILE")
    f=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        fresh=os.fstat(f)
        if (st.st_dev,st.st_ino)!=(fresh.st_dev,fresh.st_ino):
            raise Reject("REPLACED_FILE")
        with os.fdopen(f,"rb") as stream:
            f=-1
            data=stream.read(max_size+1)
    finally:
        if f>=0: os.close(f)
    if len(data)>max_size:raise Reject("OVERSIZE")
    return data

def provider_digest(path):
    return hashlib.sha256(read_regular(path,max_size=2_000_000)).hexdigest()

def read_proof(file,uid):
    try:
        data=json.loads(read_regular(file,uid))
    except FileNotFoundError:
        return {}
    except (ValueError,UnicodeError):
        raise Reject("MALFORMED_PROOF")
    return data if isinstance(data,dict) else {}

def proof_state(data,name,source_sha,now,max_age=MAX_AGE,egress_ip=None):
    if not isinstance(data,dict) or data.get("version")!=1:
        return "UNKNOWN","MISSING_OR_UNSUPPORTED_PROOF"
    if data.get("provider_sha256")!=source_sha:
        return "UNKNOWN","PROVIDER_CHANGED"
    entries=data.get("entries")
    if not isinstance(entries,dict) or len(entries)>15:
        return "UNKNOWN","BAD_PROOF_ENTRIES"
    row=entries.get(name)
    if not isinstance(row,dict) or row.get("claim")!=CLAIM:
        return "UNKNOWN","NODE_NOT_ACCEPTED"
    at=row.get("observed_at")
    if type(at) is not int or at>now+15 or now-at>max_age:
        return "UNKNOWN","STALE_OR_FUTURE_PROOF"
    if at<0:
        return "UNKNOWN","BAD_PROOF_TIME"
    saved_ip=row.get("egress_ip")
    if not valid_egress(saved_ip):
        return "UNKNOWN","PROOF_MISSING_PUBLIC_EGRESS"
    if egress_ip is not None and saved_ip != valid_egress(egress_ip):
        return "UNKNOWN","EGRESS_CHANGED"
    return "PASS","RECENT_OPERATOR_BROWSER_ACCEPTANCE"

def record(file,provider,name,observed_at,now,uid,egress_ip):
    if not valid_name(name): raise Reject("INVALID_NAME")
    egress=valid_egress(egress_ip)
    if not egress: raise Reject("EGRESS_MUST_BE_PUBLIC_IPV4")
    if (type(observed_at) is not int or observed_at>now+15
            or now-observed_at>MAX_AGE):
        raise Reject("OUTSIDE_ACCEPTANCE_WINDOW")
    secure_dir(file.parent,uid)
    sha=provider_digest(provider)
    try:
        previous=read_proof(file,uid)
    except Reject:
        raise
    old=previous.get("entries",{}) if previous.get("provider_sha256")==sha else {}
    if not isinstance(old,dict): old={}
    rows={}
    for k,v in old.items():
        if not valid_name(k): continue
        state,_=proof_state({"version":1,"provider_sha256":sha,"entries":{k:v}},
                            k,sha,now)
        if state=="PASS":
            rows[k]=v
    rows[name]={"claim":CLAIM,"observed_at":observed_at,"egress_ip":egress}
    if len(rows)>15: raise Reject("TOO_MANY_ACCEPTED_NODES")
    payload=json.dumps({"version":1,"provider_sha256":sha,
                        "entries":rows},sort_keys=True,separators=(",",":")).encode()
    fd,tmp=tempfile.mkstemp(prefix=".browser-proof-",dir=file.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as stream:
            fd=-1
            stream.write(payload)
        os.replace(tmp,file)
    finally:
        if fd>=0:os.close(fd)
        if os.path.exists(tmp):os.unlink(tmp)
    return proof_state({"version":1,"provider_sha256":sha,"entries":rows},
                       name,sha,now)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("check","record","candidates"))
    p.add_argument("--node",default="")
    p.add_argument("--observed-at",type=int)
    p.add_argument("--egress-ip",default="")
    p.add_argument("--ack-user-test",action="store_true")
    p.add_argument("--fixture-root",default="")
    args=p.parse_args()
    if args.action!="candidates" and not valid_name(args.node):p.error("bad node name")
    if args.action=="record" and (args.observed_at is None or not args.ack_user_test or not valid_egress(args.egress_ip)):
        p.error("record requires --observed-at, --egress-ip and --ack-user-test")
    try:
        if args.fixture_root:
            root=Path(args.fixture_root).absolute()
            if (root.is_symlink() or root.parent!=Path("/tmp")
                    or not root.name.startswith("awg-browser-proof-")):
                raise Reject("UNSAFE_FIXTURE")
            uid=os.geteuid()
            secure_dir(root,uid)
            file,provider=root/"browser-proof.json",root/"subscription.yaml"
        else:
            if os.geteuid()!=0:raise Reject("ROOT_REQUIRED")
            uid=0
            file,provider=PROOF,PROVIDER
        now=int(time.time())
        if args.action=="candidates":
            secure_dir(file.parent,uid)
            sha=provider_digest(provider)
            data=read_proof(file,uid)
            rows=data.get("entries",{}) if data.get("provider_sha256")==sha else {}
            if not isinstance(rows,dict) or len(rows)>15:
                raise Reject("BAD_PROOF_ENTRIES")
            candidates=sorted(name for name in rows
                              if valid_name(name) and
                              proof_state(data,name,sha,now)[0]=="PASS")
            for name in candidates:
                print("BROWSER_CANDIDATE="+name)
            return 0
        if args.action=="record":
            state,reason=record(file,provider,args.node,args.observed_at,now,uid,args.egress_ip)
        else:
            secure_dir(file.parent,uid)
            sha=provider_digest(provider)
            state,reason=proof_state(read_proof(file,uid),args.node,sha,now,
                                     egress_ip=args.egress_ip or None)
    except (OSError,Reject,ValueError) as exc:
        state,reason="UNKNOWN",str(exc) if isinstance(exc,Reject) else type(exc).__name__
    print("BROWSER_PROOF="+state)
    print("BROWSER_REASON="+reason)
    return 0 if state=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
