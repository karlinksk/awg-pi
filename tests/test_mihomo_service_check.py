#!/usr/bin/env python3
"""Offline tests for the conservative per-node service eligibility gate."""
import importlib.util
import json
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
         json.dumps({"streamingData": {"formats": [{"url": MEDIA}]}}) + ';</script>').encode()


def cases(api=(401, b'{"error":{"message":"Missing bearer authentication"}}'),
          web=(200, b"<!doctype html><html>ChatGPT</html>"),
          watch=(200, WATCH), media=(206, b"x")):
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
        self.assertEqual(result["checks"]["youtube_video"]["reason"], "youtube_video_media_range")

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

    def test_loopback_proxy_must_be_valid(self):
        for invalid in (0, 65536, -1):
            with self.assertRaises(ValueError):
                gate.fetch(invalid, gate.OPENAI_API)


if __name__ == "__main__":
    unittest.main()
