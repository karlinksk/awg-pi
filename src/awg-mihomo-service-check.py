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


def allowed_probe_url(url: str) -> bool:
    # Static HTTPS origins only. Dynamic Googlevideo media URLs must be
    # validated BEFORE connecting or following their redirects.
    if len(url) > 8192:
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and not parsed.username and not parsed.password
            and (parsed.port is None or parsed.port == 443)
            and (host in ("api.openai.com", "chatgpt.com",
                          "auth.openai.com", "login.openai.com",
                          "openai.com", "www.youtube.com", "youtube.com")
                 or allowed_media_url(url)))
    except ValueError:
        return False


class RestrictedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_probe_url(newurl):
            raise ValueError("unapproved probe redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(proxy_port: int, url: str, *, timeout: float = 6.0,
          headers: dict | None = None, max_bytes: int = MAX_WEB_BYTES) -> tuple[int, bytes, str]:
    if not (1 <= proxy_port <= 65535):
        raise ValueError("invalid loopback proxy port")
    if not allowed_probe_url(url):
        raise ValueError("unapproved probe URL")
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
        RestrictedRedirects(), urllib.request.HTTPSHandler())
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
            preview = body[:200_000].lower()
            if any(marker in preview for marker in (
                    b"cf-challenge", b"just a moment...", b"cf-turnstile",
                    b"verify you are human")):
                return Result("UNKNOWN", "chatgpt_web_challenge")
            if host != "chatgpt.com":
                return Result("UNKNOWN", "chatgpt_web_login_only")
            if b"chatgpt" not in preview or b"<html" not in preview:
                return Result("UNKNOWN", "chatgpt_web_content_unverified")
            return Result("PASS", "chatgpt_web_http_200")
        # Cloudflare can challenge even a real, JS-capable Chromium
        # launched with an empty profile. 403 does not disprove the user's chat.
        if code == 403:
            preview = body[:200_000].lower()
            if any(marker in preview for marker in (
                    b"just a moment", b"cf-challenge", b"cf-turnstile",
                    b"verify you are human")):
                return Result("UNKNOWN", "chatgpt_web_antibot_challenge")
            return Result("UNKNOWN", "chatgpt_web_http_403")
        return Result("UNKNOWN", f"chatgpt_web_http_{code}")
    except Exception as exc:
        return Result("UNKNOWN", "chatgpt_web_" + type(exc).__name__)


def player_from_html(html: bytes) -> dict | None:
    text = html.decode("utf-8", "replace")
    # Do not infer playback success from watch-page HTTP 200.
    match = re.search(r"ytInitialPlayerResponse\s*=\s*", text)
    if not match:
        return None
    try:
        player, _ = json.JSONDecoder().raw_decode(text[match.end():])
    except (ValueError, TypeError):
        return None
    return player if isinstance(player, dict) else None


def media_url_from_html(html: bytes) -> str | None:
    player = player_from_html(html)
    streams = player.get("streamingData", {}) if player else {}
    if not isinstance(streams, dict):
        return None
    candidates = streams.get("formats", []) + streams.get("adaptiveFormats", [])
    for stream in candidates:
        if not isinstance(stream, dict):
            continue
        url = stream.get("url")
        mime = stream.get("mimeType")
        # Audio-only responses cannot establish that YouTube video works.
        if (isinstance(mime, str) and mime.lower().startswith("video/")
                and isinstance(url, str) and allowed_media_url(url)):
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


def recognizable_video_header(data: bytes) -> bool:
    # A random 206 body is not proof the video media endpoint served video.
    # Accept the conservative initial container magic common to MP4/WebM/TS.
    if len(data) < 16:
        return False
    return ((data[4:8] == b"ftyp" and data[:4] != b"\x00\x00\x00\x00")
            or data.startswith(b"\x1a\x45\xdf\xa3")
            or (len(data) >= 377 and data[0] == 0x47
                and data[188] == 0x47 and data[376] == 0x47))


def youtube_probe(request: Callable) -> Result:
    try:
        status, watch, _ = request(YOUTUBE_WATCH, max_bytes=MAX_WEB_BYTES)
        if status != 200:
            return Result("UNKNOWN", f"youtube_watch_http_{status}")
        video_url = media_url_from_html(watch)
        if video_url is None:
            player = player_from_html(watch)
            if isinstance(player, dict):
                playability = player.get("playabilityStatus")
                if isinstance(playability, dict) and playability.get("status") == "LOGIN_REQUIRED":
                    # Bot/login challenge != proof the node cannot play video.
                    return Result("UNKNOWN", "youtube_player_login_required")
                streams = player.get("streamingData")
                if (isinstance(streams, dict)
                        and isinstance(streams.get("serverAbrStreamingUrl"), str)
                        and allowed_media_url(streams["serverAbrStreamingUrl"])):
                    # SABR is not plain MP4/WebM byte-range video: it needs a
                    # real supporting player. Never pretend reachability=playback.
                    return Result("UNKNOWN", "youtube_sabr_stream_unvalidated")
            return Result("UNKNOWN", "youtube_media_url_unavailable")
        code, data, final_url = request(
            video_url, headers={"Range": "bytes=0-1023"},
            max_bytes=MAX_MEDIA_BYTES)
        if not allowed_media_url(final_url):
            return Result("UNKNOWN", "youtube_media_unexpected_redirect")
        if code == 206 and recognizable_video_header(data):
            return Result("PASS", "youtube_video_media_range_header")
        if code == 206:
            return Result("UNKNOWN", "youtube_media_not_recognized")
        if code in (403, 451):
            return Result("FAIL", f"youtube_media_http_{code}")
        return Result("UNKNOWN", f"youtube_media_http_{code}")
    except Exception as exc:
        return Result("UNKNOWN", "youtube_" + type(exc).__name__)


def assess(request: Callable, *, include_youtube: bool = True) -> dict:
    # Individual probes intentionally run even if the other already failed.
    api = openai_probe(request)
    web = chatgpt_web_probe(request)
    # Stage18 uses the actual yt-dlp + FFmpeg 24-frame decoder, not the
    # legacy HTTP media-header check. Keep HTTP mode for other callers.
    video = (youtube_probe(request) if include_youtube
             else Result("UNKNOWN", "stage18_decoder_required"))
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
