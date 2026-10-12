#!/usr/bin/env python3
"""Offline Stage18: two independent 2MiB/24-frame checks remain SHADOW_ONLY."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import sys,tempfile,types,unittest

ROOT=Path(__file__).resolve().parents[1]
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"src"/path)
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m;spec.loader.exec_module(m)
    return m
m=load("awg-video-continuity-check.py","stage18_continuity")
side=load("awg-media-sidecar.py","stage18_media")
URL="https://rr5---sn-example.googlevideo.com/videoplayback?sig=SECRET"
WEBM=b"\x1a\x45\xdf\xa3"+b"x"*65536


class Stage18(unittest.TestCase):
    def trial(self,frames=24,decode_rc=0,stderr=b"",download_rc=0):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as temp:
            yt=Path(temp)/"yt-dlp";yt.write_text("stub")
            ff=Path(temp)/"ffmpeg";ff.write_text("stub")
            calls=[]
            def runner(args,**kw):
                calls.append((args,kw))
                if "--get-url" in args:
                    return types.SimpleNamespace(returncode=download_rc,
                        stdout=(URL+"\n").encode(),stderr=b"")
                return types.SimpleNamespace(returncode=decode_rc,
                    stdout=f"frame={frames}\nprogress=end\n".encode(),
                    stderr=stderr)
            with patch.object(m.shutil,"which",return_value="/dev/shm/awg-stage15/bin/node"):
                observed=m.verify(17891,executable=str(yt),
                    ffmpeg=str(ff),runner=runner,
                    version_runner=lambda *a,**kw:types.SimpleNamespace(
                        returncode=0,stdout="v22.16.0"),
                    fetcher=lambda port,url,**kw:WEBM)
            self.assertTrue(all(c[1]["start_new_session"] for c in calls))
            self.assertTrue(all(c[1]["preexec_fn"] is m.limited_child for c in calls))
            self.assertTrue(all(c[1]["cwd"].startswith("/dev/shm/") for c in calls))
            self.assertTrue(all(not Path(c[1]["cwd"]).exists() for c in calls))
            self.assertNotIn(URL,str(observed))
            return observed,calls

    def test_24_frames_real_proof(self):
        got,calls=self.trial(frames=24)
        self.assertEqual(got["state"],"PASS")
        self.assertEqual(got["reason"],"youtube_24_video_frames_decoded")
        self.assertIn("24",calls[1][0])
        self.assertNotIn("--test",calls[0][0])
        self.assertEqual(m.RANGE_CAP,2097152)
        self.assertEqual(m.MIN_DECODED_FRAMES,24)

    def test_23_frames_cannot_pass(self):
        got,_=self.trial(frames=23)
        self.assertEqual(got["state"],"UNKNOWN")
        self.assertEqual(got["reason"],"youtube_insufficient_decoded_frames")

    def test_0_frames_cannot_pass(self):
        got,_=self.trial(frames=0)
        self.assertEqual(got["state"],"UNKNOWN")

    def test_nonzero_ffmpeg_exit_cannot_pass(self):
        got,_=self.trial(frames=24,decode_rc=1,
                         stderr=b"partial file secretSignedUrl=PRIVATE")
        self.assertEqual(got["state"],"UNKNOWN")
        self.assertEqual(got["reason"],"youtube_initial_fragment_incomplete")
        self.assertNotIn("PRIVATE",str(got))

    def test_extractor_failure_no_fake_pass(self):
        got,calls=self.trial(download_rc=1)
        self.assertEqual(got["state"],"UNKNOWN")
        self.assertEqual(got["reason"],"youtube_metadata_or_extractor_unavailable")
        self.assertEqual(len(calls),1)

    def test_sidecar_accepts_only_continuity_specific_pass(self):
        safe=types.SimpleNamespace(verify=lambda *a,**k:{
            "state":"PASS","reason":"youtube_24_video_frames_decoded",
            "method":"video_frame_decode","shadow_only":True})
        wrong=types.SimpleNamespace(verify=lambda *a,**k:{
            "state":"PASS","reason":"youtube_first_video_frame_decoded",
            "method":"video_frame_decode","shadow_only":True})
        with patch.object(side,"preflight",return_value=""):
            yes=side.summarize(17891,frame=safe,use_continuity=True)
            no=side.summarize(17891,frame=wrong,use_continuity=True)
        self.assertEqual(yes["state"],"PASS")
        self.assertEqual(no["state"],"UNKNOWN")
        self.assertFalse(yes["credentials_loaded"])
        self.assertFalse(yes["production_modified"])

    def test_root_or_credentials_rejected_even_with_good_decoder(self):
        good=types.SimpleNamespace(verify=lambda *a,**k:{"state":"PASS",
            "reason":"youtube_24_video_frames_decoded",
            "method":"video_frame_decode","shadow_only":True})
        self.assertEqual(side.summarize(17891,frame=good,use_continuity=True,
                         euid=0,environ={})["state"],"UNKNOWN")
        self.assertEqual(side.summarize(17891,frame=good,use_continuity=True,
                         euid=1000,environ={"CREDENTIALS_DIRECTORY":"/run/private"})["state"],"UNKNOWN")

    def test_git_readonly_during_sudo_trial(self):
        driver=(ROOT/'scripts'/'awg-stage18-run-once.sh').read_text()
        self.assertIn('GIT_OPTIONAL_LOCKS=0',driver)
        self.assertIn('git -C "$ROOT" status --porcelain',driver)

    def test_operator_script_and_media_unit_no_auto_enabling(self):
        script=(ROOT/"scripts"/"awg-stage18-run-once.sh").read_text()
        unit=(ROOT/"units"/"awg-stage18-media@.service").read_text()
        self.assertIn("for round in 1 2; do",script)
        self.assertIn("for index in 0; do",script)
        self.assertIn("systemctl stop \"awg-stage16-node@$port.service\"",script)
        self.assertIn('PORTS=(17891)',script)
        self.assertIn('NAMES=(shadowsocks-27307)',script)
        self.assertNotIn('PORTS=(17891 17892)',script)
        self.assertIn("IPAddressDeny=any",unit)
        self.assertIn("IPAddressAllow=localhost",unit)
        self.assertIn("--continuity",unit)
        self.assertIn("InaccessiblePaths=/var/lib/awg-pbr /etc/awg-pbr /run/awg-pbr",unit)
        self.assertNotIn("\n[Install]\n",unit)

if __name__=="__main__":unittest.main()
