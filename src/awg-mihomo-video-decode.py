#!/usr/bin/env python3
"""Stage18 video-frame decoder reused by Mihomo Service Eligibility.

Never changes routes, services, live transport, or the selected Mihomo node.
Expected to run only against the existing isolated TUN-disabled shadow proxy.
Requires pinned, root-owned Node.js/yt-dlp in RAM; ffmpeg decodes a bounded
RAM-only sample. UNKNOWN on any error; no cookie/session sharing or logging.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import tempfile
import time

RAM_RUNTIME = Path("/dev/shm/awg-stage18-service-runtime")
YT_SHA = "1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6"
NODE_SHA = "fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5"
YOUTUBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
MAX_SAMPLE_BYTES = 2 * 1024 * 1024
MIN_FRAMES = 24

def _ytdlp_failure_reason(returncode: int, stderr: str) -> str:
    """Classify only known stderr patterns; never print signed media URLs."""
    raw = stderr[-12000:].lower()
    if returncode == -25 or re.search(r"file size limit exceeded|\[errno 27\]|file too large", raw):
        return "stage18_ytdlp_file_limit"
    if re.search(r"confirm you.re not a bot|sign in to confirm|bot verification|use --cookies", raw):
        return "stage18_ytdlp_bot_challenge"
    if re.search(r"http error[ :]+(?:403|429|451)\b|status code[ :]+(?:403|429|451)\b", raw):
        return "stage18_ytdlp_http_denied"
    if re.search(r"requested format is not available|no video formats found|format is not available", raw):
        return "stage18_ytdlp_format_unavailable"
    if re.search(r"remote component|ejs|nsig|signature extraction|signature solving|javascript challenge", raw):
        return "stage18_ytdlp_js_challenge"
    if re.search(r"ffmpeg.*(?:error|failed|exited|not found)|(?:error|failed).*ffmpeg", raw):
        return "stage18_ytdlp_ffmpeg_error"
    if re.search(r"timed out|timeout|connection reset|network is unreachable", raw):
        return "stage18_ytdlp_network_error"
    return "stage18_ytdlp_extract_or_download_failed"

def _verified_file(path: Path, expected: str) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    st = path.lstat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
        return False
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fresh = os.fstat(fd)
        if (st.st_dev, st.st_ino) != (fresh.st_dev, fresh.st_ino):
            return False
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
    finally:
        if fd >= 0:
            os.close(fd)
    return digest.hexdigest() == expected

def verified_runtime(root: Path = RAM_RUNTIME) -> bool:
    try:
        st = root.lstat()
        return (root.parent == Path("/dev/shm") and not root.is_symlink()
                and stat.S_ISDIR(st.st_mode) and st.st_uid == 0
                and stat.S_IMODE(st.st_mode) == 0o700
                and _verified_file(root / "node", NODE_SHA)
                and _verified_file(root / "yt-dlp", YT_SHA))
    except OSError:
        return False

def ffmpeg_ready(executable: Path = Path("/usr/bin/ffmpeg")) -> bool:
    """Stage18 is optional; do not silently install heavy multimedia packages."""
    return (executable.is_file() and not executable.is_symlink()
            and os.access(executable, os.X_OK))


def _limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_SAMPLE_BYTES, MAX_SAMPLE_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))

def decode_24_frames(proxy_port: int, *, root: Path = RAM_RUNTIME,
                     runner=subprocess.run, check_runtime=verified_runtime,
                     ffmpeg_check=None) -> tuple[str, str]:
    """Return (PASS|UNKNOWN, code). Fail-safe and diagnostic-only."""
    if not isinstance(proxy_port, int) or not 1 <= proxy_port <= 65535:
        return "UNKNOWN", "stage18_invalid_proxy"
    if os.geteuid() != 0 or not check_runtime(root):
        return "UNKNOWN", "stage18_verified_ram_runtime_unavailable"
    if not (ffmpeg_check or ffmpeg_ready)():
        return "UNKNOWN", "stage18_ffmpeg_unavailable"
    try:
        with tempfile.TemporaryDirectory(prefix="awg-stage18-video-", dir="/dev/shm") as temp:
            output = Path(temp) / "probe.%(ext)s"
            argv = [
                str(root / "yt-dlp"), "--ignore-config", "--no-cache-dir",
                "--no-playlist", "--no-progress", "--no-warnings",
                "--socket-timeout", "7", "--retries", "1", "--extractor-retries", "1",
                "--js-runtimes", "node:" + str(root / "node"),
                "--remote-components", "ejs:github",
                "--proxy", f"http://127.0.0.1:{proxy_port}",
                "--format", "worstvideo[ext=mp4]/worstvideo",
                "--download-sections", "*0-4",
                "--force-overwrites", "--no-part",
                "--output", str(output),
                YOUTUBE_URL,
            ]
            env = os.environ.copy()
            env.update({"PYTHONDONTWRITEBYTECODE":"1", "XDG_CACHE_HOME":temp,
                        "TMPDIR":temp, "NO_PROXY":"", "no_proxy":""})
            job = runner(argv, capture_output=True, text=True, timeout=55,
                         env=env, preexec_fn=_limits)
            if job.returncode != 0:
                return "UNKNOWN", _ytdlp_failure_reason(job.returncode, job.stderr or "")
            files = [p for p in Path(temp).glob("probe.*") if p.is_file() and not p.is_symlink()]
            if len(files) != 1 or not 0 < files[0].stat().st_size <= MAX_SAMPLE_BYTES:
                return "UNKNOWN", "stage18_media_sample_invalid"
            result = runner([
                "/usr/bin/ffmpeg", "-nostdin", "-hide_banner",
                "-loglevel", "error", "-protocol_whitelist", "file,pipe,data",
                "-i", str(files[0]), "-an",
                "-frames:v", str(MIN_FRAMES), "-f", "null", "-",
                "-progress", "pipe:1",
            ], capture_output=True, text=True, timeout=17)
            if result.returncode != 0:
                return "UNKNOWN", "stage18_ffmpeg_decode_failed"
            observed = [int(m) for m in re.findall(r"(?m)^frame=\s*(\d+)\s*$", result.stdout)]
            if max(observed, default=0) < MIN_FRAMES:
                return "UNKNOWN", "stage18_insufficient_frames"
            return "PASS", "youtube_24_video_frames_decoded"
    except (OSError, subprocess.TimeoutExpired, ValueError, PermissionError):
        return "UNKNOWN", "stage18_media_runtime_error"
