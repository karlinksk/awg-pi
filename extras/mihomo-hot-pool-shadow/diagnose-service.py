#!/usr/bin/env python3
"""Non-mutating single-node Mihomo service diagnostic.

Imports the existing isolated service-scan implementation and records only
allowlisted status/reason codes. Never prints raw URLs, subscriptions, errors,
credentials, video bytes, cookies, or web response bodies.
"""
from __future__ import annotations
import argparse
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import re
import sys

SOURCE = Path("/usr/local/sbin/awg-mihomo-smart")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
TOKEN = re.compile(r"^[A-Za-z0-9_]{1,96}$")

def safe_token(raw: object) -> str:
    return raw if isinstance(raw, str) and TOKEN.fullmatch(raw) else "UNKNOWN"

def explain(result: dict) -> None:
    checks = result.get("checks") if isinstance(result, dict) else None
    for key in ("openai_api", "chatgpt_web", "youtube_video"):
        value = checks.get(key, {}) if isinstance(checks, dict) else {}
        print("SERVICE_DIAG_REASON_" + key.upper() + "=" +
              safe_token(value.get("reason")), flush=True)

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--node", required=True)
    args = p.parse_args()
    if not NAME.fullmatch(args.node):
        print("SERVICE_DIAG_ERROR=INVALID_NODE_NAME", file=sys.stderr)
        return 2
    if os.geteuid() != 0:
        print("SERVICE_DIAG_ERROR=REQUIRES_ROOT", file=sys.stderr)
        return 2
    try:
        loader = importlib.machinery.SourceFileLoader("awg_service_diag_source", str(SOURCE))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        loader.exec_module(mod)
        original = mod.assess_services_with_stage18
        def interceptor(*items, **keywords):
            result = original(*items, **keywords)
            explain(result)
            return result
        mod.assess_services_with_stage18 = interceptor
        print("SERVICE_DIAG_MODE=ISOLATED_SHADOW_ONLY", flush=True)
        return mod.service_scan(argparse.Namespace(node=args.node))
    except Exception:
        # Do not disclose raw exception text: it may contain provider secrets.
        print("SERVICE_DIAG_ERROR=SCANNER_ABORTED", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())