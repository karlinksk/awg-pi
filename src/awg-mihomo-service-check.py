#!/usr/bin/env python3
"""Conservative, read-only service eligibility probes through a loopback Mihomo proxy.

PASS requires BOTH OpenAI region/API and ChatGPT web access, PLUS a YouTube
watch page and an actual small byte range from a video media endpoint.
UNKNOWN is never promoted to PASS. No selector, routes or configuration are changed.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable

OPENAI_API = "https://api.openai.com/v1/models"
CHATGPT_WEB = "https://chatgpt.com/"
YOUTUBE_WATCH = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
MAX_WEB_BYTES = 2_000_000
MAX_MEDIA_BYTES = 1024


@dataclass
class Result:
    state: str
    reason: str


def fetch(proxy_port: int, url: str, *, timeout: float = 6.0,
          headers: dict | None = None, max_bytes: int = MAX_WEB_BYTES) -> tuple[int, bytes, str]:
    if not (1 <= proxy_port <= 65535):
        raise ValueError("invalid loopback proxy port")
    # ProxyHandler's default implementation obeys NO_PROXY (including "*"),
    # which would silently bypass Mihomo. Force the loopback proxy for every
    # request, including HTTPS redirects, regardless of process environment.
    class ForcedLoopbackProxy(urllib.request.ProxyHandler):
        def proxy_open(self, req, proxy, proxy_type):
            req.set_proxy(f"127.0.0.1:{proxy_port}", "http")
            return None

    proxy = f"http://127.0.0.1:{proxy_port}"
    opener = urllib.request.build_opener(
        ForcedLoopbackProxy({"http": proxy, "https": proxy}),
        urllib.request.HTTPSHandler())
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 AWG-Service-Probe",
                      "Accept": "*/*", **(headers or {})})
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        status = int(response.status)
        final = str(response.geturl())
        # Limit response payload in RAM; too-large pages are inconclusive.
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("response too large")
        return status, data, final


def openai_probe(request: Callable) -> Result:
    try:
        code, body, _ = request(OPENAI_API, max_bytes=8192)
        text = body.decode("utf-8", "replace").lower()
        if "unsupported_country_region_territory" in text:
            return Result("FAIL", "openai_unsupported_region")
        if code == 401:
            return Result("PASS", "openai_api_auth_required")
        return Result("UNKNOWN", f"openai_api_http_{code}")
    except Exception as exc:
        return Result("UNKNOWN", "openai_api_" + type(exc).__name__)


def chatgpt_web_probe(request: Callable) -> Result:
    try:
        code, body, final = request(CHATGPT_WEB, max_bytes=MAX_WEB_BYTES)
        host = (urllib.parse.urlsplit(final).hostname or "").lower()
        if host not in ("chatgpt.com", "auth.openai.com", "login.openai.com", "openai.com"):
            return Result("UNKNOWN", "chatgpt_unexpected_redirect")
        if code == 200 and body:
            return Result("PASS", "chatgpt_web_http_200")
        # 403 can be Cloudflare challenge rather than an IP-level restriction.
        if code == 403:
            return Result("UNKNOWN", "chatgpt_web_http_403")
        return Result("UNKNOWN", f"chatgpt_web_http_{code}")
    except Exception as exc:
        return Result("UNKNOWN", "chatgpt_web_" + type(exc).__name__)


def media_url_from_html(html: bytes) -> str | None:
    text = html.decode("utf-8", "replace")
    # YouTube watch response embeds a player JSON object, which may be absent
    # under a consent screen, bot challenge or changed player version.
    match = re.search(r"ytInitialPlayerResponse\s*=\s*", text)
    if not match:
        return None
    try:
        player, _ = json.JSONDecoder().raw_decode(text[match.end():])
    except (ValueError, TypeError):
        return None
    streams = player.get("streamingData", {}) if isinstance(player, dict) else {}
    if not isinstance(streams, dict):
        return None
    candidates = streams.get("formats", []) + streams.get("adaptiveFormats", [])
    for stream in candidates:
        if not isinstance(stream, dict):
            continue
        url = stream.get("url")
        if isinstance(url, str) and allowed_media_url(url):
            return url
    return None


def allowed_media_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (parsed.scheme == "https" and parsed.username is None
                and parsed.password is None
                and (host == "googlevideo.com" or host.endswith(".googlevideo.com"))
                and (parsed.port is None or parsed.port == 443)
                and bool(parsed.path))
    except ValueError:
        return False


def youtube_probe(request: Callable) -> Result:
    try:
        status, watch, _ = request(YOUTUBE_WATCH, max_bytes=MAX_WEB_BYTES)
        if status != 200:
            return Result("UNKNOWN", f"youtube_watch_http_{status}")
        video_url = media_url_from_html(watch)
        if video_url is None:
            return Result("UNKNOWN", "youtube_media_url_unavailable")
        code, data, final_url = request(
            video_url, headers={"Range": "bytes=0-1023"},
            max_bytes=MAX_MEDIA_BYTES)
        if not allowed_media_url(final_url):
            return Result("UNKNOWN", "youtube_media_unexpected_redirect")
        if code == 206 and len(data) > 0:
            return Result("PASS", "youtube_video_media_range")
        if code in (403, 451):
            return Result("FAIL", f"youtube_media_http_{code}")
        return Result("UNKNOWN", f"youtube_media_http_{code}")
    except Exception as exc:
        return Result("UNKNOWN", "youtube_" + type(exc).__name__)


def assess(request: Callable) -> dict:
    # Individual probes intentionally run even if the other already failed.
    api = openai_probe(request)
    web = chatgpt_web_probe(request)
    video = youtube_probe(request)
    checks = {"openai_api": asdict(api), "chatgpt_web": asdict(web),
              "youtube_video": asdict(video)}
    states = [item.state for item in (api, web, video)]
    verdict = "PASS" if all(s == "PASS" for s in states) else (
        "FAIL" if any(s == "FAIL" for s in states) else "UNKNOWN")
    return {"status": verdict, "checks": checks, "checked_at": int(time.time())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=6.0)
    args = parser.parse_args()
    if not 1 <= args.proxy_port <= 65535 or not 1 <= args.timeout <= 15:
        parser.error("invalid proxy port or timeout")
    def request(url, **kwargs):
        return fetch(args.proxy_port, url, timeout=args.timeout, **kwargs)
    result = assess(request)
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
