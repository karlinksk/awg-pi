#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest

P=Path(__file__).resolve().parents[1]/"src"/"awg-xray-failover-contract.py"
spec=importlib.util.spec_from_file_location("failover_contract",P)
m=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=m
spec.loader.exec_module(m)
SHA="a"*64

class ContractTests(unittest.TestCase):
    def node(self, name, engine="XRAY", health="NETWORK_OK", sha=SHA):
        return m.Candidate(name,engine,health,sha)

    def test_uncertified_xray_cannot_activate(self):
        with self.assertRaises(m.Rejected):
            m.select_candidate("dead", [self.node("dead"),self.node("new")],SHA)

    def test_legacy_mihomo_candidate_retained(self):
        got=m.select_candidate("dead",[self.node("new","MIHOMO")],SHA)
        self.assertEqual(got.name,"new")

    def test_no_return_to_failed_original(self):
        got=m.select_candidate("dead",[self.node("dead"),self.node("new")],SHA,
                               xray_executor_certified=True)
        self.assertEqual(got.name,"new")

    def test_provider_credentials_rotated(self):
        with self.assertRaises(m.Rejected):
            m.select_candidate("dead",[self.node("new",sha="b"*64)],SHA,
                               xray_executor_certified=True)

    def test_network_unknown_is_not_pass(self):
        with self.assertRaises(m.Rejected):
            m.select_candidate("dead",[self.node("new",health="UNKNOWN_HTTP")],SHA,
                               xray_executor_certified=True)

    def test_bounded_candidates(self):
        options=[self.node("bad"+str(i),health="UNTESTED") for i in range(6)]
        options.append(self.node("working"))
        with self.assertRaises(m.Rejected):
            m.select_candidate("dead",options,SHA,xray_executor_certified=True)

    def test_commit_requires_every_guard(self):
        good=dict(original_failed="dead",selected="new",
                  independent_recovery=True,tun_postcheck=True,
                  route_100=True,route_101=True,transit_guard=True)
        self.assertTrue(m.validate_xray_commit(**good))
        for field in ("independent_recovery","tun_postcheck","route_100",
                      "route_101","transit_guard"):
            bad=dict(good);bad[field]=False
            with self.subTest(field=field),self.assertRaises(m.Rejected):
                m.validate_xray_commit(**bad)
        good["selected"]="dead"
        with self.assertRaises(m.Rejected):
            m.validate_xray_commit(**good)

if __name__=="__main__":
    unittest.main()
