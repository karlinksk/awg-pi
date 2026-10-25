#!/usr/bin/env python3
"""Bounded browser-session Stage20 path tests, synthetic only."""
import argparse
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

S=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-smart"
loader=importlib.machinery.SourceFileLoader("browser_session_test",str(S))
spec=importlib.util.spec_from_loader(loader.name,loader)
smart=importlib.util.module_from_spec(spec)
loader.exec_module(smart)

class MockProcess:
    terminated=False
    def poll(self): return None
    def terminate(self): self.terminated=True
    def wait(self,timeout=4): return 0
    def kill(self): self.terminated=True

class BrowserSessionTests(unittest.TestCase):
    def helper(self, unsafe=False):
        return types.SimpleNamespace(
            read_provider=lambda p:[{"name":"node-1","server":"93.184.216.34","port":443}],
            choose_free_port=lambda :19991,
            make_probe_config=lambda nodes,mixed,ctl:({
                "mixed-port":mixed,"allow-lan":unsafe,"bind-address":"127.0.0.1",
                "external-controller":"127.0.0.1:19991","proxies":[],
                "rules":[]},[{"probe_name":"AWG-PROBE-000001"}]),
            controller_request=lambda port,url,**k:{"proxies":{"AWG-PROBE-000001":{}}},
            select_probe=lambda port,name:None)

    def execute(self,seconds=60,unsafe=False,node="node-1"):
        process=MockProcess()
        clock=iter([0,1,2,3,65,128,260])
        def tick():
            return next(clock)
        with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp:
            with patch.object(smart.os,"geteuid",return_value=0), \
                 patch.object(smart,"STATE_DIR",Path(tmp)), \
                 patch.object(smart,"verify_candidate_direct",return_value=True), \
                 patch.object(smart,"load_pool_code",return_value=self.helper(unsafe)), \
                 patch.object(smart.subprocess,"Popen",return_value=process), \
                 patch.object(smart.time,"monotonic",side_effect=tick), \
                 patch.object(smart.time,"sleep",return_value=None):
                smart.browser_session(argparse.Namespace(seconds=seconds,node=node))
        return process

    def test_completes_synthetic_session_and_cleans_up(self):
        self.assertTrue(self.execute().terminated)

    def test_rejects_unsafe_listener(self):
        with self.assertRaisesRegex(RuntimeError,"unsafe browser listener"):
            self.execute(unsafe=True)

    def test_rejects_under_and_over_lease(self):
        for ttl in (1,59,601,3600):
            with self.subTest(ttl=ttl),self.assertRaises(RuntimeError):
                self.execute(seconds=ttl)

    def test_not_root_denied_before_provider_access(self):
        with patch.object(smart.os,"geteuid",return_value=1000):
            with self.assertRaisesRegex(RuntimeError,"requires root"):
                smart.browser_session(argparse.Namespace(seconds=600,node="node-1"))

    def test_duplicate_or_missing_node_is_denied(self):
        with self.assertRaisesRegex(RuntimeError,"ambiguous or missing"):
            self.execute(node="missing")

    def test_stage20_browser_does_not_modify_live_selection(self):
        text=S.read_text()
        start=text.split("def browser_session(args):",1)[1].split("\ndef shadow_scan(",1)[0]
        self.assertNotIn("node select-auto",start)
        self.assertNotIn("systemctl",start)
        self.assertNotIn("nft ",start)
        self.assertIn("verify_candidate_direct",start)
        self.assertIn("BROWSER_SESSION_PRODUCTION_MODIFIED=false",start)
        self.assertIn("instance.terminate()",start)

if __name__=="__main__":
    unittest.main()
