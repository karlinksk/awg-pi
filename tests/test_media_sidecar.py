#!/usr/bin/env python3
"""Offline stage15 tests: NO provider credentials in separate media worker."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import types, unittest
P=Path(__file__).resolve().parents[1]/"src"/"awg-media-sidecar.py"
spec=importlib.util.spec_from_file_location("awg_media_sidecar",P)
import sys
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)


class MediaSidecarTests(unittest.TestCase):
    def test_root_never_allowed(self):
        self.assertEqual(m.preflight(euid=0,environ={}),"root_worker_forbidden")

    def test_credential_environment_always_refused(self):
        self.assertEqual(m.preflight(euid=1001,
                        environ={"CREDENTIALS_DIRECTORY":"/run/credentials/key"}),
                         "service_credentials_forbidden")

    def test_runner_does_not_bypass_auth_checks(self):
        with patch.object(m,"preflight",return_value="service_credentials_forbidden"):
            fake=types.SimpleNamespace(verify=lambda *a,**k:{
                "state":"PASS","reason":"youtube_first_video_frame_decoded",
                "method":"video_frame_decode","shadow_only":True})
            o=m.summarize(7890,frame=fake)
        self.assertEqual(o["state"],"UNKNOWN")
        self.assertFalse(o["credentials_loaded"])

    def test_only_actual_first_frame_decoded_can_be_pass(self):
        with patch.object(m,"preflight",return_value=""):
            fake=types.SimpleNamespace(verify=lambda *a,**k:{
                "state":"PASS","reason":"youtube_first_video_frame_decoded",
                "method":"video_frame_decode","shadow_only":True})
            o=m.summarize(7890,frame=fake)
        self.assertEqual(o["state"],"PASS")
        self.assertFalse(o["production_modified"])
        self.assertFalse(o["credentials_loaded"])

    def test_unverified_http_206_does_not_fake_frame(self):
        with patch.object(m,"preflight",return_value=""):
            fake=types.SimpleNamespace(verify=lambda *a,**k:{
                "state":"PASS","reason":"http206",
                "method":"network","shadow_only":True})
            o=m.summarize(7890,frame=fake)
        self.assertEqual(o["state"],"UNKNOWN")

    def test_untrusted_exception_does_not_leak_node_data(self):
        def raise_sensitive(*args,**kwargs):
            raise RuntimeError("proxy-password=PRIVATE media-url=SIGNED")
        with patch.object(m,"preflight",return_value=""):
            result=m.summarize(7890,frame=types.SimpleNamespace(verify=raise_sensitive))
        self.assertNotIn("PRIVATE",str(result))
        self.assertNotIn("SIGNED",str(result))
        self.assertEqual(result["reason"],"media_unverified")

    def test_invalid_port_never_runs_frame(self):
        with patch.object(m,"preflight",return_value=""):
            fake=types.SimpleNamespace(verify=lambda *a,**k:
                self.fail("should not run"))
            self.assertEqual(m.summarize(0,frame=fake)["reason"],
                             "invalid_proxy_port")

    def test_unit_is_unprivileged_credential_free_and_network_local(self):
        unit=Path(__file__).resolve().parents[1]/"units"/"awg-media-sidecar@.service"
        text=unit.read_text()
        for item in ("DynamicUser=yes","IPAddressDeny=any",
                     "IPAddressAllow=localhost","NoNewPrivileges=yes",
                     "InaccessiblePaths=/var/lib/awg-pbr /etc/awg-pbr /run/awg-pbr",
                     "ProtectSystem=strict","MemoryMax=384M"):
            self.assertIn(item,text)
        self.assertNotIn("LoadCredential=selection:",text)
        self.assertNotIn("\n[Install]\n",text)

    def test_frame_checker_decoding_also_runs_in_killable_session(self):
        import importlib.util
        path=Path(__file__).resolve().parents[1]/"src"/"awg-youtube-frame-check.py"
        spec=importlib.util.spec_from_file_location("awg_stage15_frame_guard",path)
        module=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=module;spec.loader.exec_module(module)
        import tempfile
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp:
            exe=Path(tmp)/"yt-dlp";exe.write_text("test")
            fakeff=Path(tmp)/"ffmpeg";fakeff.write_text("test")
            calls=[]
            def runner(args,**kw):
                calls.append(kw)
                if "--ignore-config" in args:
                    out=args[args.index("--output")+1].replace("%(ext)s","mp4")
                    Path(out).write_bytes(b"\0\0\0\x18ftypisom"+b"x"*350)
                    return types.SimpleNamespace(returncode=0)
                return types.SimpleNamespace(returncode=0,stdout=b"frame=1\n")
            with patch.object(module.shutil,"which",return_value="/usr/bin/node"):
                result=module.verify(7890,executable=str(exe),ffmpeg=str(fakeff),
                    runner=runner,
                    version_runner=lambda *a,**k:types.SimpleNamespace(
                        returncode=0,stdout="v22.16.0"))
            self.assertEqual(result["state"],"PASS")
            self.assertTrue(all(c.get("start_new_session") is True for c in calls))
            self.assertTrue(all(c.get("preexec_fn") is module.limited_child for c in calls))


if __name__=="__main__":
    unittest.main()
