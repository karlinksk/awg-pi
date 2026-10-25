#!/usr/bin/env python3
"""Mixed provider import: VLESS Reality/XHTTP and Hysteria2, no live credentials."""
import base64
import importlib.util
from pathlib import Path
import unittest
import sys

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("awg_mihomo_provider_mixed",ROOT/"src/awg-mihomo-provider.py")
provider=importlib.util.module_from_spec(spec);sys.modules[spec.name]=provider;spec.loader.exec_module(provider)

UUID="11111111-1111-4111-8111-111111111111"
VLESS=("vless://"+UUID+"@node.example.invalid:443?"
       "type=xhttp&security=reality&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
       "&sid=123abc&path=%2Fmedia&mode=auto&sni=cdn.example.invalid&fp=chrome#One")
HY2=("hysteria2://testuser%3Atestpassword@hy2.example.invalid:443/?"
     "obfs=salamander&obfs-password=example-salamander&sni=hy2.example.invalid#Two")

class MixedSubscriptionTests(unittest.TestCase):
    def test_xhttp_reality_mapping(self):
        x=provider.parse_vless_uri(VLESS,1)
        self.assertEqual((x["type"],x["network"]),("vless","xhttp"))
        self.assertEqual(x["xhttp-opts"],{"path":"/media","mode":"auto"})
        self.assertTrue(x["tls"])
        self.assertEqual(x["reality-opts"]["short-id"],"123abc")
        self.assertEqual(x["servername"],"cdn.example.invalid")
    def test_hysteria2_auth_and_obfs_mapping(self):
        x=provider.parse_hysteria2_uri(HY2,2)
        self.assertEqual(x["type"],"hysteria2")
        self.assertEqual(x["password"],"testuser:testpassword")
        self.assertEqual(x["obfs"],"salamander")
        self.assertEqual(x["obfs-password"],"example-salamander")
        self.assertEqual(x["sni"],"hy2.example.invalid")
        self.assertFalse(x.get("skip-cert-verify",False))
    def test_hysteria2_insecure_opt_in(self):
        x=provider.parse_hysteria2_uri("hy2://auth@hy2.example.invalid:443/?insecure=1#Three",3)
        self.assertTrue(x["skip-cert-verify"])
    def test_mixed_base64_subscription_preserves_all(self):
        encoded=base64.b64encode((VLESS+"\n"+HY2+"\n").encode()).decode()
        fmt,x=provider.normalize_provider(encoded,"auto")
        self.assertEqual(fmt,"base64")
        self.assertEqual(len(x),2)
        self.assertEqual([p["type"] for p in x],["vless","hysteria2"])
    def test_mixed_plain_uri_subscription(self):
        fmt,x=provider.normalize_provider(VLESS+"\n"+HY2,"auto")
        self.assertEqual((fmt,len(x)),("vless",2))
    def test_plain_vless_format_retained(self):
        fmt,x=provider.normalize_provider(VLESS,"vless")
        self.assertEqual((fmt,len(x)),("vless",1))
    def test_unknown_hysteria_obfs_rejected(self):
        with self.assertRaises(SystemExit):
            provider.parse_hysteria2_uri("hy2://auth@h.example.invalid/?obfs=unknown",1)
    def test_unknown_xhttp_mode_rejected(self):
        with self.assertRaises(SystemExit):
            provider.parse_vless_uri(VLESS.replace("mode=auto","mode=invalid"),1)
    def test_invalid_hy2_auth_rejected(self):
        with self.assertRaises(SystemExit):
            provider.parse_hysteria2_uri("hy2://hy2.example.invalid:443/",1)
    def test_existing_vless_grpc_remains_supported(self):
        uri=("vless://"+UUID+"@grpc.example.invalid:443?type=grpc&security=reality&"
             "pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&serviceName=test#Grpc")
        x=provider.parse_vless_uri(uri,1)
        self.assertEqual(x["network"],"grpc")
        self.assertEqual(x["grpc-opts"]["grpc-service-name"],"test")

if __name__=="__main__":
    unittest.main()
