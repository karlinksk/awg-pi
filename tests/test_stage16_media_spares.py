#!/usr/bin/env python3
"""Offline fail-closed stage16 proxy and secret isolation verification."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"src"/path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

p=load("awg-stage16-prepare.py","stage16_prep")
trial=load("awg-mihomo-service-trial.py","stage16_trial")

def raw(name,server,port=443):
    return {"name":name,"type":"ss","server":server,"port":port,
            "cipher":"aes-128-gcm","password":"STAGE16_SECRET_FIXTURE",
            "udp":True}
def pool_row(source,index,delay=300):
    return {"name":source["name"],"type":"ss","server":source["server"],
            "port":source["port"],"delay_ms":delay,"healthy":True,
            "index":index,"europe":False}
def inputs():
    a=raw("shadowsocks-27307","169.150.210.233",8080)
    b=raw("shadowsocks-415241978","51.77.225.200",8388)
    return [a,b],{"nodes":[pool_row(a,1),pool_row(b,2)],
                  "geo_enriched":False}
def provenance(mode="DIRECT_LOCAL_UNVERIFIED"):
    return types.SimpleNamespace(classify=lambda n:{"mode":mode,
                    "scope":"PI_ONLY","router_verified":False})


class Stage16Tests(unittest.TestCase):
    def test_two_isolated_configs_and_exact_port(self):
        source,pool=inputs()
        chosen=p.prepare(pool=pool,raw=source,policy=("all","all"),
                         trial=trial,provenance=provenance())
        self.assertEqual(len(chosen),2)
        self.assertEqual([n["port"] for n in chosen],[17891,17892])
        self.assertNotEqual(chosen[0]["candidate_id"],chosen[1]["candidate_id"])
        for n in chosen:
            cfg=n["config"]
            self.assertEqual(cfg["mixed-port"],n["port"])
            self.assertEqual(cfg["bind-address"],"127.0.0.1")
            self.assertFalse(cfg["allow-lan"])
            self.assertFalse(cfg["ipv6"])
            self.assertFalse(cfg.get("tun",False))
            self.assertFalse(cfg.get("external-controller",False))
            self.assertEqual(cfg["rules"],["MATCH,AWG-STAGE16-ONLY-GROUP"])
            self.assertNotIn("STAGE16_SECRET_FIXTURE",str({k:v for k,v in n.items()
                                    if k!="config"}))

    def test_protect_secret_source_only_in_proxy_credentials(self):
        a=raw("n","169.150.210.233")
        c=p.node_config(a,17891)
        self.assertEqual(c["proxies"][0]["password"],"STAGE16_SECRET_FIXTURE")
        self.assertNotIn("name",str(c["proxies"][0]["server"]))
        self.assertNotIn("plugin",str(c))

    def test_non_direct_pi_underlay_rejected(self):
        source,pool=inputs()
        with self.assertRaises(p.Denied):
            p.prepare(pool=pool,raw=source,policy=("all","all"),
                      trial=trial,provenance=provenance("ASSISTED_MIHOMO"))

    def test_mikrotik_provenance_never_claimed(self):
        source,pool=inputs()
        outputs=p.prepare(pool=pool,raw=source,policy=("all","all"),
                      trial=trial,provenance=provenance())
        self.assertTrue(all(n["underlay"]=="PI_DIRECT_LOCAL_UNVERIFIED"
                            for n in outputs))

    def test_invalid_region_policy_denies_without_geo(self):
        source,pool=inputs()
        with self.assertRaises(p.Denied):
            p.prepare(pool=pool,raw=source,policy=("europe","all"),
                      trial=trial,provenance=provenance())

    def test_disallowed_protocol_does_not_overrule_policy(self):
        source,pool=inputs()
        with self.assertRaises(p.Denied):
            p.prepare(pool=pool,raw=source,policy=("all","vless"),
                      trial=trial,provenance=provenance())

    def test_duplicate_name_denied(self):
        source,pool=inputs()
        with self.assertRaises(p.Denied):
            p.prepare(pool=pool,raw=source+[source[0]],policy=("all","all"),
                      trial=trial,provenance=provenance())

    def test_unhealthy_node_denied(self):
        source,pool=inputs()
        pool["nodes"][1]["healthy"]=False
        with self.assertRaises(p.Denied):
            p.prepare(pool=pool,raw=source,policy=("all","all"),
                      trial=trial,provenance=provenance())

    def test_index_mismatch_denied(self):
        source,pool=inputs()
        pool["nodes"][0]["index"]=2
        with self.assertRaises(p.Denied):
            p.prepare(pool=pool,raw=source,policy=("all","all"),
                      trial=trial,provenance=provenance())

    def test_duplicate_endpoint_denied(self):
        source,pool=inputs()
        source[1]["server"]=source[0]["server"]
        source[1]["port"]=source[0]["port"]
        pool["nodes"][1]["server"]=source[0]["server"]
        pool["nodes"][1]["port"]=source[0]["port"]
        with self.assertRaises(p.Denied):
            p.prepare(pool=pool,raw=source,policy=("all","all"),
                      trial=trial,provenance=provenance())

    def test_plugin_and_proxy_chaining_denied(self):
        for key,value in (("plugin","v2ray-plugin"),
                          ("dialer-proxy","ACTUAL-PROD"),
                          ("interface-name","mihomo0")):
            a=raw("name","169.150.210.233")
            a[key]=value
            with self.assertRaises(p.Denied):
                p.node_config(a,17891)

    def test_non_ipv4_and_private_ip_denied(self):
        for host in ("foo.example","192.168.112.1","127.0.0.1","::1"):
            a=raw("a",host)
            with self.assertRaises(p.Denied):
                p.node_config(a,17891)

    def test_port_and_credential_validation(self):
        for val in (0,65536,True,None):
            a=raw("a","169.150.210.233",val)
            with self.assertRaises(p.Denied):
                p.node_config(a,17891)
        a=raw("a","169.150.210.233","8080")
        self.assertEqual(p.node_config(a,17891)["proxies"][0]["port"],8080)

    def test_unit_isolation_contracts(self):
        media=(ROOT/"units"/"awg-media-sidecar@.service").read_text()
        proxy=(ROOT/"units"/"awg-stage16-node@.service").read_text()
        self.assertIn("LoadCredential=proxy:/run/awg-pbr/stage16-media/proxy-%i.yaml",proxy)
        self.assertIn("DynamicUser=yes",proxy)
        self.assertIn("InaccessiblePaths=/var/lib/awg-pbr /etc/awg-pbr /run/awg-pbr",proxy)
        self.assertNotIn("CAP_NET_ADMIN",proxy)
        self.assertNotIn("external-controller",proxy)
        self.assertIn("IPAddressDeny=any",media)
        self.assertIn("IPAddressAllow=localhost",media)
        self.assertNotIn("LoadCredential=proxy",media)
        self.assertNotIn("\n[Install]\n",proxy)
        self.assertNotIn("\n[Install]\n",media)

if __name__=="__main__":unittest.main()
