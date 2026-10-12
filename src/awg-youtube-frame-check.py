#!/usr/bin/env python3
"""EXPERIMENTAL short, real decoded YouTube-frame check through one Mihomo proxy.

Staging ONLY. NOT installed/enabled and never a fallback for the service gate
unless explicitly wired after isolated real-world validation.

- Fixed public video ID, no browser cookies, no account credentials.
- The yt-dlp downloader is forced through 127.0.0.1:<port>; no direct fallback.
- --test downloads only a short initial sample; output confined to /dev/shm.
- A successful extractor request or HTTP 206 alone is NOT PASS: a real frame
  must be decoded by local ffmpeg from the bounded temporary media file.
- If Node >=22, yt-dlp, or ffmpeg is absent -> UNKNOWN, not blocked YouTube.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tempfile
from typing import Callable

VIDEO_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
MAX_FILE = 2 * 1024 * 1024
MAX_SECONDS = 40
MEM_DIR = Path("/dev/shm")
MEDIA_EXTENSIONS = {".mp4", ".webm", ".mkv", ".ts"}


def result(state: str, reason: str) -> dict:
    return {"state": state, "reason": reason, "method": "video_frame_decode",
            "shadow_only": True}


def restricted_env() -> dict:
    env = dict(os.environ)
    for key in list(env):
        if key.lower() in ("http_proxy", "https_proxy", "all_proxy",
                           "no_proxy", "ftp_proxy"):
            env.pop(key, None)
    env["HOME"] = "/dev/shm"
    env["XDG_CACHE_HOME"] = "/dev/shm"
    env["TMPDIR"] = "/dev/shm"
    return env


def limited_child() -> None:
    """Kernel limits inherited by yt-dlp and helper processes."""
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE, MAX_FILE))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))


def ready(exe: str, *, version_runner=subprocess.run) -> bool:
    if not (Path(exe).is_file() and os.access(exe, os.R_OK)):
        return False
    node = shutil.which("node")
    if not node:
        return False
    try:
        p = version_runner([node, "--version"], capture_output=True,
                           text=True, timeout=2, check=False)
        match = re.fullmatch(r"v(\d+)\.\d+\.\d+", p.stdout.strip())
        return bool(p.returncode == 0 and match and int(match.group(1)) >= 22)
    except (OSError, subprocess.TimeoutExpired, AttributeError):
        return False


def verify(port: int, *, executable: str = "/usr/local/bin/yt-dlp",
           ffmpeg: str = "/usr/bin/ffmpeg",
           runner: Callable = subprocess.run,
           version_runner: Callable = subprocess.run) -> dict:
    """One finite, isolated measurement; never switches a live node."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return result("UNKNOWN", "invalid_proxy_port")
    if not ready(executable, version_runner=version_runner):
        return result("UNKNOWN", "ytdlp_or_compatible_js_unavailable")
    if not Path(ffmpeg).is_file():
        return result("UNKNOWN", "ffmpeg_unavailable")
    try:
        with tempfile.TemporaryDirectory(prefix="awg-video-probe-", dir=MEM_DIR) as tmp:
            folder = Path(tmp)
            target = str(folder / "test.%(ext)s")
            args = [
                "/usr/bin/python3", executable, "--ignore-config", "--no-playlist",
                "--proxy", f"http://127.0.0.1:{port}", "--force-ipv4",
                "--js-runtimes", "node", "--no-cache-dir", "--no-progress",
                "--socket-timeout", "5", "--retries", "0",
                "--fragment-retries", "0", "--extractor-retries", "0",
                "--downloader", "native", "--test", "--max-filesize", "2M",
                "--limit-rate", "160K",
                "--format", "bestvideo[height<=240]/bestvideo",
                "--output", target, VIDEO_URL
            ]
            completed = runner(args, cwd=tmp, env=restricted_env(),
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               timeout=MAX_SECONDS, check=False,
                               preexec_fn=limited_child)
            if completed.returncode != 0:
                return result("UNKNOWN", "youtube_extractor_or_media_unavailable")
            files = [f for f in folder.iterdir() if f.is_file()
                     and f.suffix.lower() in MEDIA_EXTENSIONS]
            if len(files) != 1:
                return result("UNKNOWN", "youtube_video_file_unverified")
            video = files[0]
            size = video.stat().st_size
            if not 128 <= size <= MAX_FILE:
                return result("UNKNOWN", "youtube_video_file_unverified")
            # IMPORTANT: Read local RAM file only, not a URL or http input.
            decode = runner([
                ffmpeg, "-v", "error", "-nostdin",
                "-protocol_whitelist", "file,pipe,crypto",
                "-i", str(video), "-an", "-frames:v", "1",
                "-f", "null", "-progress", "pipe:1", "-"],
                cwd=tmp, env=restricted_env(),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=8, check=False)
            if (decode.returncode == 0 and
                    isinstance(decode.stdout, (str, bytes)) and
                    re.search(r"(?m)^frame=\s*[1-9]\d*\s*$",
                              decode.stdout.decode("ascii", "replace")
                              if isinstance(decode.stdout, bytes)
                              else decode.stdout)):
                return result("PASS", "youtube_first_video_frame_decoded")
            return result("UNKNOWN", "youtube_video_decode_unverified")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return result("UNKNOWN", "youtube_media_probe_unavailable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-port", type=int, required=True)
    parser.add_argument("--ytdlp", default="/usr/local/bin/yt-dlp")
    args = parser.parse_args()
    import json
    verdict = verify(args.proxy_port, executable=args.ytdlp)
    print(json.dumps(verdict, sort_keys=True))
    return 0 if verdict["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
