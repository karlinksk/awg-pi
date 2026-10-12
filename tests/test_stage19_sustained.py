#!/usr/bin/env python3
"""Stage19 offline tests: 60s decode with finite limits and strictly nonproduction."""
from pathlib import Path
from unittest.mock import patch
import importlib.util
import sys
import tempfile
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
def mod(filename,name):
    sp=importlib.util.spec_from_file_location(name,ROOT/"src"/filename)
    m=importlib.util.module_from_spec(sp);sys.modules[name]=m;sp.loader.exec_module(m)
    return m
m=mod("awg-video-sustained-check.py","stage19_sustained")
side=mod("awg-media-sidecar.py","stage19_sidecar")
URL="https://example-x.googlevideo.com/videoplayback?sig=SECRET"
WEBM=b"\x1a\x45\xdf\xa3"+b"x"*65536


class Stage19(unittest.TestCase):
    def verify_fixture(self,*,frames=1400,elapsed=60000000,
                       result=0,extract=0,stderr=b""):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp:
            yt=Path(tmp)/"yt-dlp";yt.write_text("mock")
            ff=Path(tmp)/"ffmpeg";ff.write_text("mock")
            invoked=[]
            def runner(args,**opts):
                invoked.append((args,opts))
                if "--get-url" in args:
                    return types.SimpleNamespace(returncode=extract,
                        stdout=(URL+"\n").encode(),stderr=b"")
                return types.SimpleNamespace(returncode=result,
                    stdout=f"frame={frames}\nout_time_us={elapsed}\nprogress=end\n".encode(),
                    stderr=stderr)
            with patch.object(m.shutil,"which",return_value="/dev/shm/awg-stage15/bin/node"):
                observation=m.verify(17891,executable=str(yt),ffmpeg=str(ff),
                    runner=runner,version_runner=lambda *a,**kw:
                    types.SimpleNamespace(returncode=0,stdout="v22.16.0"),
                    fetcher=lambda *a,**kw:WEBM)
            self.assertNotIn("SECRET",str(observation))
            self.assertTrue(all(x[1]["start_new_session"] for x in invoked))
            self.assertTrue(all(x[1]["preexec_fn"] is m.limited_child for x in invoked))
            self.assertTrue(all(not Path(x[1]["cwd"]).exists() for x in invoked))
            return observation,invoked

    def test_long_film_id_verified_format_and_budget(self):
        self.assertEqual(m.VIDEO_URL,"https://www.youtube.com/watch?v=aqz-KE-bpKQ")
        self.assertEqual(m.RANGE_CAP,12*1024*1024)
        self.assertEqual(m.MIN_DURATION_US,59000000)
        self.assertEqual(m.MIN_DECODED_FRAMES,900)
        got,calls=self.verify_fixture()
        self.assertEqual(got["state"],"PASS")
        self.assertEqual(got["reason"],"youtube_60s_video_decoded")
        self.assertNotIn("--test",calls[0][0])
        self.assertIn("bestvideo[height<=240]",calls[0][0])
        self.assertIn("-t",calls[1][0])
        self.assertIn("60",calls[1][0])
        self.assertIn("-protocol_whitelist",calls[1][0])
        self.assertIn("file,pipe,crypto",calls[1][0])

    def test_less_than_59_seconds_is_unknown(self):
        got,_=self.verify_fixture(elapsed=58000000)
        self.assertEqual((got["state"],got["reason"]),
                         ("UNKNOWN","youtube_sustained_duration_insufficient"))

    def test_fewer_than_900_frames_is_unknown(self):
        got,_=self.verify_fixture(frames=899)
        self.assertEqual(got["state"],"UNKNOWN")

    def test_nonzero_ffmpeg_and_private_stderr_never_pass(self):
        got,_=self.verify_fixture(result=1,stderr=b"Truncated private=SECRET")
        self.assertEqual(got["reason"],"youtube_initial_fragment_incomplete")
        self.assertNotIn("SECRET",str(got))

    def test_no_url_no_frame_and_no_leak(self):
        got,calls=self.verify_fixture(extract=1)
        self.assertEqual(got["state"],"UNKNOWN")
        self.assertEqual(len(calls),1)

    def test_force_proxy_is_reused(self):
        self.assertTrue(m.safe_media_url(URL))
        self.assertFalse(m.safe_media_url("https://googlevideo.com.evil.test/videoplayback"))
        with self.assertRaises(ValueError):
            m.fetch_range(0,URL)
        with self.assertRaises(ValueError):
            m.fetch_range(17891,URL,cap=m.RANGE_CAP+1)

    def test_bad_content_range_not_accepted(self):
        with patch.object(m.urllib.request,"build_opener") as factory:
            class BadResponse:
                status=206
                headers={"Content-Range":"bytes 100-10000/20000000"}
                def geturl(self):return URL
                def __enter__(self):return self
                def __exit__(self,*exc):pass
                def read(self,n):
                    raise AssertionError("must never read wrong range")
            factory.return_value.open.return_value=BadResponse()
            with self.assertRaises(ValueError):
                m.fetch_range(17891,URL,cap=2048)

    def test_sidecar_only_60s_result_is_success(self):
        good=types.SimpleNamespace(verify=lambda *a,**k:{
            "state":"PASS","reason":"youtube_60s_video_decoded",
            "method":"video_frame_decode","shadow_only":True})
        bad=types.SimpleNamespace(verify=lambda *a,**k:{
            "state":"PASS","reason":"youtube_24_video_frames_decoded",
            "method":"video_frame_decode","shadow_only":True})
        with patch.object(side,"preflight",return_value=""):
            self.assertEqual(side.summarize(17891,frame=good,use_sustained=True)["state"],"PASS")
            self.assertEqual(side.summarize(17891,frame=bad,use_sustained=True)["state"],"UNKNOWN")

    def test_worker_with_root_or_credential_env_denied(self):
        fake=types.SimpleNamespace(verify=lambda *a,**k:{
            "state":"PASS","reason":"youtube_60s_video_decoded",
            "method":"video_frame_decode","shadow_only":True})
        self.assertEqual(side.summarize(17891,frame=fake,use_sustained=True,
                         euid=0,environ={})["state"],"UNKNOWN")
        self.assertEqual(side.summarize(17891,frame=fake,use_sustained=True,
                         euid=1000,environ={"CREDENTIALS_DIRECTORY":"/x"})["state"],"UNKNOWN")

    def test_sustained_unit_and_operator_are_ephemeral(self):
        unit=(ROOT/"units"/"awg-stage19-media@.service").read_text()
        sh=(ROOT/"scripts"/"awg-stage19-run-once.sh").read_text()
        self.assertIn("IPAddressDeny=any",unit)
        self.assertIn("IPAddressAllow=localhost",unit)
        self.assertIn("LoadCredential=\n",unit)
        self.assertIn("InaccessiblePaths=/var/lib/awg-pbr /etc/awg-pbr /run/awg-pbr",unit)
        self.assertNotIn("\n[Install]",unit)
        self.assertIn("--sustained",unit)
        self.assertIn("PORTS=(17891)",sh)
        self.assertIn("for round in 1; do",sh)
        self.assertIn("for index in 0; do",sh)
        self.assertIn("GIT_OPTIONAL_LOCKS=0",sh)
        self.assertIn("trap trap_cleanup EXIT",sh)
        self.assertNotIn("awg-stage18-media@",sh)
if __name__=="__main__":unittest.main()
