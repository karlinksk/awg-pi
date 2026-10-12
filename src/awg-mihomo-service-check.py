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
import uuid
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
        # 403 can be Cloudflare challenge rather than an IP-level restriction.
        if code == 403:
            return Result("UNKNOWN", "chatgpt_web_http_403")
        return Result("UNKNOWN", f"chatgpt_web_http_{code}")
    except Exception as exc:
        return Result("UNKNOWN", "chatgpt_web_" + type(exc).__name__)


def player_from_html(html: bytes) -> dict | None:
    """Extract the embedded player object without evaluating any JS."""
    text = html.decode("utf-8", "replace")
    match = re.search(r"ytInitialPlayerResponse\s*=\s*", text)
    if not match:
        return None
    try:
        player, _ = json.JSONDecoder().raw_decode(text[match.end():])
    except (ValueError, TypeError):
        return None
    return player if isinstance(player, dict) else None


def media_url_from_player(player: dict | None) -> str | None:
    if not isinstance(player, dict):
        return None
    streams = player.get("streamingData", {})
    if not isinstance(streams, dict):
        return None
    formats = streams.get("formats", [])
    adaptive = streams.get("adaptiveFormats", [])
    if not isinstance(formats, list) or not isinstance(adaptive, list):
        return None
    for stream in formats + adaptive:
        if not isinstance(stream, dict):
            continue
        # Audio-only bytes must NEVER prove video playback. The player must
        # explicitly describe the selected stream as a VIDEO format.
        mime = stream.get("mimeType")
        if not isinstance(mime, str) or not mime.startswith("video/"):
            continue
        url = stream.get("url")
        if isinstance(url, str) and allowed_media_url(url):
            return url
    return None


def media_url_from_html(html: bytes) -> str | None:
    return media_url_from_player(player_from_html(html))


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


def plausible_video_header(data: bytes) -> bool:
    """Reject HTML and arbitrary 206 bytes; sniff only known video containers.

    This confirms the start of a *video container* from an actual media URL,
    NOT video decode or a logged-in browser playback session.
    """
    if not isinstance(data, bytes) or len(data) < 12:
        return False
    # ISO BMFF/fragmented MP4 must start with a valid sized file/segment box.
    if data[4:8] in (b"ftyp", b"styp") and int.from_bytes(data[:4], "big") >= 12:
        return True
    # Matroska/WebM EBML header magic.
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return True
    # H.264-in-MPEG-TS: demand at least three sync points, not one arbitrary 0x47.
    if len(data) >= 377 and all(data[n] == 0x47 for n in (0, 188, 376)):
        return True
    return False


def youtube_probe(request: Callable) -> Result:
    try:
        status, watch, _ = request(YOUTUBE_WATCH, max_bytes=MAX_WEB_BYTES)
        if status != 200:
            return Result("UNKNOWN", f"youtube_watch_http_{status}")
        player = player_from_html(watch)
        if player is None:
            return Result("UNKNOWN", "youtube_player_data_missing")
        playability = player.get("playabilityStatus")
        if not isinstance(playability, dict) or playability.get("status") != "OK":
            # A particular video could be age-restricted, deleted or blocked:
            # never extrapolate a video's availability to all of YouTube.
            return Result("UNKNOWN", "youtube_player_not_confirmed_playable")
        video_url = media_url_from_player(player)
        if video_url is None:
            stream = player.get("streamingData", {})
            if not isinstance(stream, dict):
                return Result("UNKNOWN", "youtube_media_url_unavailable")
            sabr = stream.get("serverAbrStreamingUrl")
            if isinstance(sabr, str) and allowed_media_url(sabr):
                # SABR/UMP does not expose normal video ranges. Do not call
                # SABR an actual media PASS merely because the player says OK.
                # The small /videogoodput probe is a *CDN reachability* check,
                # not decoded, playable video bytes.
                goodput = stream.get("probeUrl")
                if isinstance(goodput, str) and allowed_media_url(goodput):
                    try:
                        code, data, final = request(
                            goodput, headers={"Range": "bytes=0-1023"},
                            max_bytes=MAX_MEDIA_BYTES)
                        if (code in (200, 206) and data
                                and allowed_media_url(final)):
                            return Result("UNKNOWN",
                                          "youtube_sabr_cdn_reachable_media_unverified")
                    except Exception:
                        pass
                return Result("UNKNOWN", "youtube_sabr_media_unverified")
            return Result("UNKNOWN", "youtube_media_url_unavailable")
        code, data, final_url = request(
            video_url, headers={"Range": "bytes=0-1023"},
            max_bytes=MAX_MEDIA_BYTES)
        if not allowed_media_url(final_url):
            return Result("UNKNOWN", "youtube_media_unexpected_redirect")
        if code == 206 and plausible_video_header(data):
            return Result("PASS", "youtube_video_container_header_verified")
        if code == 206:
            return Result("UNKNOWN", "youtube_video_container_unverified")
        if code in (403, 451):
            # A signed URL can expire or require a playback/PO token. A
            # single video's CDN rejection cannot prove all YouTube is down.
            return Result("UNKNOWN", f"youtube_media_http_{code}_unconfirmed")
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
    parser.add_argument("--identity", default="",
                        help="Exact currently selected Mihomo node name for evidence attribution")
    args = parser.parse_args()
    if not 1 <= args.proxy_port <= 65535 or not 1 <= args.timeout <= 15:
        parser.error("invalid proxy port or timeout")
    def request(url, **kwargs):
        return fetch(args.proxy_port, url, timeout=args.timeout, **kwargs)
    result = assess(request)
    result["transport"] = "mihomo"
    result["identity"] = args.identity
    result["sample_id"] = uuid.uuid4().hex
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
