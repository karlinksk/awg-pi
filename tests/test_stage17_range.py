#!/usr/bin/env python3
"""Stage17: offline-only signed-URL restrictions, bounded range and decoder evidence."""
from pathlib import Path
import importlib.util
import socket
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/"src"/"awg-video-range-check.py"
spec=importlib.util.spec_from_file_location("awg_range17",path)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

VALID="https://rr1---sn-foo.googlevideo.com/videoplayback?sig=SECRET"
WEBM=b"\x1a\x45\xdf\xa3"+b"x"*4096


class RangeTests(unittest.TestCase):
    def test_refuse_non_googlevideo_hosts_and_unsafe_urls(self):
        for url in ("http://googlevideo.com/videoplayback",
                    "https://googlevideo.com.evil.invalid/videoplayback",
                    "https://127.0.0.1/videoplayback",
                    "https://user:pass@googlevideo.com/videoplayback",
                    "https://googlevideo.com:8080/videoplayback",
                    "https://foo.googlevideo.com/private",
                    "https://foo.googlevideo.com.evil.com/videoplayback",
                    "https://foo.googlevideo.com/videoplayback"+("x"*20000)):
            self.assertFalse(m.safe_media_url(url),url[:40])
        self.assertTrue(m.safe_media_url(VALID))

    def test_redirect_to_non_media_host_rejected(self):
        handler=m.SafeRedirects()
        import urllib.request
        req=urllib.request.Request(VALID)
        with self.assertRaises(ValueError):
            handler.redirect_request(req,None,302,"found",{},"https://example.com/")

    def test_range_parameters_and_cap_are_enforced(self):
        from unittest.mock import patch
        with patch.object(m.urllib.request,"build_opener") as build:
            class FakeResponse:
                status=206
                headers={"Content-Range":"bytes 0-4095/999999"}
                def geturl(self):return VALID
                def read(self,n):
                    self.bytes_requested=n
                    return WEBM
                def __enter__(self):return self
                def __exit__(self,*args):pass
            response=FakeResponse()
            build.return_value.open.return_value=response
            data=m.fetch_range(17891,VALID,cap=8192)
            self.assertEqual(data,WEBM)
            self.assertEqual(response.bytes_requested,8193)
            req=build.return_value.open.call_args.args[0]
            self.assertEqual(req.get_header("Range"),"bytes=0-8191")
            self.assertEqual(req.get_header("Accept-encoding"),"identity")
        for port in (0,65536,"17891",True):
            with self.assertRaises(ValueError):m.fetch_range(port,VALID)
        with self.assertRaises(ValueError):
            m.fetch_range(17891,VALID,cap=m.RANGE_CAP+1)

    def test_large_or_fake_range_is_rejected(self):
        with patch.object(m.urllib.request,"build_opener") as build:
            class Fake:
                status=206
                headers={"Content-Range":"bytes 0-499/999999"}
                def geturl(self):return VALID
                def read(self,n):return b"A"*(n+1)
                def __enter__(self):return self
                def __exit__(self,*a):pass
            build.return_value.open.return_value=Fake()
            with self.assertRaises(ValueError):
                m.fetch_range(17891,VALID,cap=500)
            build.return_value.open.return_value.read=lambda n:b"<html>"+b"!"*200
            with self.assertRaises(ValueError):
                m.fetch_range(17891,VALID,cap=500)

    def test_reject_range_not_starting_at_zero(self):
        with patch.object(m.urllib.request,"build_opener") as build:
            class Fake:
                status=206
                headers={"Content-Range":"bytes 100-499/1000000"}
                def geturl(self):return VALID
                def read(self,n):
                    self.fail_read=True
                    return WEBM
                def __enter__(self):return self
                def __exit__(self,*a):pass
            obj=Fake()
            build.return_value.open.return_value=obj
            with self.assertRaises(ValueError):
                m.fetch_range(17891,VALID,cap=8192)
            self.assertFalse(hasattr(obj,"fail_read"))

    def test_proxy_bypass_with_no_proxy_all_still_connects_local(self):
        import os
        captured=[]
        with socket.socket() as server:
            server.bind(("127.0.0.1",0))
            server.listen(1)
            server.settimeout(2)
            port=server.getsockname()[1]
            def serve():
                try:
                    conn,_=server.accept()
                    with conn:
                        captured.append(conn.recv(2048))
                        conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length:0\r\n\r\n")
                except OSError:
                    pass
            thr=threading.Thread(target=serve)
            thr.start()
            with patch.dict(os.environ,{"NO_PROXY":"*","no_proxy":"*"}):
                try:m.fetch_range(port,VALID,timeout=1)
                except Exception:pass
            thr.join(timeout=3)
        self.assertTrue(captured)
        self.assertIn(b"CONNECT rr1---sn-foo.googlevideo.com:443",captured[0])

    def test_bounded_url_resolution_and_decoded_frame(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp:
            yt=Path(tmp)/"yt-dlp";yt.write_text("fixture")
            ff=Path(tmp)/"ffmpeg";ff.write_text("fixture")
            calls=[]
            def runner(args,**kw):
                calls.append((args,kw))
                if "--get-url" in args:
                    return types.SimpleNamespace(returncode=0,
                                                 stdout=(VALID+"\n").encode(),stderr=b"")
                return types.SimpleNamespace(returncode=0,
                                             stdout=b"frame=1\nprogress=end\n",stderr=b"")
            with patch.object(m.shutil,"which",return_value="/dev/shm/awg-stage15/bin/node"):
                result=m.verify(17891,executable=str(yt),ffmpeg=str(ff),runner=runner,
                                version_runner=lambda *a,**kw:types.SimpleNamespace(
                                    returncode=0,stdout="v22.16.0"),
                                fetcher=lambda p,url,**kw:WEBM)
            self.assertEqual(result["state"],"PASS")
            self.assertIn("--get-url",calls[0][0])
            self.assertNotIn("--test",calls[0][0])
            self.assertEqual(len(calls),2)
            self.assertTrue(all(x[1]["start_new_session"] for x in calls))
            self.assertTrue(all(x[1]["preexec_fn"] is m.limited_child for x in calls))
            self.assertFalse(Path(calls[0][1]["cwd"]).exists())

    def test_signed_media_url_does_not_escape_error(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp:
            yt=Path(tmp)/"yt";yt.write_text("x")
            ff=Path(tmp)/"ffmpeg";ff.write_text("x")
            def fake(args,**kw):
                return types.SimpleNamespace(returncode=0,stdout=(VALID+"\n").encode())
            with patch.object(m.shutil,"which",return_value="/dev/shm/node"):
                result=m.verify(17891,executable=str(yt),ffmpeg=str(ff),
                                runner=fake,fetcher=lambda *a,**kw:
                                (_ for _ in ()).throw(
                                    ValueError("URL="+VALID+"?secret=123")),
                                version_runner=lambda *a,**kw:types.SimpleNamespace(
                                    returncode=0,stdout="v22.16.0"))
            self.assertNotIn("SECRET",str(result))
            self.assertNotIn("123",str(result))
            self.assertEqual(result["state"],"UNKNOWN")

    def test_ffmpeg_failure_reason_codes_no_stderr_leak(self):
        self.assertEqual(m.decode_reason(1,b"moov atom not found URL=PRIVATE"),
                         "youtube_initial_fragment_incomplete")
        self.assertEqual(m.decode_reason(1,b"Decoder not found secret=PRIVATE"),
                         "youtube_video_codec_unsupported")
        self.assertEqual(m.decode_reason(1,b"totally unknown KEY=SECRET"),
                         "youtube_video_decode_unverified")
        self.assertEqual(m.decode_reason(0,b""),
                         "youtube_no_decoded_frame")

    def test_unit_and_operator_one_candidate_proof(self):
        unit=(ROOT/"units"/"awg-stage17-media@.service").read_text()
        driver=(ROOT/"scripts"/"awg-stage17-run-once.sh").read_text()
        for a in ("IPAddressDeny=any","IPAddressAllow=localhost",
                  "InaccessiblePaths=/var/lib/awg-pbr /etc/awg-pbr /run/awg-pbr"):
            self.assertIn(a,unit)
        self.assertNotIn("\n[Install]\n",unit)
        self.assertIn("--proxy-port %i --range",unit)
        self.assertIn("PORTS=(17891)",driver)
        self.assertIn("--target shadowsocks-27307",driver)
        self.assertNotIn("PORTS=(17891 17892)",driver)


if __name__=="__main__":
    unittest.main()
