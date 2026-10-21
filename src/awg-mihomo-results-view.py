#!/usr/bin/env python3
"""Engine-aware read-only Mihomo/Xray results for the TUI.

Xray NETWORK_OK means isolated OpenAI HTTPS only, never READY, TUN, or LAN.
Never changes selected nodes, DNS, services, routes, or provider state.
"""
import argparse
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import sys

UNIFIED=Path("/usr/local/sbin/awg-mihomo-unified-nodes")

def find_xray_evidence(node,profiles,inventory):
    """Match by unique name+protocol+endpoint; ignore display/sort index."""
    name=node.get("name")
    if not isinstance(name,str) or not name or node.get("duplicate_name"):
        return None
    # Cross-endpoint duplicate names remain ambiguous to the live selector.
    if sum(isinstance(p,dict) and p.get("name")==name for p in profiles)!=1:
        return None
    matches=[i for i,p in enumerate(profiles) if isinstance(p,dict)
        and p.get("name")==name and p.get("type")==node.get("type")
        and str(p.get("server"))==str(node.get("server"))
        and str(p.get("port"))==str(node.get("port"))]
    if len(matches)!=1 or matches[0]>=len(inventory):return None
    row=inventory[matches[0]]
    return (row.get("basic_network","UNTESTED")
        if row.get("engine")=="XRAY" and row.get("name")==name
            and row.get("index")==matches[0]+1 else None)

def state(row,evidence):
    # These are test results only; neither a positive Mihomo pool result nor
    # isolated Xray HTTPS establishes Pi TUN/LAN eligibility.
    if evidence is None:
        if row.get("type")=="vless":
            return "—","НЕ ПРОВ.","нет независимого Xray-подтверждения"
        healthy=row.get("healthy")
        status="ТЕСТ OK" if healthy is True else (
            "ТЕСТ FAIL" if healthy is False else "НЕ ПРОВ.")
        return "Mihomo",status,(
            "" if healthy is True else str(row.get("error") or row.get("geo_error") or ""))
    states={"NETWORK_OK":"HTTPS OK","NETWORK_FAIL":"HTTPS FAIL",
        "UNTESTED":"НЕ ПРОВ.","UNKNOWN_HTTP":"HTTP ?",
        "UNKNOWN_ERROR":"ОШИБКА","UNAVAILABLE":"НЕТ XRAY",
        "UNUSABLE_DUPLICATE_OR_MISSING_NAME":"ДУБЛИКАТ"}
    why=str(row.get("error") or "")
    return "Xray",states.get(evidence,"НЕ ПРОВ."),("Mihomo: "+why if why else "")

def display_name(value):
    value=str(value or "")
    head,sep,tail=value.partition(" ")
    return tail if sep and head and not any(c.isalnum() for c in head) else value

def protocol_label(node):
    """Human-facing protocol name; never change the provider's real type."""
    kind=str(node.get("type") or "").lower() if isinstance(node,dict) else ""
    if kind=="hysteria2":return "HY2"
    if kind=="shadowsocks":return "SS"
    if kind=="vless":
        network=str(node.get("network") or "").lower()
        return ("VLESS/xHTTP" if network=="xhttp" else
                "VLESS/gRPC" if network=="grpc" else "VLESS")
    return {"vmess":"VMess","trojan":"Trojan"}.get(kind,kind.upper() or "—")

def clip(value,width):
    s=str(value or "")
    return s if len(s)<=width else s[:width-1]+"…"

def render(rows,profiles=None,inventory=None,target="live"):
    profiles=profiles if isinstance(profiles,list) else []
    inventory=inventory if isinstance(inventory,list) else []
    active=target=="live" and len(profiles)==len(inventory) and bool(profiles)
    result=[
      "Сервер = адрес подключения, не публичный IP выхода. RTT = задержка теста, не ICMP ping.",
      "Статус HTTPS у Xray = изолированный прокси-тест; НЕ READY / TUN / LAN.",
      "",
      f"{'№':>3}  {'Узел':<20} {'Движок':<7} {'Протокол':<12} {'Сервер':<26} {'RTT':>7} {'Статус':<11}",
      "-"*105]
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict):continue
        evidence=find_xray_evidence(row,profiles,inventory) if active else None
        engine,health,why=state(row,evidence)
        latency=(str(row.get("delay_ms"))+"мс" if engine=="Mihomo"
          and isinstance(row.get("delay_ms"),int) else "—")
        # Prefer the exact current provider record for VLESS transport labels.
        matches=[p for p in profiles if isinstance(p,dict) and
            p.get("name")==row.get("name") and p.get("type")==row.get("type") and
            str(p.get("server"))==str(row.get("server")) and
            str(p.get("port"))==str(row.get("port"))]
        proto=protocol_label(matches[0] if active and len(matches)==1 else row)
        endpoint=str(row.get("server",""))+":"+str(row.get("port",""))
        result.append(f"{i:>3}  {clip(display_name(row.get('name')),20):<20} "
          f"{engine:<7} {clip(proto,12):<12} "
          f"{clip(endpoint,26):<26} {latency:>7} {health:<11}")
        if why:result.append("     Причина теста: "+clip(why,92))
    if not active and any(isinstance(p,dict) and p.get("type")=="vless" for p in rows):
        result.append("Xray: данных текущего профиля нет; показаны результаты Mihomo.")
    return "\n".join(result)+"\n"

def load_live():
    if os.geteuid()!=0 or not UNIFIED.is_file() or UNIFIED.is_symlink():
        return [],[]
    spec=importlib.util.spec_from_loader("awg_ui_unified",
      SourceFileLoader("awg_ui_unified",str(UNIFIED)))
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    adapter=mod.load_adapter()
    nodes,_,pool,cache=mod.snapshots(adapter)
    return nodes,mod.inventory(nodes,pool,cache,adapter)

def main():
    a=argparse.ArgumentParser()
    a.add_argument("pool_json")
    a.add_argument("--target",choices=("live","candidate"),default="live")
    opts=a.parse_args()
    rows=json.loads(Path(opts.pool_json).read_text(encoding="utf-8"))
    if not isinstance(rows,list):raise SystemExit("Invalid list format")
    profiles,inventory=[],[]
    if opts.target=="live":
        try:profiles,inventory=load_live()
        except (OSError,ValueError,RuntimeError,SystemExit,ImportError,KeyError):
            # Fail visibly as Mihomo-only, never forge Xray success.
            pass
    sys.stdout.write(render(rows,profiles,inventory,opts.target))

if __name__=="__main__":
    main()
