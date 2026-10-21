#!/usr/bin/env python3
"""Rootless engine-scoped 'best' candidate selection; no actual provider."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"src/awg-mihomo-unified-nodes.py"
spec=importlib.util.spec_from_file_location("unified_engine_best",PATH)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)
ROWS=[
    {"name":"HY2 healthy", "engine":"MIHOMO","basic_network":"NETWORK_OK"},
    {"name":"VLESS stale","engine":"XRAY","basic_network":"UNTESTED"},
    {"name":"VLESS current","engine":"XRAY","basic_network":"NETWORK_OK"},
    {"name":"VLESS second","engine":"XRAY","basic_network":"NETWORK_OK"},
]

class EngineBest(unittest.TestCase):
    def best(self,*args):
        capture=io.StringIO()
        with (mock.patch.object(m.os,"geteuid",return_value=0),
              mock.patch.object(m,"load_adapter",return_value=object()),
              mock.patch.object(m,"snapshots",return_value=([],"deadbeef",{},{})),
              mock.patch.object(m,"inventory",return_value=ROWS),
              mock.patch.object(sys,"argv",["unified","best",*args]),
              contextlib.redirect_stdout(capture)):
            m.command()
        return capture.getvalue().strip()
    def test_explicit_xray_skips_native_and_stale(self):
        self.assertEqual(self.best("--engine","XRAY"),"VLESS current")
    def test_xray_exclude_next_exact_profile(self):
        self.assertEqual(self.best("--engine","XRAY","--exclude","VLESS current"),"VLESS second")
    def test_auto_rotation_can_reach_all_xray_candidates(self):
        seen=set()
        for bucket in range(12):
            with mock.patch.object(m.time,"time",return_value=float(bucket*300)):
                seen.add(self.best("--engine","XRAY","--rotate"))
        self.assertEqual(seen,{"VLESS current","VLESS second"})

    def test_existing_default_preserves_provider_order(self):
        self.assertEqual(self.best(),"HY2 healthy")
    def test_mihomo_filter_excludes_xray(self):
        self.assertEqual(self.best("--engine","MIHOMO"),"HY2 healthy")
    def test_no_fresh_xray_refuses_to_nominate(self):
        with self.assertRaises(SystemExit):
            self.best("--engine","XRAY","--exclude","VLESS current","--exclude","VLESS second")
    def test_auto_dispatch_only_after_native_budget(self):
        source=(ROOT/"src/awg-mihomo-node-policy").read_text()
        body=source.split("failover_auto(){",1)[1].split("\n}\n",1)[0]
        self.assertIn('xray_visits=0 max_xray_visits=2 max_candidate_visits=3',body)
        self.assertIn('candidate_visits" -lt "$max_checks"',body)
        self.assertIn('local -a unified_args=(best --engine XRAY --rotate)',body)
        self.assertIn('max_candidate_visits=$((max_checks + max_xray_visits))',body)
        self.assertIn('xray_visits=$((xray_visits+1))',body)
        self.assertIn('for item in "${excludes[@]}"',body)

if __name__=="__main__":
    unittest.main()
