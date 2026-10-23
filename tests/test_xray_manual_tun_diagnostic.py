#!/usr/bin/env python3
"""Failure classification for REAL Pi-bound TUN HTTPS; no live network."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"src/awg-xray-manual-switch.py"
spec=importlib.util.spec_from_file_location("manual_tun_diagnostic",SRC)
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)

class HttpsObservabilityContract(unittest.TestCase):
    def do_probe(self, rc, code):
        with mock.patch.object(mod.subprocess,"run",
                return_value=subprocess.CompletedProcess(["curl"],rc,code,"secret-leak-sentinel")) as call:
            with mock.patch.dict(mod.os.environ,
                    {"HTTPS_PROXY":"http://some-private-endpoint",
                     "http_proxy":"http://some-private-endpoint"}):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    result=mod.https_ok("tun")
        args=call.call_args.args[0]
        kwargs=call.call_args.kwargs
        self.assertIn("--interface",args)
        self.assertEqual(args[args.index("--interface")+1],"mihomo0")
        self.assertIn("--noproxy",args)
        self.assertEqual(args[args.index("--noproxy")+1],"*")
        self.assertNotIn("HTTPS_PROXY",kwargs["env"])
        self.assertNotIn("http_proxy",kwargs["env"])
        self.assertNotIn("private",output.getvalue())
        self.assertNotIn("secret",mod._LAST_HTTPS_PROBE_CLASS)
        return result

    def test_only_openai_401_is_success(self):
        self.assertTrue(self.do_probe(0,"401"))
        self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"HTTP_401")
        self.assertFalse(self.do_probe(0,"403"))
        self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"HTTP_403")
        self.assertFalse(self.do_probe(0,"200"))
        self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"HTTP_200")

    def test_empty_or_invalid_code_fails_closed(self):
        for value in ("","connection refused","401PRIVATE","0"):
            with self.subTest(value=value):
                self.assertFalse(self.do_probe(0,value))
                self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"HTTP_INVALID")

    def test_timeout_and_tls_errors_expose_only_code(self):
        self.assertFalse(self.do_probe(28,"000"))
        self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"CURL_EXIT_28")
        self.assertFalse(self.do_probe(60,"000"))
        self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"CURL_EXIT_60")
        self.assertFalse(self.do_probe(99,"000"))
        self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"CURL_EXIT_OTHER")

    def test_mixed_proxy_is_diagnostic_only(self):
        with mock.patch.object(mod.subprocess,"run",return_value=
             subprocess.CompletedProcess(["curl"],0,"401","")) as c:
            self.assertTrue(mod.https_ok("mixed"))
            args=c.call_args.args[0]
            self.assertEqual(args[args.index("--proxy")+1],"http://127.0.0.1:7890")
            self.assertNotIn("--interface",args)
            self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"HTTP_401")

    def test_mixed_timeout_never_skips_tun(self):
        with mock.patch.object(mod.subprocess,"run",return_value=
             subprocess.CompletedProcess(["curl"],28,"000","")):
            self.assertFalse(mod.https_ok("mixed"))
            self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"CURL_EXIT_28")
        source=SRC.read_text().split("def apply(index):",1)[1].split(
            "def last_failure():",1)[0]
        block=source.split('checkpoint(path,state,"SWITCH_TUN")',1)[1]
        self.assertIn('https_ok("mixed")',block)
        self.assertIn('state["mixed_probe_last"]=_LAST_HTTPS_PROBE_CLASS',block)
        self.assertLess(block.index('https_ok("mixed")'),block.index("native_tun_proof()"))
        self.assertNotIn("if mixed_ok:",block)
        self.assertIn('"mixed_probe_last"',SRC.read_text())

    def test_unknown_probe_mode_fails_closed(self):
        with mock.patch.object(mod.subprocess,"run") as p:
            self.assertFalse(mod.https_ok("unknown"))
            p.assert_not_called()

    def test_process_timeout_and_os_error(self):
        with mock.patch.object(mod.subprocess,"run",
                               side_effect=subprocess.TimeoutExpired(["curl"],23)):
            self.assertFalse(mod.https_ok("tun"))
            self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"PROCESS_TIMEOUT")
        with mock.patch.object(mod.subprocess,"run",side_effect=OSError("private path")):
            self.assertFalse(mod.https_ok("tun"))
            self.assertEqual(mod._LAST_HTTPS_PROBE_CLASS,"PROCESS_ERROR")

    def test_native_tun_rejects_both_failed_checks_without_widening_gate(self):
        with mock.patch.object(mod,"routing_ok",return_value=True) as route,\
             mock.patch.object(mod,"https_ok",side_effect=[False,False]) as probe,\
             mock.patch.object(mod.time,"sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError,"NATIVE_TUN_HTTPS_UNVERIFIED"):
                mod.native_tun_proof()
        self.assertEqual(probe.call_count,2)
        sleep.assert_called_once_with(1)
        self.assertEqual(route.call_count,1)

    def test_diagnostic_stored_before_native_rollback(self):
        src=SRC.read_text()
        for name in ("def native_return(name):","def apply(index):"):
            section=src.split(name,1)[1].split("def ",1)[0]
            self.assertIn('state["tun_probe_last"]=_LAST_HTTPS_PROBE_CLASS',section)
            self.assertLess(section.index('state["tun_probe_last"]'),section.index('restore(')
                if name=="def apply(index):" else section.index('restore_native('))
        self.assertIn('"tun_probe_last"',src)
        self.assertIn('re.fullmatch(r"[A-Z][A-Z0-9_]',src)
        self.assertNotIn("p.stderr",src[src.index("def https_ok(via):"):src.index("def prove_local_xray():")])

if __name__=="__main__":unittest.main()
