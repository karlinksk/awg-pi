#!/usr/bin/env python3
"""Offline security tests for the nonroot credential-backed Mihomo candidate trial."""
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

    def test_real_pool_unhealthy_null_delays_do_not_break_sort(self):
        # Regression for Stage 13: out of ~1,869 scanned provider nodes
        # only ~249 are healthy; unhealthy rows have delay_ms=None.
        a=row("fast", "194.38.11.86", delay=320)
        b=row("slow", "45.86.66.170", delay=420)
        bad=[dict(row("down"+str(i),"198.51.100."+str(i+1)),
                  healthy=False,delay_ms=None) for i in range(8)]
        invalid={"name":"(invalid #12)","type":"invalid",
                 "server":"","port":0,"healthy":False,"delay_ms":None}
        result=t.select({"nodes":bad+[b,invalid,a]},
                        [raw(a),raw(b)])
        self.assertEqual([n["name"] for n in result],["fast","slow"])

    def test_yaml_numeric_string_port_is_normalized(self):
        a=row("yaml-port","194.38.11.86",port=65443)
        rec=raw(a)
        rec["port"]="65443"
        selected=t.select({"nodes":[a]},[rec])
        self.assertEqual([n["name"] for n in selected],["yaml-port"])

    def test_index_binding_requires_original_provider_row(self):
        a=row("one","194.38.11.86")
        b=row("two","45.86.66.170",delay=400)
        a["index"]=2
        b["index"]=1
        self.assertEqual(t.select({"nodes":[a,b]},
                                  [raw(a),raw(b)]),[])
        self.assertEqual(len(t.select({"nodes":[a,b]},
                         [raw(b),raw(a)])),2)

    def test_invalid_and_boolean_delay_are_skipped(self):
        healthy=row("good","194.38.11.86")
        bad1=row("bool","45.86.66.170")
        bad1["delay_ms"]=True
        bad2=row("none","45.86.66.171")
        bad2["delay_ms"]=None
        good=t.select({"nodes":[bad1,bad2,healthy]},
                      [raw(bad1),raw(bad2),raw(healthy)])
        self.assertEqual([n["name"] for n in good],["good"])

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
        # The stage-14 runner has NO decoded-video helper loaded.
        self.assertEqual(got["results"][0]["service_single_sample"],"UNKNOWN")
        self.assertEqual(got["results"][0]["checks"]["youtube_video"],"UNKNOWN")
        self.assertFalse(got["results"][0]["service_ready"])
        self.assertFalse(got["results"][0]["routing_qualified"])
        self.assertEqual(got["candidates_selected"], 1)
        self.assertEqual(got["candidates_tested"], 1)
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

    def test_unattempted_candidate_is_not_counted_as_tested(self):
        a=row("a","194.38.11.86")
        got=t.sanitized({},[a],provider_sha="f"*64,elapsed=2)
        self.assertEqual(got["candidates_selected"],1)
        self.assertEqual(got["candidates_tested"],0)
        self.assertEqual(got["results"][0]["service_single_sample"],"UNKNOWN")

    def test_unknown_reason_codes_are_reported_per_service(self):
        a=row("reasoned-node","194.38.11.86")
        raw={"reasoned-node":{"status":"UNKNOWN","identity":"reasoned-node",
             "transport":"mihomo","sample_id":"safe-1","checks":{
                 "openai_api":{"state":"PASS","reason":"openai_api_auth_required"},
                 "chatgpt_web":{"state":"UNKNOWN","reason":"chatgpt_web_http_403"},
                 "youtube_video":{"state":"UNKNOWN","reason":"youtube_timeout"}}}}
        data=t.sanitized(raw,[a],provider_sha="a"*64,elapsed=4)
        self.assertEqual(data["results"][0]["reason_codes"],{
            "openai_api":"openai_api_auth_required",
            "chatgpt_web":"chatgpt_web_http_403",
            "youtube_video":"youtube_timeout"})
        self.assertFalse(data["results"][0]["service_ready"])

    def test_credential_url_not_reflected_into_reason_report(self):
        a=row("secret-name","194.38.11.86")
        dangerous="youtube_timeout/https://token.example/?auth=sensitive"
        raw={"secret-name":{"status":"UNKNOWN","identity":"secret-name",
             "transport":"mihomo","sample_id":"safe-2","checks":{
                "openai_api":{"state":"PASS","reason":"openai_api_auth_required"},
                "chatgpt_web":{"state":"UNKNOWN","reason":dangerous},
                "youtube_video":{"state":"UNKNOWN","reason":"youtube_URLError"}}}}
        data=t.sanitized(raw,[a],provider_sha="a"*64,elapsed=4)
        result=str(data)
        self.assertNotIn("token.example",result)
        self.assertNotIn("secret-name",result)
        self.assertEqual(data["results"][0]["reason_codes"]["chatgpt_web"],
                         "unclassified")
        self.assertEqual(data["results"][0]["reason_codes"]["youtube_video"],
                         "unclassified")

    def test_wrong_identity_downgrades_all_reasons(self):
        a=row("real-node","194.38.11.86")
        raw={"real-node":{"status":"FAIL","identity":"wrong",
             "transport":"mihomo","sample_id":"safe-3","checks":{
                 "openai_api":{"state":"FAIL","reason":"openai_unsupported_region"}}}}
        data=t.sanitized(raw,[a],provider_sha="a"*64,elapsed=1)
        self.assertTrue(all(v=="unclassified" for v in
                            data["results"][0]["reason_codes"].values()))

    def test_two_rounds_use_two_isolated_proxy_instances_without_promotion(self):
        import json, tempfile, time, types
        full=row("two-probes","194.38.11.86")
        candidate={k:full[k] for k in ("name","server","type","port","delay_ms")}
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            credential=Path(directory)/"selection"
            credential.write_text(json.dumps({
                "version":1,"prepared_at":int(time.time()),
                "mode":"SHADOW_ONLY","service_ready":False,
                "routing_verified":False,"boot_id":"boot",
                "route_generation":9,"candidates":[candidate],
                "proxies":[raw(candidate)],"provider_sha256":"b"*64}))
            calls=[]
            def probe(*args,**kwargs):
                calls.append(len(calls)+1)
                return {"two-probes":{
                    "status":"UNKNOWN","transport":"mihomo",
                    "identity":"two-probes","sample_id":f"pass-{len(calls)}",
                    "checks":{
                       "openai_api":{"state":"PASS","reason":"openai_api_auth_required"},
                       "chatgpt_web":{"state":"UNKNOWN",
                                      "reason":"chatgpt_web_http_403"},
                       "youtube_video":{"state":"UNKNOWN",
                                        "reason":"youtube_timeout"}}}}
            standby=types.SimpleNamespace(
                boot_identity=lambda:"boot",
                current_generation=lambda:9,
                probe_candidates=probe)
            smart=types.SimpleNamespace(
                POOL_PY=None,
                load_pool_code=lambda:object(),
                load_service_code=lambda:object())
            with patch.object(t,"credential_paths",
                              return_value={"selection":credential}), \
                 patch.object(t,"load",side_effect=lambda n,f:
                              standby if f=="awg-mihomo-standby.py" else smart), \
                 patch.object(t.time,"sleep",return_value=None):
                result=t.run(limit=1,rounds=2,timeout=2)
            self.assertEqual(calls,[1,2])
            self.assertEqual(result["rounds_executed"],2)
            self.assertEqual(result["total_service_samples"],2)
            self.assertEqual(result["candidates_tested"],1)
            self.assertFalse(result["service_ready"])
            self.assertFalse(result["routing_qualified"])
            self.assertFalse(result["video_decoder_used"])
            for sample in result["samples"]:
                entry=sample["results"][0]
                self.assertEqual(entry["checks"]["openai_api"],"PASS")
                self.assertEqual(entry["checks"]["chatgpt_web"],"UNKNOWN")
                self.assertEqual(entry["reason_codes"]["youtube_video"],
                                 "youtube_timeout")

    def test_unavailable_video_decoder_never_promotes_mock_pass(self):
        a=row("test-n","194.38.11.86")
        d={"test-n":{"status":"PASS","transport":"mihomo","identity":"test-n",
                     "sample_id":"sample123",
                     "checks":{key:{"state":"PASS","reason":"test"}
                               for key in ("openai_api","chatgpt_web","youtube_video")}}}
        result=t.sanitized(d,[a],provider_sha="a"*64,elapsed=0.1)
        self.assertEqual(result["results"][0]["service_single_sample"],"UNKNOWN")
        self.assertFalse(result["results"][0]["service_ready"])

    def test_root_execution_is_always_refused(self):
        with patch.object(t.os,"geteuid",return_value=0):
            with self.assertRaises(PermissionError):
                t.credential_paths(env={"CREDENTIALS_DIRECTORY":"/run/credentials/trial"},uid=0)
            with self.assertRaises(PermissionError):
                t.run()

    def test_unprivileged_without_service_credentials_is_refused(self):
        with patch.object(t.os,"geteuid",return_value=1000):
            with patch.dict(t.os.environ,{},clear=True):
                with self.assertRaises(PermissionError):
                    t.run()

    def test_private_credentials_path_required(self):
        with self.assertRaises(PermissionError):
            t.credential_paths(env={"CREDENTIALS_DIRECTORY":"/tmp/fake"},uid=1000)
        with self.assertRaises(PermissionError):
            t.credential_paths(env={"CREDENTIALS_DIRECTORY":""},uid=1000)

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
