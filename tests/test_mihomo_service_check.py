#!/usr/bin/env python3
"""Offline tests for the conservative per-node service eligibility gate."""
import importlib.util
import json
import os
import socket
import threading
from unittest.mock import patch
from pathlib import Path
import sys
import unittest

MODULE = Path(__file__).resolve().parents[1] / "src" / "awg-mihomo-service-check.py"
spec = importlib.util.spec_from_file_location("service_gate", MODULE)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)

MEDIA = "https://rr5---sn-test.googlevideo.com/videoplayback?id=abc"
WATCH = ('<script>var ytInitialPlayerResponse = ' +
         json.dumps({"streamingData": {"formats": [{"url": MEDIA, "mimeType": "video/mp4"}]}}) + ';</script>').encode()


def cases(api=(401, b'{"error":{"message":"Missing bearer authentication"}}'),
          web=(200, b"<!doctype html><html>ChatGPT</html>"),
          watch=(200, WATCH), media=(206, b"\x00\x00\x00\x18ftypisom" + b"0"*80)):
    def request(url, **kwargs):
        if url == gate.OPENAI_API:
            return *api, url
        if url == gate.CHATGPT_WEB:
            return *web, url
        if url == gate.YOUTUBE_WATCH:
            return *watch, url
        if url == MEDIA:
            assert kwargs.get("headers") == {"Range": "bytes=0-1023"}
            assert kwargs.get("max_bytes") == 1024
            return *media, url
        raise AssertionError("unexpected URL " + url)
    return request


class ServiceGateTests(unittest.TestCase):
    def test_both_services_and_actual_video_range_pass(self):
        result = gate.assess(cases())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checks"]["youtube_video"]["reason"], "youtube_video_media_range_header")

    def test_arbitrary_206_body_does_not_count_as_video(self):
        result = gate.assess(cases(media=(206, b"<html>blocked but 206</html>")))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["checks"]["youtube_video"]["reason"], "youtube_media_not_recognized")

    def test_audio_only_206_cannot_qualify_video(self):
        watch = ('var ytInitialPlayerResponse = ' +
                 json.dumps({"streamingData":{"formats":[{"url":MEDIA,"mimeType":"audio/mp4"}]}})).encode()
        self.assertEqual(gate.assess(cases(watch=(200,watch)))["status"],"UNKNOWN")

    def test_region_block_is_not_healthy(self):
        api = (403, b'{"error":{"code":"unsupported_country_region_territory"}}')
        result = gate.assess(cases(api=api))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["checks"]["openai_api"]["reason"], "openai_unsupported_region")

    def test_chatgpt_web_challenge_must_not_promote_to_pass(self):
        result = gate.assess(cases(web=(403, b"Just a moment...")))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["checks"]["chatgpt_web"]["reason"], "chatgpt_web_http_403")

    def test_watch_page_without_video_is_unknown(self):
        result = gate.assess(cases(watch=(200, b"<html>youtube</html>")))
        self.assertEqual(result["status"], "UNKNOWN")

    def test_actual_video_failure_blocks_selection(self):
        result = gate.assess(cases(media=(403, b"forbidden")))
        self.assertEqual(result["status"], "FAIL")

    def test_invalid_media_host_is_not_requested(self):
        host = "https://googlevideo.com.evil.example/videoplayback?id=foo"
        watch = ('var ytInitialPlayerResponse = ' +
                 json.dumps({"streamingData": {"formats": [{"url": host}]}})).encode()
        self.assertIsNone(gate.media_url_from_html(watch))
        self.assertEqual(gate.assess(cases(watch=(200, watch)))["status"], "UNKNOWN")

    def test_no_resolved_url_is_unknown(self):
        watch = ('var ytInitialPlayerResponse = ' +
                 json.dumps({"streamingData": {"formats": [{"signatureCipher": "cipher"}]}})).encode()
        self.assertEqual(gate.assess(cases(watch=(200, watch)))["status"], "UNKNOWN")

    def test_malformed_player_is_unknown(self):
        self.assertIsNone(gate.media_url_from_html(b'ytInitialPlayerResponse = {notjson;}'))

    def test_missing_service_is_unknown_not_pass(self):
        def request(url, **kwargs):
            if url == gate.CHATGPT_WEB:
                raise TimeoutError()
            return cases()(url, **kwargs)
        self.assertEqual(gate.assess(request)["status"], "UNKNOWN")

    def test_http_200_challenge_is_unknown(self):
        result = gate.assess(cases(web=(200, b"<html>Just a moment...</html>")))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["checks"]["chatgpt_web"]["reason"], "chatgpt_web_challenge")

    def test_no_proxy_wildcard_does_not_bypass_loopback_proxy(self):
        received = []
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(2.0)
            port = server.getsockname()[1]
            def serve():
                try:
                    conn, _ = server.accept()
                    with conn:
                        conn.settimeout(2.0)
                        received.append(conn.recv(4096))
                        conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                except (OSError, TimeoutError):
                    pass
            thread = threading.Thread(target=serve)
            thread.start()
            with patch.dict(os.environ, {"NO_PROXY": "*", "no_proxy": "*"}):
                try:
                    gate.fetch(port, gate.OPENAI_API, timeout=1.5)
                except Exception:
                    pass
            thread.join(timeout=2.5)
        self.assertTrue(received, "the proxy was bypassed")
        self.assertIn(b"CONNECT api.openai.com:443", received[0])

    def test_untrusted_media_url_is_rejected_before_network(self):
        self.assertFalse(gate.allowed_probe_url("http://api.openai.com/v1/models"))
        self.assertFalse(gate.allowed_probe_url("https://127.0.0.1/admin"))
        self.assertFalse(gate.allowed_probe_url("https://googlevideo.com.evil.invalid/a"))
        self.assertFalse(gate.allowed_probe_url("https://api.openai.com:8443/v1/models"))
        with self.assertRaisesRegex(ValueError, "unapproved probe URL"):
            gate.fetch(7890, "https://127.0.0.1/admin")

    def test_redirect_to_untrusted_host_is_rejected_before_network(self):
        # The HTTP redirect handler must reject the target, not examine it
        # after making a connection to the untrusted destination.
        import urllib.request
        handler = gate.RestrictedRedirects()
        req = urllib.request.Request(gate.OPENAI_API)
        with self.assertRaisesRegex(ValueError, "unapproved probe redirect"):
            handler.redirect_request(req, None, 302, "Found", {},
                                     "https://evil.invalid/collect")
        self.assertTrue(gate.allowed_probe_url(gate.OPENAI_API))

    def test_http_200_non_chatgpt_page_is_unknown(self):
        self.assertEqual(gate.assess(cases(web=(200, b"<html>OK</html>")))["status"],
                         "UNKNOWN")

    def test_loopback_proxy_must_be_valid(self):
        for invalid in (0, 65536, -1):
            with self.assertRaises(ValueError):
                gate.fetch(invalid, gate.OPENAI_API)


if __name__ == "__main__":
    unittest.main()
