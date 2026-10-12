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
VIDEO_BOX = b"\x00\x00\x00\x18ftypisom" + b"\x00"*12
WATCH = ('<script>var ytInitialPlayerResponse = ' +
         json.dumps({"playabilityStatus": {"status": "OK"},  "streamingData": {"formats": [{"url": MEDIA, "mimeType": "video/mp4"}]}}) + ';</script>').encode()


def cases(api=(401, b'{"error":{"message":"Missing bearer authentication"}}'),
          web=(200, b"<!doctype html><html>ChatGPT</html>"),
          watch=(200, WATCH), media=(206, VIDEO_BOX)):
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
    def test_all_services_and_decoded_video_frame_pass(self):
        result = gate.assess(cases(), frame_verifier=lambda: {
            "state": "PASS", "reason": "youtube_first_video_frame_decoded",
            "method": "video_frame_decode", "shadow_only": True})
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checks"]["youtube_video"]["reason"],
                         "youtube_first_video_frame_decoded")

    def test_http_206_container_header_alone_is_not_playback(self):
        result = gate.assess(cases())
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["checks"]["youtube_video"]["reason"],
                         "youtube_video_container_only")

    def test_verifier_fake_success_not_allowed(self):
        result = gate.assess(cases(), frame_verifier=lambda: {
            "state": "PASS", "reason": "got_200_webpage",
            "method": "webpage", "shadow_only": True})
        self.assertEqual(result["status"], "UNKNOWN")

    def test_sabr_can_only_pass_with_decoded_video(self):
        sabr = "https://rr3---sn-test.googlevideo.com/videoplayback?sabr=1"
        page = ("ytInitialPlayerResponse = " + json.dumps({
            "playabilityStatus":{"status":"OK"},
            "streamingData":{"serverAbrStreamingUrl":sabr}})).encode()
        passed = gate.assess(cases(watch=(200,page)), frame_verifier=lambda: {
            "state": "PASS", "reason": "youtube_first_video_frame_decoded",
            "method": "video_frame_decode", "shadow_only": True})
        self.assertEqual(passed["status"], "PASS")
        unverified = gate.assess(cases(watch=(200,page)))
        self.assertEqual(unverified["status"], "UNKNOWN")


    def test_arbitrary_http_206_bytes_are_not_real_video(self):
        result = gate.assess(cases(media=(206, b"x")))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["checks"]["youtube_video"]["reason"],
                         "youtube_video_container_unverified")

    def test_http_206_html_is_not_real_video(self):
        result = gate.assess(cases(media=(206, b"<html>unavailable</html>")))
        self.assertEqual(result["status"], "UNKNOWN")

    def test_audio_only_media_cannot_prove_video(self):
        page = ("ytInitialPlayerResponse = " + json.dumps({
            "playabilityStatus": {"status": "OK"},
            "streamingData": {"adaptiveFormats": [
                {"url": MEDIA, "mimeType": "audio/mp4; codecs=mp4a.40.2"}]}})).encode()
        self.assertEqual(gate.assess(cases(watch=(200,page)))["status"],"UNKNOWN")

    def test_webm_video_header_recognized(self):
        self.assertTrue(gate.plausible_video_header(
            b"\x1a\x45\xdf\xa3" + b"0"*16))

    def test_mpegts_single_sync_byte_is_not_enough(self):
        self.assertFalse(gate.plausible_video_header(b"G" + b"0"*500))
        ts = bytearray(b"0"*500)
        ts[0] = ts[188] = ts[376] = 0x47
        self.assertTrue(gate.plausible_video_header(bytes(ts)))

    def test_bad_bmff_box_length_rejected(self):
        self.assertFalse(gate.plausible_video_header(
            b"\x00\x00\x00\x00ftypisom0000"))

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

    def test_media_url_403_is_not_global_youtube_block(self):
        result = gate.assess(cases(media=(403, b"forbidden")))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["checks"]["youtube_video"]["reason"],
                         "youtube_media_http_403_unconfirmed")

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

    def test_sabr_player_does_not_fake_actual_media_success(self):
        sabr = "https://rr3---sn-test.googlevideo.com/videoplayback?sabr=1"
        goodput = "https://rr3---sn-test.googlevideo.com/videogoodput?sig=demo"
        page = ("<script>ytInitialPlayerResponse = " +
                json.dumps({"playabilityStatus": {"status": "OK"},
                            "streamingData": {
                                "serverAbrStreamingUrl": sabr,
                                "probeUrl": goodput,
                                "adaptiveFormats": [{"itag": 140, "mimeType": "audio/mp4"}]}}) +
                ";</script>").encode()
        sent = []
        def request(url, **kw):
            sent.append(url)
            if url == gate.YOUTUBE_WATCH:
                return 200, page, url
            if url == goodput:
                self.assertEqual(kw.get("headers"), {"Range": "bytes=0-1023"})
                self.assertEqual(kw.get("max_bytes"), 1024)
                return 206, b"goodput", url
            raise AssertionError("request must not fetch SABR as direct video bytes")
        result = gate.youtube_probe(request)
        self.assertEqual(result.state, "UNKNOWN")
        self.assertEqual(result.reason, "youtube_sabr_cdn_reachable_media_unverified")
        self.assertNotIn(sabr, sent)

    def test_sabr_unreachable_cdn_stays_unknown(self):
        sabr = "https://rr3---sn-test.googlevideo.com/videoplayback?sabr=1"
        page = ("ytInitialPlayerResponse = " + json.dumps({
            "playabilityStatus": {"status": "OK"},
            "streamingData": {"serverAbrStreamingUrl": sabr,
                              "probeUrl": "https://bad.example.local/videogoodput"}})).encode()
        outcome = gate.youtube_probe(lambda url, **kw: (200, page, url))
        self.assertEqual(outcome.state, "UNKNOWN")
        self.assertEqual(outcome.reason, "youtube_sabr_media_unverified")

    def test_unplayable_single_video_not_global_youtube_failure(self):
        page = ("ytInitialPlayerResponse = " + json.dumps({
            "playabilityStatus": {"status": "LOGIN_REQUIRED"},
             "streamingData": {"formats": [{"url": MEDIA, "mimeType": "video/mp4"}]}})).encode()
        result = gate.youtube_probe(lambda url, **kw: (200, page, url))
        self.assertEqual(result.state, "UNKNOWN")
        self.assertEqual(result.reason, "youtube_player_not_confirmed_playable")

    def test_malformed_streaming_data_never_throws(self):
        page = ("ytInitialPlayerResponse = " + json.dumps({
            "playabilityStatus": {"status": "OK"},
            "streamingData": {"formats": "bad", "adaptiveFormats": {}}})).encode()
        self.assertEqual(gate.youtube_probe(lambda url, **kw: (200, page, url)).state,
                         "UNKNOWN")

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

    def test_gate_exposes_fresh_sample_identity_in_cli(self):
        import io
        import contextlib
        import sys
        from unittest.mock import patch
        output = io.StringIO()
        with patch.object(gate, "assess", return_value={"status": "PASS", "checks": {},
                                                        "checked_at": 2000}), \
             patch.object(sys, "argv", ["check", "--proxy-port", "7890",
                                       "--identity", "node-A"]), \
             contextlib.redirect_stdout(output):
            self.assertEqual(gate.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual((result["identity"], result["transport"]), ("node-A", "mihomo"))
        self.assertEqual(len(result["sample_id"]), 32)

    def test_loopback_proxy_must_be_valid(self):
        for invalid in (0, 65536, -1):
            with self.assertRaises(ValueError):
                gate.fetch(invalid, gate.OPENAI_API)


if __name__ == "__main__":
    unittest.main()
