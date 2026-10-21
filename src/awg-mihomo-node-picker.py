#!/usr/bin/env python3
"""Read-only unified picker for existing Mihomo and opt-in Xray profiles.

Xray eligible means fresh isolated OpenAI HTTPS, never a guaranteed live TUN.
Pool filtering and the selected node are NOT mutated. This helper is safe
to use only on the root-owned current live provider.
"""
import argparse
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import sys

RESULTS=Path("/usr/local/sbin/awg-mihomo-results-view")

def country_ok(row,region):
    return region!="europe" or row.get("country_code") in (
        "DE","NL","FI","EE","LV","SE","PL","FR","GB","CH","AT","BE",
        "CZ","DK","ES","IT","LT","LU","NO","PT","RO","SK","SI")

def protocol_ok(row,flt):
    proto=row.get("type")
    return flt=="all" or proto==flt or (flt=="ss" and proto=="shadowsocks")

def entries(rows,profiles,inventory,protocol="all",region="all"):
    view=load_view()
    rows=list(rows) if isinstance(rows,list) else []
    profiles=profiles if isinstance(profiles,list) else []
    inventory=inventory if isinstance(inventory,list) else []
    consistent=len(profiles)==len(inventory) and len(profiles)>0
    # Build one inventory from the current provider, not only from the last
    # Mihomo health scan. A freshly imported Reality node can be absent from
    # Mihomo scan output yet must be visible as UNTESTED (never READY).
    if consistent:
        current={(str(r.get("name")),str(r.get("type")),
                  str(r.get("server")),str(r.get("port")))
                 for r in rows if isinstance(r,dict)}
        for pos,(profile,proof) in enumerate(zip(profiles,inventory),1):
            if not isinstance(profile,dict) or not isinstance(proof,dict):
                continue
            if (proof.get("engine")!="XRAY" or proof.get("index")!=pos
                or proof.get("name")!=profile.get("name")):
                continue
            key=(str(profile.get("name")),str(profile.get("type")),
                 str(profile.get("server")),str(profile.get("port")))
            if key not in current:
                rows.append({"index":pos,"name":profile.get("name"),
                             "type":profile.get("type"),"server":profile.get("server"),
                             "port":profile.get("port"),"healthy":False})
                current.add(key)
    out=[]
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or not protocol_ok(row,protocol) or not country_ok(row,region):
            continue
        name=row.get("name")
        if not isinstance(name,str) or not name or name in seen or row.get("duplicate_name"):
            continue
        proof=view.find_xray_evidence(row,profiles,inventory) if consistent else None
        if proof is not None:
            # A provider label/IP country is not independent Xray exit-GeoIP proof.
            if region=="europe":continue
            # Network evidence is displayed, not assumed. Xray can be
            # selected only after a fresh independent NETWORK_OK proof.
            engine={"NETWORK_OK":"XRAY_HTTPS",
                    "NETWORK_FAIL":"XRAY_NETWORK_FAIL",
                    "UNKNOWN_HTTP":"XRAY_UNKNOWN_HTTP",
                    "UNKNOWN_ERROR":"XRAY_UNKNOWN_ERROR",
                    "UNAVAILABLE":"XRAY_UNAVAILABLE",
                    "UNTESTED":"XRAY_UNTESTED"}.get(proof,"XRAY_UNTESTED")
            latency="-"
        else:
            if row.get("healthy") is not True:continue
            # Fail shut on a mismatched non-Mihomo live engine.
            if consistent:
                matches=[x for x in inventory if x.get("name")==name]
                if len(matches)!=1 or matches[0].get("engine")!="MIHOMO":
                    continue
            engine="HEALTHY"
            latency=str(row.get("delay_ms"))+"ms" if isinstance(row.get("delay_ms"),int) else "-"
        endpoint=str(row.get("server",""))+":"+str(row.get("port",""))
        fields=(str(row.get("index","")),name,str(row.get("type","")),endpoint,
                "",engine,str(row.get("country_code") or "??"),latency)
        # TSV consumer cannot represent tabs/newlines. Skip malicious or
        # malformed provider names rather than corrupting selection UI.
        if any(any(c in field for c in ("\t","\r","\n")) for field in fields):continue
        out.append("\t".join(fields))
        seen.add(name)
    return out

def load_view():
    spec=importlib.util.spec_from_loader("awg_picker_evidence",
        SourceFileLoader("awg_picker_evidence",str(RESULTS)))
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

def main():
    p=argparse.ArgumentParser()
    p.add_argument("pool_json")
    p.add_argument("--target",choices=("live","candidate"),default="live")
    p.add_argument("--protocol",default="all")
    p.add_argument("--region",choices=("all","europe"),default="all")
    args=p.parse_args()
    rows=json.loads(Path(args.pool_json).read_text())
    view=load_view()
    profiles,inventory=(view.load_live() if args.target=="live" else ([],[]))
    for line in entries(rows,profiles,inventory,args.protocol,args.region):
        print(line)

if __name__=="__main__":
    main()
