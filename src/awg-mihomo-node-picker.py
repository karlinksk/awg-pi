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
    """Display every current provider profile; never equate visibility to eligibility.

    Live pool proof is matched to the exact provider index/name/endpoint and
    scoped to the provider SHA by the upstream unified snapshot.
    """
    view=load_view()
    rows=list(rows) if isinstance(rows,list) else []
    profiles=profiles if isinstance(profiles,list) else []
    inventory=inventory if isinstance(inventory,list) else []
    consistent=len(profiles)==len(inventory) and bool(profiles)
    if not consistent:
        # Candidate/import without live unified evidence: fail closed.
        return legacy_entries(rows,protocol,region)
    indexed={}
    for r in rows:
        if not isinstance(r,dict):continue
        ix=r.get("index")
        if type(ix)==int and ix>0:
            indexed[ix]=r
    seen_names={}
    for profile in profiles:
        if isinstance(profile,dict):
            n=profile.get("name")
            if isinstance(n,str):seen_names[n]=seen_names.get(n,0)+1
    output=[]
    for pos,(profile,proof) in enumerate(zip(profiles,inventory),1):
        if not isinstance(profile,dict) or not isinstance(proof,dict):continue
        if proof.get("index")!=pos or proof.get("name")!=profile.get("name"):
            continue
        name=profile.get("name")
        if not isinstance(name,str) or not name:continue
        row=indexed.get(pos,{})
        matched=(row.get("name")==name and row.get("type")==profile.get("type")
            and str(row.get("server"))==str(profile.get("server"))
            and str(row.get("port"))==str(profile.get("port")))
        check=row if matched else {}
        engine=proof.get("engine")
        if engine=="XRAY":
            # A country in the node label/server IP is NOT verified exit GeoIP.
            if region=="europe":continue
            h={"NETWORK_OK":"XRAY_HTTPS","NETWORK_FAIL":"XRAY_NETWORK_FAIL",
               "UNKNOWN_HTTP":"XRAY_UNKNOWN_HTTP","UNKNOWN_ERROR":"XRAY_UNKNOWN_ERROR",
               "UNAVAILABLE":"XRAY_UNAVAILABLE","UNTESTED":"XRAY_UNTESTED"}.get(
                   proof.get("basic_network"),"XRAY_UNTESTED")
            delay="-";country="??"
        elif engine=="MIHOMO":
            h=("MIHOMO_OK" if matched and check.get("healthy") is True
               else "MIHOMO_FAIL" if matched and check.get("healthy") is False
               else "MIHOMO_UNTESTED")
            delay=(str(check.get("delay_ms"))+"ms"
                   if matched and isinstance(check.get("delay_ms"),int) else "-")
            country=check.get("country_code") if matched else "??"
            if not country_ok({"country_code":country},region):continue
        else:
            h="UNSUPPORTED";delay="-";country="??"
            if region=="europe":continue
        if not protocol_ok(profile,protocol):continue
        if seen_names.get(name)!=1:
            h="DUPLICATE"
        fields=(str(pos),name,str(profile.get("type","")),
                str(profile.get("server",""))+":"+str(profile.get("port","")),
                "DUPLICATE" if h=="DUPLICATE" else "",h,
                str(country or "??"),delay)
        if any(any(c in field for c in ("\t","\r","\n")) for field in fields):
            continue
        output.append("\t".join(fields))
    return output

def legacy_entries(rows,protocol="all",region="all"):
    """Unconfirmed candidate: show inventory but never represent it as READY."""
    output=[]
    for row in rows:
        if not isinstance(row,dict) or not protocol_ok(row,protocol) or not country_ok(row,region):
            continue
        name=row.get("name")
        if not isinstance(name,str) or not name:continue
        fields=(str(row.get("index","")),name,str(row.get("type","")),
                str(row.get("server",""))+":"+str(row.get("port","")),
                "DUPLICATE" if row.get("duplicate_name") else "",
                ("MIHOMO_OK" if row.get("healthy") is True else
                 "MIHOMO_FAIL" if row.get("healthy") is False else
                 "MIHOMO_UNTESTED"),"??","-")
        if any(any(c in field for c in ("\t","\r","\n")) for field in fields):
            continue
        output.append("\t".join(fields))
    return output

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
