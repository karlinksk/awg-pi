#!/usr/bin/env python3
"""Synthetic, network-free tests for private VLESS adapter generation."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import yaml

SOURCE=Path(__file__).resolve().parents[1]/"src"/"awg-xray-vless.py"
class AdapterTests(unittest.TestCase):
    def setUp(self):
        ctx=tempfile.TemporaryDirectory()
        self.addCleanup(ctx.cleanup)
        root=Path(ctx.name)
        self.provider=root/"subscription.yaml"
        self.selected=root/"selected.json"
        self.runtime=root/"config.json"
        self.lan=root/"env";self.lan.write_text("LAN_IF='lo'\n")
        spec=importlib.util.spec_from_file_location("awg_xray_vless",SOURCE)
        self.a=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.a)
        self.a.PROVIDER=self.provider;self.a.SELECTED=self.selected;self.a.RUNTIME=self.runtime;self.a.LAN_ENV=self.lan
        self.a.PORT=17892
        self.vless={
          "name":"🇳🇱 HoneyVPN VLESS XHTTP",
          "type":"vless","server":"203.0.113.21","port":443,
          "uuid":"01234567-89ab-4cde-8f01-23456789abcd",
          "network":"xhttp","tls":True,
          "servername":"example.com","client-fingerprint":"ios",
          "reality-opts":{"public-key":"A"*43,"short-id":"01ab"},
          "xhttp-opts":{"path":"/xhttp","mode":"auto"}
        }
        self.grpc={**self.vless,"name":"HoneyVPN gRPC","network":"grpc",
                   "grpc-opts":{"grpc-service-name":"grpcname"}}
        self.grpc.pop("xhttp-opts")
        self.grpc_tls={k:v for k,v in self.grpc.items() if k!="reality-opts"}
        self.grpc_tls["name"]="Verified TLS/gRPC"
        self.grpc_tls["alpn"]=["h2"]
        self.hy2={"name":"Hysteria2","type":"hysteria2","server":"198.51.100.4","port":443}
        self.provider.write_text(yaml.safe_dump({"proxies":[self.vless,self.grpc,self.hy2]},allow_unicode=True))
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(self.a.os,"geteuid",return_value=0).start()
        # In rootless CI, isolate owner-only filesystem operations via a
        # synthetic fixture. Root/integration tests exercise real ownership.
        if os.getuid()!=0:
            def fake_read(path, **kwargs):
                if path.is_symlink():self.a.die("SOURCE_UNAVAILABLE")
                return path.read_bytes()
            def fake_atomic(path,data):
                path.parent.mkdir(exist_ok=True,parents=True)
                path.write_text(json.dumps(data));path.chmod(0o600)
            self.a.secure_read=fake_read
            self.a.atomic_json=fake_atomic
    def call(self,*args):
        # Never consult a real systemd service in a synthetic adapter test:
        # CI may run on the test Pi while the authorized Xray sidecar is live.
        original_run=self.a.subprocess.run
        def isolated_service_check(argv,*a,**kw):
            if argv==["systemctl","is-active","--quiet","awg-xray-vless.service"]:
                return self.a.subprocess.CompletedProcess(argv,1)
            return original_run(argv,*a,**kw)
        with mock.patch.object(sys,"argv",["awg-xray-vless",*args]), \
             mock.patch.object(self.a.subprocess,"run",side_effect=isolated_service_check):
            return self.a.run()
    def test_select_renders_xhttp_without_touching_provider(self):
        original=self.provider.read_bytes()
        self.call("select","1")
        self.assertEqual(self.selected.stat().st_mode&0o777,0o600)
        with mock.patch.object(self.a,"interface",return_value="lo"):
            self.call("render")
        self.assertEqual(self.provider.read_bytes(),original)
        d=json.loads(self.runtime.read_text())
        self.assertEqual(d["inbounds"][0]["listen"],"127.0.0.1")
        self.assertEqual(d["inbounds"][0]["protocol"],"socks")
        self.assertFalse(d["inbounds"][0]["settings"]["udp"])
        self.assertEqual(d["outbounds"][0]["protocol"],"vless")
        self.assertEqual(d["outbounds"][0]["streamSettings"]["network"],"xhttp")
        self.assertEqual(d["outbounds"][0]["streamSettings"]["sockopt"]["interface"],"lo")
        self.assertEqual(d["outbounds"][0]["streamSettings"]["realitySettings"]["fingerprint"],"ios")
        self.assertEqual(d["outbounds"][0]["settings"]["vnext"][0]["users"][0]["id"],self.vless["uuid"])
        self.assertNotIn(self.vless["uuid"],self.selected.read_text())
        self.assertEqual(self.runtime.stat().st_mode&0o777,0o600)
    def test_grpc_transport_is_preserved(self):
        self.call("select","2")
        with mock.patch.object(self.a,"interface",return_value="lo"):
            self.call("render")
        d=json.loads(self.runtime.read_text())
        ss=d["outbounds"][0]["streamSettings"]
        self.assertEqual(ss["network"],"grpc")
        self.assertEqual(ss["grpcSettings"]["serviceName"],"grpcname")
        self.assertNotIn("xhttpSettings",ss)
    def test_verified_tls_grpc_select_and_render_uses_same_safe_bridge(self):
        self.provider.write_text(yaml.safe_dump(
            {"proxies":[self.vless,self.grpc,self.hy2,self.grpc_tls]},allow_unicode=True))
        self.call("select","4")
        with mock.patch.object(self.a,"interface",return_value="lo"):
            self.call("render")
        d=json.loads(self.runtime.read_text())
        ss=d["outbounds"][0]["streamSettings"]
        self.assertEqual(ss["security"],"tls")
        self.assertEqual(ss["network"],"grpc")
        self.assertEqual(ss["tlsSettings"],{
            "serverName":"example.com","allowInsecure":False,"alpn":["h2"]})
        self.assertEqual(ss["grpcSettings"]["serviceName"],"grpcname")
        self.assertNotIn("realitySettings",ss)
        self.assertEqual(ss["sockopt"]["interface"],"lo")
        self.assertNotIn(self.grpc_tls["uuid"],self.selected.read_text())
        self.assertEqual(self.runtime.stat().st_mode&0o777,0o600)

    def test_tls_grpc_no_insecure_or_malformed_fallback(self):
        invalid=(
            {"skip-cert-verify":True},
            {"alpn":["http/1.1"]},
            {"alpn":"h2"},
            {"alpn":["h2","not-real"]},
            {"flow":"xtls-rprx-vision"},
            {"reality-opts":None},
            {"reality-opts":{"public-key":"short"}},
            {"network":"xhttp"},
            {"tls":False},
        )
        for change in invalid:
            with self.subTest(change=change):
                with self.assertRaises(SystemExit):
                    self.a.validate({**self.grpc_tls,**change})

    def test_hysteria2_rejected(self):
        with self.assertRaises(SystemExit):self.call("select","3")
        self.assertFalse(self.selected.exists())
    def test_missing_or_changed_credentials_fail_closed(self):
        self.call("select","1")
        with mock.patch.object(self.a,"interface",return_value="lo"):
            self.call("render")
        old=self.runtime.read_bytes()
        self.vless["uuid"]="11234567-89ab-4cde-8f01-23456789abcd"
        self.provider.write_text(yaml.safe_dump({"proxies":[self.vless]},allow_unicode=True))
        with self.assertRaises(SystemExit):self.call("render")
        self.assertEqual(self.runtime.read_bytes(),old)
    def test_duplicate_profile_fingerprint_fails_closed(self):
        self.provider.write_text(yaml.safe_dump({"proxies":[self.vless,{**self.vless,"name":"other-name"}]}))
        self.call("select","1")
        with self.assertRaises(SystemExit):self.call("render")
    def test_invalid_insecure_or_unsupported_transport(self):
        for extra in ({"skip-cert-verify":True},{"network":"ws"},{"tls":False}):
            x={**self.vless,**extra}
            with self.assertRaises(SystemExit):self.a.validate(x)
    def test_symlink_provider_rejected(self):
        target=self.provider.with_name("target")
        self.provider.rename(target);self.provider.symlink_to(target)
        with self.assertRaises(SystemExit):self.call("list")
    def test_no_root_selection_allowed(self):
        with mock.patch.object(self.a.os,"geteuid",return_value=1000):
            with self.assertRaises(SystemExit):self.call("select","1")
    def test_missing_provider_is_nonfatal_status(self):
        self.provider.unlink()
        self.call("status")
        self.assertFalse(self.runtime.exists())
if __name__=="__main__":unittest.main()
