#!/usr/bin/env python3
"""Offline no-network tests of opt-in decoded-frame probe."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

P=Path(__file__).resolve().parents[1]/"src"/"awg-youtube-frame-check.py"
s=importlib.util.spec_from_file_location("awg_youtube_frame_checker",P)
m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)


class FrameCheckTests(unittest.TestCase):
    def fixture(self, node_version="v22.13.1", *, media=True, decode=True,
                downloader_rc=0):
        root=tempfile.TemporaryDirectory(dir="/dev/shm")
        exe=Path(root.name)/"yt-dlp"
        exe.write_text("fixture")
        captured=[]
        def version_runner(cmd, **kwargs):
            return types.SimpleNamespace(returncode=0,stdout=node_version)
        def runner(args, **kwargs):
            captured.append((args,kwargs))
            if "--ignore-config" in args:
                if downloader_rc==0 and media:
                    output=args[args.index("--output")+1]
                    f=Path(output.replace("%(ext)s","mp4"))
                    f.write_bytes(b"\x00\x00\x00\x18ftypisom"+b"x"*500)
                return types.SimpleNamespace(returncode=downloader_rc)
            return types.SimpleNamespace(
                returncode=0 if decode else 1,
                stdout=b"frame=1\nprogress=end\n" if decode else b"frame=0\n")
        return root,exe,runner,version_runner,captured

    def test_missing_binary_is_unknown(self):
        self.assertEqual(m.verify(7890,executable="/missing/yt-dlp")["state"],"UNKNOWN")

    def test_old_node20_cannot_qualify(self):
        root,exe,runner,version,captured=self.fixture("v20.19.2")
        try:
            v=m.verify(7890,executable=str(exe),runner=runner,
                       version_runner=version)
            self.assertEqual(v["state"],"UNKNOWN")
            self.assertEqual(captured,[])
        finally:root.cleanup()

    def test_node22_and_actual_decoded_frame_positive(self):
        root,exe,runner,version,captured=self.fixture()
        try:
            v=m.verify(7890,executable=str(exe),runner=runner,
                       version_runner=version)
            self.assertEqual(v["state"],"PASS")
            self.assertEqual(v["reason"],"youtube_first_video_frame_decoded")
            self.assertEqual(len(captured),2)
            download=captured[0][0]
            self.assertEqual(download[download.index("--proxy")+1],
                             "http://127.0.0.1:7890")
            self.assertIn("--test",download)
            self.assertTrue(captured[0][1]["start_new_session"])
            self.assertIn("--no-cache-dir",download)
            self.assertIn("--ignore-config",download)
            self.assertIn("--downloader",download)
            self.assertEqual(captured[0][1]["cwd"],captured[1][1]["cwd"])
            self.assertTrue(str(captured[0][1]["cwd"]).startswith("/dev/shm/"))
            self.assertNotIn("HTTP_PROXY",captured[0][1]["env"])
            self.assertNotIn("NO_PROXY",captured[0][1]["env"])
        finally:root.cleanup()

    def test_downloader_failure_is_unknown(self):
        root,exe,runner,version,captured=self.fixture(downloader_rc=1)
        try:
            v=m.verify(7890,executable=str(exe),runner=runner,
                       version_runner=version)
            self.assertEqual((v["state"],v["reason"]),
                             ("UNKNOWN","youtube_extractor_or_media_unavailable"))
        finally:root.cleanup()

    def test_no_media_bytes_is_unknown(self):
        root,exe,runner,version,captured=self.fixture(media=False)
        try:
            v=m.verify(7890,executable=str(exe),runner=runner,
                       version_runner=version)
            self.assertEqual(v["reason"],"youtube_video_file_unverified")
        finally:root.cleanup()

    def test_decoder_failure_cannot_promote(self):
        root,exe,runner,version,captured=self.fixture(decode=False)
        try:
            v=m.verify(7890,executable=str(exe),runner=runner,
                       version_runner=version)
            self.assertEqual(v["state"],"UNKNOWN")
            self.assertEqual(v["reason"],"youtube_video_decode_unverified")
        finally:root.cleanup()

    def test_invalid_port_never_launches(self):
        for port in (0,65536,-1,True,"7890"):
            self.assertEqual(m.verify(port)["reason"],"invalid_proxy_port")

    def test_timeout_is_unknown(self):
        root,exe,runner,version,captured=self.fixture()
        try:
            import subprocess
            def failed(*args,**kwargs):
                raise subprocess.TimeoutExpired(args[0],2)
            v=m.verify(7890,executable=str(exe),runner=failed,
                       version_runner=version)
            self.assertEqual(v["reason"],"youtube_media_probe_unavailable")
        finally:root.cleanup()

    def test_ambient_proxy_variables_removed(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"HTTP_PROXY":"http://evil.invalid",
                 "NO_PROXY":"*", "ALL_PROXY":"socks5://evil.invalid"},clear=False):
            e=m.restricted_env()
            self.assertNotIn("HTTP_PROXY",e)
            self.assertNotIn("NO_PROXY",e)
            self.assertNotIn("ALL_PROXY",e)

    def test_temp_file_cleaned_after_success(self):
        root,exe,runner,version,captured=self.fixture()
        try:
            result=m.verify(7890,executable=str(exe),runner=runner,
                            version_runner=version)
            self.assertEqual(result["state"],"PASS")
            self.assertFalse(Path(captured[0][1]["cwd"]).exists())
        finally:root.cleanup()


if __name__=="__main__":
    unittest.main()
