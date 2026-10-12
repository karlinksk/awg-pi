#!/usr/bin/env python3
"""AWG stage15: credential-free, loopback-only decoded YouTube frame trial.

Must run as its OWN restricted DynamicUser systemd unit, NEVER from the
credential-bearing proxy unit. A real decoded frame is the only PASS.
No source configuration, provider node name, media URL, cookies or tokens
are read, printed or included in result. No production routing changes.
"""
from __future__ import annotations
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

THIS_DIR = Path(__file__).resolve().parent
FRAME = THIS_DIR / "awg-youtube-frame-check.py"
TRUSTED_RUNTIME = Path("/dev/shm/awg-stage15/bin/yt-dlp")


def preflight(*, euid=None, environ=None) -> str:
    user = os.geteuid() if euid is None else euid
    env = os.environ if environ is None else environ
    if user == 0:
        return "root_worker_forbidden"
    if env.get("CREDENTIALS_DIRECTORY"):
        return "service_credentials_forbidden"
    if not FRAME.is_file() or FRAME.is_symlink():
        return "media_checker_unavailable"
    if not TRUSTED_RUNTIME.is_file() or TRUSTED_RUNTIME.is_symlink():
        return "verified_media_runtime_unavailable"
    return ""


def load_frame():
    loader = importlib.machinery.SourceFileLoader("awg_stage15_media_frame", str(FRAME))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def summarize(port: int, *, euid=None, environ=None, frame=None) -> dict:
    # Never bypass privilege / credential preflight, including in tests.
    reason = preflight(euid=euid, environ=environ)
    if reason:
        return {"state":"UNKNOWN","reason":reason,
                "method":"video_frame_decode","shadow_only":True,
                "credentials_loaded":False,"production_modified":False}
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        reason="invalid_proxy_port"
    else:
        try:
            verifier=load_frame() if frame is None else frame
            observation=verifier.verify(port, executable=str(TRUSTED_RUNTIME))
            if (isinstance(observation,dict)
                    and observation.get("state")=="PASS"
                    and observation.get("reason")=="youtube_first_video_frame_decoded"
                    and observation.get("method")=="video_frame_decode"
                    and observation.get("shadow_only") is True):
                return {"state":"PASS","reason":"youtube_first_video_frame_decoded",
                        "method":"video_frame_decode","shadow_only":True,
                        "credentials_loaded":False,"production_modified":False}
            # Strict allowlist: no exception text, URL or media tokens in output.
            allowed={"invalid_proxy_port", "ytdlp_or_compatible_js_unavailable",
                     "ffmpeg_unavailable","youtube_extractor_or_media_unavailable",
                     "youtube_video_file_unverified","youtube_video_decode_unverified",
                     "youtube_media_probe_unavailable"}
            raw_reason=observation.get("reason") if isinstance(observation,dict) else None
            reason=raw_reason if raw_reason in allowed else "media_unverified"
        except Exception:
            reason="media_unverified"
    return {"state":"UNKNOWN","reason":reason,
            "method":"video_frame_decode","shadow_only":True,
            "credentials_loaded":False,"production_modified":False}


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--proxy-port",type=int,required=True)
    args=parser.parse_args()
    report=summarize(args.proxy_port)
    print(json.dumps(report,separators=(",",":"),sort_keys=True))
    return 0 if report["state"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
