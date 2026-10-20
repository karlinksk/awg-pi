#!/usr/bin/env python3
"""Subscription URL, ordering, names, count and credential churn without network/systemd."""
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
import yaml
ROOT=Path(__file__).resolve().parents[1]

class DynamicNodesTests(unittest.TestCase):
    def setUp(self):
        work=tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root=Path(work.name)
        spec=importlib.util.spec_from_file_location("unified_nodes",ROOT/"src"/"awg-mihomo-unified-nodes.py")
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        spec=importlib.util.spec_from_file_location("xray_adapter",ROOT/"src"/"awg-xray-vless.py")
        self.a=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.a)
        self.m.PROVIDER=self.root/"provider.yaml"
        self.m.MIHOMO_POOL=self.root/"pool.json"
        self.m.CACHE=self.root/"health.json"
        self.m.TTL=3600
        self.m.load_adapter=lambda:self.a
        self.a.PROVIDER=self.m.PROVIDER
        # Always synthetic rootless owner fixtures, not live subscription state.
        self.a.secure_read=lambda p,**kw:Path(p).read_bytes()
        self.a.atomic_json=lambda path,data:Path(path).write_text(json.dumps(data))
        self.vless={
         "name":"🇳🇱 xhttp-A", "type":"vless","network":"xhttp","tls":True,
         "server":"203.0.113.1","port":443,
         "uuid":"01234567-89ab-4cde-8f01-23456789abcd",
         "servername":"example.com","client-fingerprint":"ios",
         "reality-opts":{"public-key":"A"*43,"short-id":"ab"},
         "xhttp-opts":{"path":"/xhttp","mode":"auto"}}
        self.vlessb={**self.vless,"name":"🇫🇮 gRPC-B","network":"grpc",
                      "uuid":"11234567-89ab-4cde-8f01-23456789abcd",
                      "server":"203.0.113.2","grpc-opts":{"grpc-service-name":"t"}}
        self.vlessb.pop("xhttp-opts",None)
        self.hy2={"name":"🇩🇪 HY2-C","type":"hysteria2","server":"192.0.2.3","port":443}
        self.nodes=[self.vless,self.vlessb,self.hy2]
        self.publish(self.nodes)
    def publish(self,nodes):
        self.m.PROVIDER.write_text(yaml.safe_dump({"proxies":nodes},allow_unicode=True))
        raw=self.m.PROVIDER.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        pool={"version":2,"target":"live","scanned_at":time.time(),
              "provider_sha256":sha,
              "nodes":[{"index":i,"name":n.get("name"),"healthy":n.get("type")!="vless"}
                       for i,n in enumerate(nodes,1)]}
        self.m.MIHOMO_POOL.write_text(json.dumps(pool))
    def seed(self, node, status="NETWORK_OK"):
        self.m.CACHE.write_text(json.dumps({
            "version":1,"provider_sha256":"formerly-different-url/provider",
            "results":{self.a.sha_profile(node):{"at":time.time(),"status":status}}}))
    def get_rows(self):
        nodes,sha,pool,cache=self.m.snapshots(self.a)
        return self.m.inventory(nodes,pool,cache,self.a),cache
    def test_same_transport_new_url_and_reordered_count_retains_valid_evidence(self):
        self.seed(self.vless)
        self.publish([self.hy2,self.vlessb,{**self.vless,"name":"Renamed A"},
                      {"name":"NEW HY2","type":"hysteria2","server":"198.51.100.3","port":443}])
        rows,cache=self.get_rows()
        self.assertEqual(len(rows),4)
        self.assertEqual([r["engine"] for r in rows],["MIHOMO","XRAY","XRAY","MIHOMO"])
        self.assertEqual([r["basic_network"] for r in rows],
                         ["NETWORK_OK","UNTESTED","NETWORK_OK","NETWORK_OK"])
        self.assertEqual(len(cache["results"]),1)
    def test_removed_node_and_rotation_rejects_old_evidence(self):
        self.seed(self.vless)
        changed={**self.vless,"server":"203.0.113.9","port":8443}
        self.publish([self.hy2,changed])
        rows,cache=self.get_rows()
        self.assertEqual(rows[1]["basic_network"],"UNTESTED")
        self.assertFalse(cache["results"])
    def test_only_removed_and_added_nodes(self):
        self.seed(self.vlessb)
        self.publish([self.hy2])
        rows,cache=self.get_rows()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["engine"],"MIHOMO")
        self.assertEqual(cache["results"],{})
    def test_duplicate_names_are_not_selectable(self):
        self.publish([self.vless,{**self.vlessb,"name":self.vless["name"]}])
        rows,_=self.get_rows()
        self.assertEqual([r["basic_network"] for r in rows],["UNUSABLE_DUPLICATE_OR_MISSING_NAME"]*2)
    def test_stale_scan_is_not_healthy(self):
        payload=json.loads(self.m.MIHOMO_POOL.read_text())
        payload["scanned_at"]=time.time()-4000
        self.m.MIHOMO_POOL.write_text(json.dumps(payload))
        rows,_=self.get_rows()
        self.assertEqual(rows[2]["basic_network"],"UNTESTED")
    def test_old_proof_expires_even_if_provider_same(self):
        self.m.CACHE.write_text(json.dumps({"version":1,"results":{
            self.a.sha_profile(self.vless):{"at":time.time()-4000,"status":"NETWORK_OK"}}}))
        rows,cache=self.get_rows()
        self.assertEqual(rows[0]["basic_network"],"UNTESTED")
        self.assertEqual(cache["results"],{})
    def test_same_name_new_credentials_not_previous_success(self):
        self.seed(self.vless)
        updated={**self.vless,"uuid":"21234567-89ab-4cde-8f01-23456789abcd"}
        self.publish([updated])
        rows,_=self.get_rows()
        self.assertEqual(rows[0]["basic_network"],"UNTESTED")
    def test_persist_prunes_orphans(self):
        self.seed(self.vless)
        self.publish([self.hy2,self.vlessb])
        self.m.persist_cache(self.a,hashlib.sha256(self.m.PROVIDER.read_bytes()).hexdigest(),
                            {self.a.sha_profile(self.vlessb):{"at":time.time(),"status":"NETWORK_OK"}})
        record=json.loads(self.m.CACHE.read_text())["results"]
        self.assertEqual(set(record),{self.a.sha_profile(self.vlessb)})
    def test_large_and_changing_count_scans_in_bounded_batches(self):
        # 27 VLESS plus a network-healthy HY2. No fixed 5/11-node assumption.
        nodes=[{**self.vless,"name":f"VLESS {i}","server":f"203.0.113.{i+1}"}
               for i in range(27)]+[self.hy2]
        self.publish(nodes)
        self.m.MAX_PROBE=10
        successes=[]
        self.m.isolated_probe=lambda adapter,node: successes.append(node["name"]) or "NETWORK_OK"
        self.m.persist_cache(self.a,hashlib.sha256(self.m.PROVIDER.read_bytes()).hexdigest(),{})
        import sys,contextlib,io
        for wanted in (10,10,7):
            out=io.StringIO()
            with mock.patch.object(sys,"argv",["unified-nodes","probe-vless-all"]),                 mock.patch.object(self.m.os,"geteuid",return_value=0),                 contextlib.redirect_stdout(out):
                self.m.command()
            self.assertIn("UNIFIED_XRAY_SCAN_BATCH="+str(wanted),out.getvalue())
        self.assertEqual(len(successes),27)
        rows,cache=self.get_rows()
        self.assertEqual(len(rows),28)
        self.assertEqual(sum(x["basic_network"]=="NETWORK_OK" for x in rows),28)
        # A fourth scan is a no-op and performs no extra checks.
        with mock.patch.object(sys,"argv",["unified-nodes","probe-vless-all"]),             mock.patch.object(self.m.os,"geteuid",return_value=0),             contextlib.redirect_stdout(io.StringIO()):
            self.m.command()
        self.assertEqual(len(successes),27)

    def test_provider_rotation_mid_probe_does_not_write_old_identity(self):
        import contextlib,io,sys
        def rotate(adapter,node):
            self.publish([self.hy2,self.vlessb])
            return "NETWORK_OK"
        self.m.isolated_probe=rotate
        with mock.patch.object(sys,"argv",["unified-nodes","probe","1"]),\
             mock.patch.object(self.m.os,"geteuid",return_value=0),\
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.m.command()
        self.assertFalse(self.m.CACHE.exists())

    def test_resolve_engine_without_activation_or_ready(self):
        import contextlib,io,sys
        self.seed(self.vless)
        out=io.StringIO()
        with mock.patch.object(sys,"argv",["unified-nodes","resolve",self.vless["name"]]), \
             mock.patch.object(self.m.os,"geteuid",return_value=0), \
             contextlib.redirect_stdout(out):
            self.m.command()
        self.assertIn("NODE_ENGINE=XRAY",out.getvalue())
        self.assertIn("NODE_ACTIVATED=NO",out.getvalue())
        self.assertIn("NODE_LIVE_FAILOVER_CERTIFIED=NO",out.getvalue())
        self.assertNotIn("READY=PASS",out.getvalue())
        self.publish([self.hy2,self.vlessb])
        with mock.patch.object(sys,"argv",["unified-nodes","resolve",self.vless["name"]]), \
             mock.patch.object(self.m.os,"geteuid",return_value=0), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):self.m.command()

    def test_no_ready_claim_on_simple_http_check(self):
        self.seed(self.vless)
        rows,_=self.get_rows()
        self.assertEqual(rows[0]["basic_network"],"NETWORK_OK")
        self.assertNotIn("READY",rows[0])
if __name__=="__main__":unittest.main()
