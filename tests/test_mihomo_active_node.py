#!/usr/bin/env python3
"""Read-only active-node API contract tests; no real gateway changes."""
import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import yaml

SCRIPT=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-active-node.py"
spec=importlib.util.spec_from_file_location("active_node",SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class API(BaseHTTPRequestHandler):
    node="backup"
    members=["primary","backup"]
    auth=None
    def do_GET(self):
        if self.path!="/proxies/AWG-MIHOMO" or (self.auth is not None and self.headers.get("Authorization") != self.auth):
            self.send_response(403)
            self.end_headers()
            return
        data=json.dumps({"now":self.node,"all":self.members,"type":"Fallback"}).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.end_headers()
        self.wfile.write(data)
    def log_message(self,*args): pass


class ActiveNodeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=HTTPServer(("127.0.0.1",0),API)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        API.node="backup";API.members=["primary","backup"];API.auth=None
        self.conf=Path(self.temp.name)/"config.yaml"
        self.data={"external-controller":f"127.0.0.1:{self.server.server_port}",
                   "proxy-groups":[{"name":"AWG-MIHOMO","type":"fallback","use":["remote-provider"]}]}
        self.write()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def write(self):
        self.conf.write_text(yaml.safe_dump(self.data))

    def test_provider_based_fallback_reports_runtime_selection(self):
        self.assertEqual(mod.read_active(self.conf),"backup")

    def test_selector_reports_configured_group_choice(self):
        self.data["proxy-groups"][0]["type"]="select"
        self.write()
        self.assertEqual(mod.read_active(self.conf),"backup")

    def test_controller_disallows_unknown_node(self):
        API.node="injected"
        self.assertIn("unknown",mod.read_active(self.conf))

    def test_nonloopback_controller_rejected(self):
        self.data["external-controller"]="8.8.8.8:9090"
        self.write()
        self.assertIn("no loopback",mod.read_active(self.conf))

    def test_authenticated_loopback_supported(self):
        self.data["secret"]="example-secret"
        API.auth="Bearer example-secret"
        self.write()
        self.assertEqual(mod.read_active(self.conf),"backup")

    def test_controller_failure_is_not_a_success(self):
        self.data["external-controller"]="127.0.0.1:1"
        self.write()
        self.assertIn("unknown",mod.read_active(self.conf))

    def test_invalid_config_is_safe(self):
        self.conf.write_text("[]")
        self.assertIn("unknown",mod.read_active(self.conf))


if __name__ == "__main__":
    unittest.main()
