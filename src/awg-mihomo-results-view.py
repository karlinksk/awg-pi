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
    if evidence is None:
        healthy=row.get("healthy") is True
        return "Mihomo","работает" if healthy else "недоступен",(
            "" if healthy else str(row.get("error") or row.get("geo_error") or ""))
    states={"NETWORK_OK":"HTTPS OK","NETWORK_FAIL":"сеть ошибка",
        "UNTESTED":"не проверен","UNKNOWN_HTTP":"HTTP ?",
        "UNKNOWN_ERROR":"ошибка теста","UNAVAILABLE":"нет Xray",
        "UNUSABLE_DUPLICATE_OR_MISSING_NAME":"не выбран"}
    why=str(row.get("error") or "")
    return "Xray",states.get(evidence,"не проверен"),("Mihomo: "+why if why else "")

def display_name(value):
    value=str(value or "")
    head,sep,tail=value.partition(" ")
    return tail if sep and head and not any(c.isalnum() for c in head) else value

def clip(value,width):
    s=str(value or "")
    return s if len(s)<=width else s[:width-1]+"…"

def render(rows,profiles=None,inventory=None,target="live"):
    profiles=profiles if isinstance(profiles,list) else []
    inventory=inventory if isinstance(inventory,list) else []
    active=target=="live" and len(profiles)==len(inventory) and bool(profiles)
    result=[
      "Xray: базовая HTTPS-проверка OpenAI, НЕ READY / TUN / LAN.",
      "Задержка Xray здесь не измерялась; результат Mihomo — отдельно.",
      "",
      f"{'№':>3}  {'Узел':<19} {'Протокол':<9} {'Движок':<7} {'Сервер':<26} {'Состояние':<13} {'Страна':<6} {'Задержка':>8}",
      "-"*105]
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict):continue
        evidence=find_xray_evidence(row,profiles,inventory) if active else None
        engine,health,why=state(row,evidence)
        latency=(str(row.get("delay_ms"))+" мс" if engine=="Mihomo"
          and isinstance(row.get("delay_ms"),int) else "—")
        result.append(f"{i:>3}  {clip(display_name(row.get('name')),19):<19} "
          f"{clip(row.get('type'),9):<9} {engine:<7} "
          f"{clip(str(row.get('server',''))+':'+str(row.get('port','')),26):<26} "
          f"{health:<13} {clip(row.get('country_code') or '—',6):<6} {latency:>8}")
        if why:result.append("     Причина: "+clip(why,92))
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
