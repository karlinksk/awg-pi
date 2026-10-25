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
import subprocess

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

def classify_ytdlp_error(raw: str) -> str:
    """Return only an allowlisted error family; never expose diagnostic text."""
    text = (raw or "").casefold()[-12000:]
    if any(x in text for x in ("sign in to confirm", "confirm you.re not a bot",
                               "cookies are required", "login required")):
        return "YOUTUBE_BOT_OR_LOGIN"
    if "requested format is not available" in text or "no video formats found" in text:
        return "YOUTUBE_FORMAT_UNAVAILABLE"
    for code in ("403", "429", "451", "404"):
        if ("http error " + code) in text or ("http_error_" + code) in text:
            return "HTTP_" + code
    if "video unavailable" in text or "this video is unavailable" in text:
        return "YOUTUBE_VIDEO_UNAVAILABLE"
    if any(x in text for x in ("ejs", "remote component", "challenge solving",
                               "javascript runtime", "github")):
        return "EJS_COMPONENT_OR_CHALLENGE"
    if any(x in text for x in ("timed out", "timeout", "time out")):
        return "NETWORK_TIMEOUT"
    if any(x in text for x in ("proxyerror", "proxy error", "connection refused",
                               "connection reset", "unable to connect")):
        return "NETWORK_OR_PROXY_CONNECT"
    if any(x in text for x in ("certificate verify", "ssl error", "tls error")):
        return "TLS_VERIFICATION"
    if any(x in text for x in ("name or service not known", "temporary failure in name resolution",
                               "getaddrinfo failed")):
        return "DNS_RESOLUTION"
    if "unable to download webpage" in text or "unable to download api" in text:
        return "YOUTUBE_WEB_FETCH"
    if any(x in text for x in ("unable to download video data",
                               "unable to download fragment", "fragment not found")):
        return "YOUTUBE_MEDIA_DOWNLOAD"
    return "UNCLASSIFIED"


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
        base_loader = mod.load_video_decode_code
        def video_loader():
            video_module = base_loader()
            if video_module is None:
                return None
            class DiagnosisVideo:
                @staticmethod
                def decode_24_frames(proxy_port: int):
                    def observed_runner(argv, **kwargs):
                        outcome = subprocess.run(argv, **kwargs)
                        if argv and Path(str(argv[0])).name == "yt-dlp":
                            print("SERVICE_DIAG_YTDLP_RC=" + str(outcome.returncode), flush=True)
                            if outcome.returncode != 0:
                                print("SERVICE_DIAG_YTDLP_FAILURE_FAMILY=" +
                                      classify_ytdlp_error(outcome.stderr), flush=True)
                        return outcome
                    return video_module.decode_24_frames(proxy_port, runner=observed_runner)
            return DiagnosisVideo
        mod.load_video_decode_code = video_loader
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