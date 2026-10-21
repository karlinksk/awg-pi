#!/usr/bin/env python3
"""Strictly opt-in Mihomo->local SOCKS5->Xray VLESS bridge.

Consumes the EXISTING root-owned Mihomo provider (HoneyVPN and others).
No subscription fetching, no routes, no TUN, no node changes and no secrets
in stdout. A missing, changed or unsupported node fails closed on service start.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import stat
import sys
import tempfile
import uuid
import yaml

PROVIDER = Path(os.environ.get("AWG_XRAY_PROVIDER",
  "/var/lib/awg-pbr/mihomo/providers/subscription.yaml"))
SELECTED = Path(os.environ.get("AWG_XRAY_SELECTED",
  "/var/lib/awg-pbr/xray-vless/selected.json"))
RUNTIME = Path(os.environ.get("AWG_XRAY_RUNTIME",
  "/run/awg-pbr/xray-vless/config.json"))
LAN_ENV = Path(os.environ.get("AWG_XRAY_LAN_ENV", "/etc/awg-pbr/env"))
PORT = int(os.environ.get("AWG_XRAY_LOCAL_PORT","17892"))
LOOPBACK = "127.0.0.1"
MAX_PROVIDER_BYTES = 8 * 1024 * 1024
FINGERPRINTS = {"chrome","firefox","safari","ios","edge","random","randomized"}
XHTTP_MODES = {"auto","stream-one","stream-up","packet-up"}

def die(message, code=2):
    print("XRAY_VLESS_ERROR="+message, file=sys.stderr)
    raise SystemExit(code)

def secure_read(path, *, max_bytes=MAX_PROVIDER_BYTES):
    try:
        fd=os.open(path,os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (os.geteuid()==0 and info.st_uid!=0):
                die("UNTRUSTED_FILE")
            if info.st_size>max_bytes:die("FILE_TOO_LARGE")
            with os.fdopen(os.dup(fd),"rb") as f:return f.read(max_bytes+1)
        finally:os.close(fd)
    except (OSError,ValueError):die("SOURCE_UNAVAILABLE")

def sha_profile(p):
    canonical=json.dumps({k:v for k,v in p.items() if k!="name"},
                         sort_keys=True,ensure_ascii=False,separators=(",",":"))
    return hashlib.sha256(canonical.encode()).hexdigest()

def read_provider():
    try:
        doc=yaml.safe_load(secure_read(PROVIDER))
    except (yaml.YAMLError,UnicodeError):die("INVALID_PROVIDER")
    proxies=doc.get("proxies") if isinstance(doc,dict) else None
    if not isinstance(proxies,list) or len(proxies)>10000:die("INVALID_PROVIDER")
    return proxies

def validate(node):
    if not isinstance(node,dict) or node.get("type")!="vless":
        die("VLESS_ONLY")
    if node.get("network") not in ("xhttp","grpc"):die("UNSUPPORTED_NETWORK")
    if node.get("tls") is not True or node.get("skip-cert-verify") is True:
        die("VERIFIED_TLS_REQUIRED")
    address=node.get("server")
    if not isinstance(address,str) or not 1<=len(address)<=253:
        die("INVALID_ENDPOINT")
    try: ipaddress.IPv4Address(address)
    except ValueError:
        # Conservative hostname validation; no user-supplied URL schemes or IPv6.
        if not re.fullmatch(r"(?i)(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?",address):
            die("INVALID_ENDPOINT")
    port=node.get("port")
    if type(port)!=int or not 1<=port<=65535:die("INVALID_PORT")
    try: node_uuid=str(uuid.UUID(str(node.get("uuid",""))))
    except ValueError:die("INVALID_UUID")
    if not isinstance(node.get("servername"),str) or not node["servername"] or len(node["servername"])>253:
        die("SNI_REQUIRED")
    reality=node.get("reality-opts")
    fp=node.get("client-fingerprint","chrome")
    if fp not in FINGERPRINTS:die("INVALID_FINGERPRINT")
    if node.get("flow") not in (None,"","xtls-rprx-vision"):
        die("UNSUPPORTED_FLOW")
    if isinstance(reality,dict):
        # Preserve original pinned REALITY behaviour for XHTTP/gRPC.
        pbk=reality.get("public-key")
        if not isinstance(pbk,str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,64}",pbk):
            die("INVALID_PUBLIC_KEY")
        sid=reality.get("short-id","")
        if not isinstance(sid,str) or not re.fullmatch(r"[0-9a-fA-F]{0,16}",sid):
            die("INVALID_SHORT_ID")
        stream={
          "network":node["network"],"security":"reality",
          "realitySettings":{
            "fingerprint":fp,"serverName":node["servername"],
            "publicKey":pbk,"shortId":sid,"spiderX":"/"}}
    elif ("reality-opts" not in node and node["network"]=="grpc"):
        # Ordinary VLESS TLS/gRPC from the SAME provider. Do not accept
        # insecure TLS, REALITY-like malformed metadata or XHTTP without
        # REALITY. Standard gRPC requires HTTP/2 ALPN.
        if node.get("flow") not in (None,""):die("TLS_GRPC_FLOW_UNSUPPORTED")
        alpn=node.get("alpn",["h2"])
        if not isinstance(alpn,list) or "h2" not in alpn or any(
            a not in ("h2","http/1.1") for a in alpn):
            die("TLS_GRPC_ALPN_REQUIRED")
        stream={"network":"grpc","security":"tls",
                "tlsSettings":{"serverName":node["servername"],
                               "allowInsecure":False,"alpn":alpn}}
    else:
        die("REALITY_REQUIRED")
    if node["network"]=="xhttp":
        opts=node.get("xhttp-opts")
        if not isinstance(opts,dict) or not isinstance(opts.get("path"),str) or not opts["path"].startswith("/"):
            die("XHTTP_PATH_REQUIRED")
        mode=opts.get("mode","auto")
        if mode not in XHTTP_MODES:die("INVALID_XHTTP_MODE")
        xhttp={"path":opts["path"],"mode":mode}
        if opts.get("host"):xhttp["host"]=opts["host"]
        stream["xhttpSettings"]=xhttp
    else:
        opts=node.get("grpc-opts",{})
        if not isinstance(opts,dict):die("INVALID_GRPC")
        service=opts.get("grpc-service-name")
        if not isinstance(service,str) or not service or len(service)>256:die("GRPC_SERVICE_REQUIRED")
        stream["grpcSettings"]={"serviceName":service,"multiMode":False}
    return node_uuid,stream

def interface():
    try: content=secure_read(LAN_ENV,max_bytes=15000).decode()
    except Exception:die("LAN_ENV_UNAVAILABLE")
    m=re.search(r"(?m)^LAN_IF=(['\"]?)([a-zA-Z0-9_.-]{1,15})\1$",content)
    if not m:die("LAN_INTERFACE_UNCONFIGURED")
    iface=m.group(2)
    if not (Path("/sys/class/net")/iface).exists():
        die("LAN_INTERFACE_MISSING")
    return iface

def atomic_json(path,body):
    parent=path.parent
    parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if parent.is_symlink() or (os.geteuid()==0 and parent.stat().st_uid!=0):
        die("UNTRUSTED_DESTINATION")
    fd,name=tempfile.mkstemp(prefix=".xray-",dir=parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(body,f,ensure_ascii=False,sort_keys=True)
            f.write("\n");f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def selected_profile(proxies):
    try: d=json.loads(secure_read(SELECTED,max_bytes=2048))
    except (ValueError,UnicodeDecodeError):die("INVALID_SELECTION")
    digest=d.get("sha256") if isinstance(d,dict) else None
    if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
        die("INVALID_SELECTION")
    found=[p for p in proxies if isinstance(p,dict) and sha_profile(p)==digest]
    if len(found)!=1:die("SELECTED_PROFILE_CHANGED_OR_MISSING")
    return found[0]

def status():
    print("XRAY_VLESS_ADAPTER=OPTIONAL")
    print("XRAY_VLESS_SELECTION="+("PRESENT" if SELECTED.is_file() else "NONE"))
    print("XRAY_VLESS_RUNTIME="+("PREPARED" if RUNTIME.is_file() else "ABSENT"))
    print("XRAY_VLESS_SOURCE="+("PRESENT" if PROVIDER.is_file() else "NONE"))
    print("XRAY_VLESS_LISTEN=127.0.0.1:"+str(PORT))
    print("XRAY_VLESS_DEFAULT=DISABLED")
    if SELECTED.is_file() and PROVIDER.is_file():
        proxies=read_provider()
        chosen=selected_profile(proxies)
        print("XRAY_VLESS_SELECTED_PROTOCOL="+chosen["network"])
        print("XRAY_VLESS_SELECTED_ID="+sha_profile(chosen)[:12])

def run():
    parser=argparse.ArgumentParser(description="Opt-in Xray VLESS bridge (no routes or secrets in status)")
    parser.add_argument("action",choices=("list","select","render","status"))
    parser.add_argument("value",nargs="?")
    a=parser.parse_args()
    if a.action=="status":status();return
    if os.geteuid()!=0:die("ROOT_REQUIRED")
    if not 1024<=PORT<=65535:die("INVALID_LOCAL_PORT")
    profiles=read_provider()
    if a.action=="list":
        for i,p in enumerate(profiles,1):
            if isinstance(p,dict) and p.get("type")=="vless":
                print(f"XRAY_VLESS_CANDIDATE={i} NETWORK={p.get('network','UNKNOWN')}")
        return
    if a.action=="select":
        # Do not re-point identity while a real Xray sidecar still uses the
        # previous credentials. Stop the unit first, then select and restart.
        if subprocess.run(["systemctl","is-active","--quiet","awg-xray-vless.service"],
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
            die("SERVICE_RUNNING_STOP_FIRST")
        if not a.value or not a.value.isdecimal():die("INDEX_REQUIRED")
        ix=int(a.value)
        if not 1<=ix<=len(profiles):die("INVALID_INDEX")
        chosen=profiles[ix-1]
        validate(chosen)
        atomic_json(SELECTED,{"version":1,"sha256":sha_profile(chosen)})
        print("XRAY_VLESS_SELECTED=STAGED_ONLY")
        print("XRAY_VLESS_INDEX="+str(ix))
        print("XRAY_VLESS_SERVICE_NOT_STARTED=YES")
        return
    if a.action=="render":
        if a.value:die("UNEXPECTED_ARGUMENT")
        chosen=selected_profile(profiles)
        node_uuid,stream=validate(chosen)
        stream["sockopt"]={"interface":interface(),"domainStrategy":"UseIPv4"}
        config={
          "log":{"loglevel":"warning"},
          "inbounds":[{"tag":"mihomo-loopback","listen":LOOPBACK,"port":PORT,
                       "protocol":"socks","settings":{"auth":"noauth","udp":False}}],
          "outbounds":[{"tag":"vless","protocol":"vless",
                        "settings":{"vnext":[{"address":chosen["server"],"port":chosen["port"],
                                              "users":[{"id":node_uuid,"encryption":"none",
                                                        **({"flow":chosen["flow"]} if chosen.get("flow") else {})}]}]},
                        "streamSettings":stream}],
          "routing":{"domainStrategy":"AsIs","rules":[{"type":"field","inboundTag":["mihomo-loopback"],
                                                        "outboundTag":"vless"}]}
        }
        atomic_json(RUNTIME,config)
        print("XRAY_VLESS_RUNTIME=PREPARED")
        print("XRAY_VLESS_BIND=127.0.0.1")
        print("XRAY_VLESS_TRANSPORT="+chosen["network"])
        print("XRAY_VLESS_ROUTE_CHANGE=NO")

if __name__=="__main__":run()
