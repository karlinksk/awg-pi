#!/usr/bin/env python3
"""Offline security tests for Stage27 preview. No live routing writes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import yaml

mod_path=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-fallback-preview.py"
spec=importlib.util.spec_from_file_location("stage27preview",mod_path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def ss(name, ip, port=8080):
    return {"name":name,"type":"ss","server":ip,"port":port,"cipher":"aes-128-gcm","password":"do-not-print"}

class Stage27Tests(unittest.TestCase):
    def setUp(self):
        self.prov={"proxies":[ss("A","169.150.210.233"),ss("B","176.32.32.108")]}
        self.base={"mixed-port":7890,"proxy-providers":{"subscription":{"path":"/secret"}},
          "proxy-groups":[{"name":"AWG-MIHOMO","type":"select","use":["subscription"]}],
          "rules":["MATCH,AWG-MIHOMO"],"tun":{"enable":True,"auto-route":False,"auto-redirect":False}}

    def test_explicit_order_and_no_other_provider_nodes(self):
        nodes=m.choose_nodes(self.prov,["B","A"])
        c=m.candidate(self.base,nodes)
        self.assertEqual(c["proxy-groups"][0]["proxies"],["B","A"])
        self.assertEqual([x["name"] for x in c["proxies"]],["B","A"])
        self.assertNotIn("proxy-providers",c)
        self.assertFalse(c["tun"]["enable"])
        self.assertFalse(c["profile"]["store-selected"])
        self.assertFalse(c["allow-lan"])
        self.assertEqual(c["bind-address"],"127.0.0.1")
        self.assertEqual(self.base["tun"]["enable"],True)

    def test_reject_duplicate_and_unknown(self):
        for names in (["A","A"],["A","C"],["A"],["A","B","C","D","E"]):
            with self.subTest(names=names),self.assertRaises(ValueError):
                m.choose_nodes(self.prov,names)

    def test_reject_unsafe_endpoint(self):
        for ip in ("192.168.1.2","127.0.0.1","::1","vpn.example.net"):
            with self.subTest(ip=ip),self.assertRaises(ValueError):
                m.choose_nodes({"proxies":[ss("A",ip),ss("B","176.32.32.108")]},["A","B"])

    def test_reject_bad_protocol_or_credential(self):
        self.prov["proxies"][0]["type"]="vless"
        with self.assertRaises(ValueError):m.choose_nodes(self.prov,["A","B"])
        self.prov["proxies"][0]["type"]="ss"
        self.prov["proxies"][0].pop("password")
        with self.assertRaises(ValueError):m.choose_nodes(self.prov,["A","B"])

    def test_direct_route_accepted(self):
        self.assertTrue(m.require_direct("169.150.210.233","eth0","192.168.112.1",
            "169.150.210.233 via 192.168.112.1 dev eth0 src 192.168.112.34 uid 0\n cache\n"))

    def test_direct_route_rejects_wrong_path(self):
        for route in ("169.150.210.233 dev mihomo0 src 198.18.0.1",
                      "169.150.210.233 via 192.168.112.2 dev eth0",
                      "169.150.210.233 via 192.168.112.1 dev awg0",
                      "169.150.210.233 via 192.168.112.1 dev eth1",
                      "169.150.210.233 dev eth0",
                      ""):
            with self.subTest(route=route),self.assertRaises(ValueError):
                m.require_direct("169.150.210.233","eth0","192.168.112.1",route)

    def test_refuse_non_tmp_or_world_accessible_directory(self):
        with self.assertRaises(ValueError):
            m.save_ram_private("/etc/awg-pbr/config.yaml",{})
        with self.assertRaises(ValueError):
            m.save_ram_private("/tmp/unsafe-stage27.yaml",{})
        with self.assertRaises(ValueError):
            m.save_ram_private("/tmp/../etc/stage27-unsafe.yaml",{})

    def test_no_secrets_in_exception_for_missing_node(self):
        with self.assertRaises(ValueError) as e:
            m.choose_nodes(self.prov,["A","missing"])
        self.assertNotIn("do-not-print",str(e.exception))

if __name__=="__main__":
    unittest.main()
