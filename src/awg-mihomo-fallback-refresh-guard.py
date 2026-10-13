#!/usr/bin/env python3
"""Read-only native fallback refresh gate and direct-route audit.

Exit 0 = legacy; exit 10 = native fallback requiring staged manual review;
exit 20 = unknown/unsafe, also staged manual review.
Never prints provider secrets or mutates any state.
"""
import argparse
import ipaddress
from pathlib import Path
import subprocess
import sys

import yaml


def classify(config):
    """Returns native, legacy or unknown. Parsing errors fail closed."""
    try:
        data=yaml.safe_load(Path(config).read_text(encoding="utf-8"))
        if not isinstance(data,dict):return "unknown"
        groups=data.get("proxy-groups")
        if not isinstance(groups,list):return "unknown"
        matches=[g for g in groups if isinstance(g,dict) and g.get("name")=="AWG-MIHOMO"]
        if len(matches)!=1:return "unknown"
        typ=matches[0].get("type")
        if typ=="fallback":return "native"
        if typ=="select":return "legacy"
        return "unknown"
    except Exception:
        return "unknown"


def audit(config,iface,gateway,runner=subprocess.run):
    if classify(config)!="native":
        raise ValueError("not a native fallback")
    data=yaml.safe_load(Path(config).read_text(encoding="utf-8"))
    group=next(g for g in data["proxy-groups"] if isinstance(g,dict) and g.get("name")=="AWG-MIHOMO")
    names=group.get("proxies")
    proxies=data.get("proxies")
    if not isinstance(names,list) or not (2<=len(names)<=4) or len(names)!=len(set(names)):
        raise ValueError("invalid explicit fallback member list")
    if not isinstance(proxies,list) or len(proxies)!=len(names):
        raise ValueError("fallback must contain exactly its explicit members")
    by_name={p.get("name"):p for p in proxies if isinstance(p,dict)}
    if set(names)!=set(by_name):
        raise ValueError("fallback member mismatch")
    import importlib.util
    path=Path(__file__).with_name("awg-mihomo-fallback-preview.py")
    spec=importlib.util.spec_from_file_location("awg_fallback_preview",path)
    preview=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)
    nodes=preview.choose_nodes({"proxies":proxies},names)
    preview.check_routes(nodes,iface,gateway,runner=runner)
    return names


def decide(config, modefile):
    marker=Path(modefile)
    try:
        has_marker=marker.exists()
    except OSError:
        return "unknown"
    if has_marker:
        try:
            value=marker.read_text(encoding="utf-8").strip()
        except OSError:
            return "unknown"
        if value not in ("native", "legacy"):
            return "unknown"
        if value=="native":return "native"
        # Even explicit legacy marker cannot overrule detected native config
    kind=classify(config)
    if has_marker and value=="legacy" and kind=="unknown":
        return "legacy"
    return kind


def monitor_state(config, modefile, iface, gateway, runner=subprocess.run):
    # Native mode is only safe when the marker and actual running TUN config agree.
    mode = decide(config, modefile)
    if mode == "legacy":
        return "LEGACY" if classify(config) == "legacy" else "NATIVE_UNSAFE"
    if mode != "native" or classify(config) != "native":
        return "NATIVE_UNSAFE"
    try:
        data = yaml.safe_load(Path(config).read_text(encoding="utf-8"))
        tun = data.get("tun")
        if not isinstance(tun, dict) or tun.get("enable") is not True:
            return "NATIVE_UNSAFE"
        ipaddress.IPv4Address(gateway)
        if not iface or not isinstance(iface, str):
            return "NATIVE_UNSAFE"
        audit(config, iface, gateway, runner=runner)
    except Exception:
        return "NATIVE_UNSAFE"
    return "NATIVE_OK"


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--config",required=True)
    p.add_argument("--mode-file",required=True)
    p.add_argument("--audit-direct",action="store_true")
    p.add_argument("--monitor-check",action="store_true")
    p.add_argument("--iface")
    p.add_argument("--gateway")
    a=p.parse_args()
    if a.monitor_check:
        state=monitor_state(a.config,a.mode_file,a.iface,a.gateway)
        print("MONITOR_FALLBACK="+state)
        return 0 if state != "NATIVE_UNSAFE" else 20
    state=decide(a.config,a.mode_file)
    if state=="legacy":
        print("FALLBACK_REFRESH_GATE=LEGACY")
        return 0
    if state=="unknown":
        print("FALLBACK_REFRESH_GATE=UNKNOWN_STAGE_ONLY")
        return 20
    if a.audit_direct:
        if not a.iface or not a.gateway:
            print("FALLBACK_REFRESH_GATE=INVALID_AUDIT_INPUT")
            return 20
        try:
            ipaddress.IPv4Address(a.gateway)
            names=audit(a.config,a.iface,a.gateway)
        except (ValueError,OSError,subprocess.TimeoutExpired,yaml.YAMLError):
            print("FALLBACK_REFRESH_GATE=UNSAFE_DIRECT_STAGE_ONLY")
            return 20
        print(f"FALLBACK_REFRESH_GATE=NATIVE_DIRECT_PASS nodes={len(names)}")
    else:
        print("FALLBACK_REFRESH_GATE=NATIVE_STAGE_ONLY")
    return 10


if __name__=="__main__":
    sys.exit(main())
