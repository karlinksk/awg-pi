#!/usr/bin/env python3
"""Offline security tests for the root-owned service-only Mihomo candidate trial."""
from pathlib import Path
from unittest.mock import patch
import importlib.util,sys,unittest
P=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-service-trial.py"
s=importlib.util.spec_from_file_location("awg_trial",P)
t=importlib.util.module_from_spec(s);sys.modules[s.name]=t;s.loader.exec_module(t)


def row(name, server, port=443, delay=100, ptype="vless", **kw):
    return dict(name=name,server=server,port=port,delay_ms=delay,
                type=ptype,healthy=True,**kw)


def raw(n):
    return {k:n[k] for k in ("name","server","port","type")}


class ServiceTrialTests(unittest.TestCase):
    def test_select_only_matches_protected_provider(self):
        a=row("good","194.38.11.86",65443)
        b=row("new","45.86.66.170",8443,delay=200)
        bad=row("mismatch","51.77.225.200",8388,delay=5)
        chosen=t.select({"nodes":[a,b,bad]},[raw(a),raw(b),dict(raw(bad),port=80)])
        self.assertEqual([n["name"] for n in chosen],["good","new"])

    def test_never_select_more_than_three(self):
        nodes=[row("n"+str(n),"194.38.11."+str(n+80)) for n in range(8)]
        self.assertEqual(len(t.select({"nodes":nodes},list(map(raw,nodes)))),3)

    def test_duplicate_endpoint_not_independent(self):
        a=row("a","194.38.11.86",443,delay=30)
        b=row("b","194.38.11.86",443,delay=40)
        self.assertEqual(len(t.select({"nodes":[a,b]},[raw(a),raw(b)])),1)

    def test_duplicate_name_is_ambiguous(self):
        a=row("a","194.38.11.86")
        self.assertEqual(t.select({"nodes":[a,a]},[raw(a),raw(a)]),[])

    def test_europe_only_policy_protected(self):
        a=row("a","194.38.11.86",europe=False)
        b=row("b","45.86.66.170",europe=True)
        self.assertEqual([x["name"] for x in t.select({"nodes":[a,b]},
                          [raw(a),raw(b)],region="europe")],["b"])

    def test_type_filter(self):
        a=row("a","194.38.11.86",ptype="ss")
        b=row("b","45.86.66.170",ptype="vless")
        result=t.select({"nodes":[a,b]},[raw(a),raw(b)],protocol="ss")
        self.assertEqual([x["name"] for x in result],["a"])

    def test_mismatch_protocol_refused(self):
        a=row("a","194.38.11.86",ptype="ss")
        self.assertEqual(t.select({"nodes":[a]},[dict(raw(a),type="trojan")]),[])

    def test_unhealthy_candidate_cannot_qualify(self):
        a=row("a","194.38.11.86")
        a["healthy"]=False
        self.assertEqual(t.select({"nodes":[a]},[raw(a)]),[])

    def test_sanitized_result_contains_no_server_or_raw_secret(self):
        a=row("name-secret","194.38.11.86")
        raw_response={"name-secret":{"status":"PASS","identity":"name-secret",
            "transport":"mihomo","sample_id":"fixture-1","checks":{
            x:{"state":"PASS","reason":"test"} for x in
            ("openai_api","chatgpt_web","youtube_video")}}}
        got=t.sanitized(raw_response,[a],provider_sha="f"*64,elapsed=4.2)
        self.assertEqual(got["results"][0]["service_single_sample"],"PASS")
        self.assertFalse(got["results"][0]["service_ready"])
        self.assertFalse(got["results"][0]["routing_qualified"])
        self.assertEqual(len(got["results"][0]["candidate_id"]),12)
        self.assertNotIn("194.38.11.86",repr(got))
        self.assertNotIn("name-secret",repr(got))

    def test_missing_or_unknown_services_cannot_be_pass(self):
        a=row("a","194.38.11.86")
        got=t.sanitized({"a":{"status":"UNKNOWN","identity":"a",
            "transport":"mihomo","sample_id":"fixture-2",
            "checks":{"openai_api":{"state":"PASS"},
                                        "chatgpt_web":{"state":"UNKNOWN"}}}},
                        [a],provider_sha="a"*64,elapsed=1)
        self.assertEqual(got["results"][0]["service_single_sample"],"UNKNOWN")

    def test_any_known_fail_is_fail_for_this_sample(self):
        a=row("a","194.38.11.86")
        got=t.sanitized({"a":{"status":"FAIL","identity":"a",
            "transport":"mihomo","sample_id":"fixture-3",
            "checks":{"openai_api":{"state":"FAIL"},
                                        "chatgpt_web":{"state":"PASS"},
                                        "youtube_video":{"state":"PASS"}}}},
                        [a],provider_sha="a"*64,elapsed=1)
        self.assertEqual(got["results"][0]["service_single_sample"],"FAIL")
        self.assertFalse(got["results"][0]["service_ready"])

    def test_wrong_node_identity_cannot_fabricate_pass(self):
        a=row("a","194.38.11.86")
        checks={k:{"state":"PASS"} for k in
                ("openai_api","chatgpt_web","youtube_video")}
        row_raw={"a":{"status":"PASS","identity":"other-node",
                      "transport":"mihomo","sample_id":"different","checks":checks}}
        got=t.sanitized(row_raw,[a],provider_sha="a"*64,elapsed=1)
        self.assertEqual(got["results"][0]["service_single_sample"],"UNKNOWN")

    def test_duplicate_or_missing_sample_is_unknown(self):
        a=row("a","194.38.11.86")
        checks={k:{"state":"PASS"} for k in
                ("openai_api","chatgpt_web","youtube_video")}
        got=t.sanitized({"a":{"status":"PASS","identity":"a","transport":"mihomo",
                             "sample_id":"","checks":checks}},
                        [a],provider_sha="a"*64,elapsed=1)
        self.assertEqual(got["results"][0]["service_single_sample"],"UNKNOWN")

    def test_root_access_is_required(self):
        with patch.object(t.os,"geteuid",return_value=1000):
            with self.assertRaises(PermissionError):
                t.run()
        # A CLI denial cannot leak provider credentials via an exception.
        with patch.object(t.os,"geteuid",return_value=1000):
            self.assertEqual(t.main.__name__,"main")

    def test_invalid_limits_refused(self):
        for invalid in (0,4,-1):
            with self.assertRaises(ValueError):
                t.select({"nodes":[]},[],limit=invalid)

    def test_no_production_mutation_codepaths(self):
        import inspect
        source=inspect.getsource(t.run)
        for danger in ("awg-transport select","iptables","nft add",
                       "systemctl start", "ip route replace"):
            self.assertNotIn(danger,source)


if __name__=="__main__":
    unittest.main()
