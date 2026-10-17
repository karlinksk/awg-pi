#!/usr/bin/env python3
"""Regression for Stage18 24-frame decoder integration, no real network."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
from subprocess import CompletedProcess
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]/"src"
SMART=HERE/"awg-mihomo-smart"
MEDIA=HERE/"awg-mihomo-video-decode.py"
spec=importlib.util.spec_from_file_location("test_stage18_video",MEDIA)
vid=importlib.util.module_from_spec(spec);spec.loader.exec_module(vid)
loader=importlib.machinery.SourceFileLoader("test_stage18_smart",str(SMART))
smart_spec=importlib.util.spec_from_loader(loader.name,loader)
smart=importlib.util.module_from_spec(smart_spec);loader.exec_module(smart)

class VideoStage18(unittest.TestCase):
    def mock_subprocess(self,*,frames=24,size=43000,ok=True):
        calls=[]
        def runner(argv,**kwargs):
            calls.append(argv)
            if str(argv[0]).endswith("yt-dlp"):
                target=Path(argv[argv.index("--output")+1].replace("%(ext)s","mp4"))
                if ok:
                    target.write_bytes(b"video fixture bytes"*max(1,size//19))
                return CompletedProcess(argv,0 if ok else 1,"","")
            return CompletedProcess(argv,0,f"frame={frames}\nprogress=end\n","")
        return runner,calls

    def test_ytdlp_failure_families_are_bounded_and_secret_free(self):
        cases = (
            ("ERROR: HTTP Error 403: Forbidden https://SECRET", "stage18_ytdlp_http_denied"),
            ("ERROR: Sign in to confirm you're not a bot", "stage18_ytdlp_bot_challenge"),
            ("ERROR: Requested format is not available", "stage18_ytdlp_format_unavailable"),
            ("ERROR: Failed to solve EJS challenge", "stage18_ytdlp_js_challenge"),
            ("ERROR: ffmpeg exited with code 1", "stage18_ytdlp_ffmpeg_error"),
            ("ERROR: The read operation timed out", "stage18_ytdlp_network_error"),
            ("ERROR: File size limit exceeded", "stage18_ytdlp_file_limit"),
            ("ERROR: unknown SECRET=token", "stage18_ytdlp_extract_or_download_failed"),
        )
        for message, expected in cases:
            with self.subTest(expected=expected):
                actual = vid._ytdlp_failure_reason(1, message)
                self.assertEqual(actual, expected)
                self.assertNotIn("SECRET", actual)
        self.assertEqual(vid._ytdlp_failure_reason(-25, ""),
                         "stage18_ytdlp_file_limit")

    def test_ytdlp_failure_is_reported_without_raw_stderr(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            return CompletedProcess(argv, 1, "", "ERROR: HTTP Error 403: https://SECRET")
        with patch.object(vid.os, "geteuid", return_value=0):
            state, reason = vid.decode_24_frames(
                17891, runner=runner, check_runtime=lambda root: True,
                ffmpeg_check=lambda: True)
        self.assertEqual((state, reason), ("UNKNOWN", "stage18_ytdlp_http_denied"))
        self.assertEqual(len(calls), 1)

    def test_missing_ffmpeg_fails_before_network_or_download(self):
        def must_not_run(*args, **kwargs):
            self.fail("Missing FFmpeg must not invoke yt-dlp")
        with patch.object(vid.os, "geteuid", return_value=0):
            state, reason = vid.decode_24_frames(
                17891, runner=must_not_run,
                check_runtime=lambda root: True,
                ffmpeg_check=lambda: False)
        self.assertEqual((state, reason), ("UNKNOWN", "stage18_ffmpeg_unavailable"))

    def test_ffmpeg_presence_requires_executable_regular_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ffmpeg = Path(d) / "ffmpeg"
            self.assertFalse(vid.ffmpeg_ready(ffmpeg))
            ffmpeg.write_text("fixture")
            ffmpeg.chmod(0o600)
            self.assertFalse(vid.ffmpeg_ready(ffmpeg))
            ffmpeg.chmod(0o700)
            self.assertTrue(vid.ffmpeg_ready(ffmpeg))
            alias = Path(d) / "alias"
            alias.symlink_to(ffmpeg)
            self.assertFalse(vid.ffmpeg_ready(alias))

    def test_twenty_four_frames_are_pass(self):
        runner,calls=self.mock_subprocess()
        with patch.object(vid.os,"geteuid",return_value=0):
            state,reason=vid.decode_24_frames(17891,runner=runner,check_runtime=lambda root:True,
                ffmpeg_check=lambda: True)
        self.assertEqual((state,reason),("PASS","youtube_24_video_frames_decoded"))
        self.assertEqual(len(calls),2)
        self.assertIn("--proxy",calls[0])
        self.assertIn("http://127.0.0.1:17891",calls[0])
        self.assertEqual(calls[1][0],"/usr/bin/ffmpeg")
        self.assertIn("-frames:v",calls[1])
        self.assertIn("24",calls[1])

    def test_twenty_three_frames_do_not_pass(self):
        runner,_=self.mock_subprocess(frames=23)
        with patch.object(vid.os,"geteuid",return_value=0):
            result=vid.decode_24_frames(17891,runner=runner,check_runtime=lambda root:True,
                ffmpeg_check=lambda: True)
        self.assertEqual(result[0],"UNKNOWN")
        self.assertEqual(result[1],"stage18_insufficient_frames")

    def test_failed_download_does_not_pass(self):
        runner,_=self.mock_subprocess(ok=False)
        with patch.object(vid.os,"geteuid",return_value=0):
            result=vid.decode_24_frames(17891,runner=runner,check_runtime=lambda root:True,
                ffmpeg_check=lambda: True)
        self.assertEqual(result[1],"stage18_ytdlp_extract_or_download_failed")

    def test_oversized_download_does_not_pass(self):
        runner,_=self.mock_subprocess(size=vid.MAX_SAMPLE_BYTES+1500)
        with patch.object(vid.os,"geteuid",return_value=0):
            result=vid.decode_24_frames(17891,runner=runner,check_runtime=lambda root:True,
                ffmpeg_check=lambda: True)
        self.assertEqual(result[1],"stage18_media_sample_invalid")

    def test_insecure_or_missing_runtime_fails_closed(self):
        self.assertFalse(vid.verified_runtime(Path("/tmp/nonexistent-stage18")))
        with patch.object(vid.os,"geteuid",return_value=0):
            result=vid.decode_24_frames(17891,check_runtime=lambda root:False)
        self.assertEqual(result[0],"UNKNOWN")

    def test_invalid_proxy_port_rejected_without_execution(self):
        for port in (0,-1,65536,"7890"):
            self.assertEqual(vid.decode_24_frames(port)[0],"UNKNOWN")

    @staticmethod
    def gate(api="PASS",web="PASS",youtube="UNKNOWN"):
        checks={k:{"state":v,"reason":"mock"} for k,v in
                (("openai_api",api),("chatgpt_web",web),("youtube_video",youtube))}
        result={"status":"UNKNOWN","checks":checks}
        return types.SimpleNamespace(assess=lambda f, **kw:result,fetch=lambda *x,**kw:None)

    def test_sabr_fallback_promotes_only_actual_decoder_pass(self):
        gate=self.gate()
        video=types.SimpleNamespace(decode_24_frames=lambda port:("PASS","youtube_24_video_frames_decoded"))
        out=smart.assess_services_with_stage18(gate,17891,video_module=video)
        self.assertEqual(out["status"],"PASS")
        self.assertEqual(out["checks"]["youtube_video"]["reason"],"youtube_24_video_frames_decoded")

    def test_unknown_video_decoder_cannot_promote(self):
        gate=self.gate()
        video=types.SimpleNamespace(decode_24_frames=lambda port:("UNKNOWN","stage18_insufficient_frames"))
        self.assertEqual(smart.assess_services_with_stage18(gate,17891,video_module=video)["status"],"UNKNOWN")

    def test_api_region_failure_never_promoted(self):
        gate=self.gate(api="FAIL")
        video=types.SimpleNamespace(decode_24_frames=lambda port:(_ for _ in ()).throw(AssertionError("called")))
        self.assertEqual(smart.assess_services_with_stage18(gate,17891,video_module=video)["status"],"FAIL")

    def test_no_expensive_decoder_when_web_unconfirmed_in_bulk_scan(self):
        gate=self.gate(web="UNKNOWN")
        video=types.SimpleNamespace(decode_24_frames=lambda port:(_ for _ in ()).throw(AssertionError("called")))
        self.assertEqual(smart.assess_services_with_stage18(gate,17891,video_module=video)["status"],"UNKNOWN")
        state=smart.assess_services_with_stage18(
            self.gate(web="UNKNOWN"),17891,force_media=True,
            video_module=types.SimpleNamespace(decode_24_frames=lambda port:("PASS","youtube_24_video_frames_decoded")))
        self.assertEqual(state["checks"]["youtube_video"]["state"],"PASS")
        self.assertEqual(state["status"],"UNKNOWN")

    def test_http_header_pass_cannot_bypass_24_frame_decoder(self):
        gate=self.gate(youtube="PASS")
        video=types.SimpleNamespace(
            decode_24_frames=lambda port:("UNKNOWN", "stage18_insufficient_frames"))
        result=smart.assess_services_with_stage18(gate,17891,video_module=video)
        self.assertEqual(result["checks"]["youtube_video"]["state"],"UNKNOWN")
        self.assertEqual(result["status"],"UNKNOWN")

    def test_stage18_does_not_call_legacy_youtube_http_probe(self):
        called=[]
        gate=types.SimpleNamespace(
            fetch=lambda *args,**kwargs:None,
            assess=lambda fn,**kwargs:(
                called.append(kwargs.get("include_youtube")) or
                {"status":"UNKNOWN","checks":{
                    "openai_api":{"state":"PASS","reason":"fixture"},
                    "chatgpt_web":{"state":"PASS","reason":"fixture"},
                    "youtube_video":{"state":"PASS","reason":"unsafe_legacy_http_header"}}}))
        video=types.SimpleNamespace(
            decode_24_frames=lambda port:("PASS","youtube_24_video_frames_decoded"))
        outcome=smart.assess_services_with_stage18(gate,17891,video_module=video)
        self.assertEqual(called,[False])
        self.assertEqual(outcome["status"],"PASS")
        self.assertEqual(outcome["checks"]["youtube_video"]["reason"],
                         "youtube_24_video_frames_decoded")

if __name__=="__main__":
    unittest.main()
