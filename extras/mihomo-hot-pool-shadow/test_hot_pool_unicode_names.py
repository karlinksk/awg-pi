#!/usr/bin/env python3
"""Offline, secret-free regressions for human-readable provider names in Hot Pool."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
import yaml

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("hot_continuity_display", HERE/"awg-hot-pool-continuity.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
NOW = 200000

def profile(name, *, server, key, ptype="hysteria2"):
    cfg = {"name":name, "type":ptype, "server":server, "port":443}
    if ptype == "hysteria2":
        cfg.update({"password":key, "sni":"example.invalid"})
    else:
        cfg.update({"uuid":key,"tls":True,"network":"xhttp"})
    return cfg

def publish(provider,pool,items):
    provider.write_text(yaml.safe_dump({"proxies":items},sort_keys=False,allow_unicode=True))
    pool.write_text(json.dumps({
        "provider_sha256":core.sha(provider),
        "scanned_at":NOW,
        "nodes":[{"name":p["name"],"type":p["type"],"server":p["server"],
                  "port":p["port"],"healthy":True,"delay_ms":800+i}
                 for i,p in enumerate(items)]}))

class UnicodeHotPoolTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        self.live=root/"live.yaml";self.live_pool=root/"live-health.json"
        self.candidate=root/"staged.yaml";self.candidate_pool=root/"staged-health.json"
        self.state=root/"state.json";self.vault=root/"vault.json"
        self.output=root/"union.yaml";self.outpool=root/"union-health.json";self.outstate=root/"union-state.json"
        self.old=profile("LegacyReady",server="8.8.8.8",key="old-secret")
        self.new=[
            profile("🇳🇱 Netherlands 1",server="9.9.9.9",key="hy2-new-secret"),
            profile("Germany 2 / XHTTP",server="208.67.222.222",key="vless-new-secret",ptype="vless"),
            profile("Node 🙂",server="1.1.1.1",key="third-secret"),
        ]
        publish(self.live,self.live_pool,[self.old])
        publish(self.candidate,self.candidate_pool,[])
        key=core.identity(self.old["name"],self.old["type"],self.old["server"],self.old["port"])
        self.state.write_text(json.dumps({"version":1,"provider_sha256":core.sha(self.live),
            "checks":{key:{"last_result":"PASS","last_checked":NOW-700,
                            "passes":[NOW-1500,NOW-700]}},
            "quarantine":{},"geo_history":[]}))
    def args(self):
        return types.SimpleNamespace(live_provider=self.live,live_pool=self.live_pool,
            current_file=None,candidate_provider=self.candidate,candidate_pool=self.candidate_pool,
            state=self.state,vault=self.vault,output_provider=self.output,
            output_pool=self.outpool,output_state=self.outstate,now=NOW)
    def test_unicode_live_node_is_aliased_with_transport_intact(self):
        publish(self.live,self.live_pool,self.new)
        core.run(self.args())
        united=yaml.safe_load(self.output.read_text())["proxies"]
        self.assertEqual(len(united),3)
        for original,converted in zip(self.new,united):
            self.assertTrue(core.NAME.fullmatch(converted["name"]))
            self.assertTrue(converted["name"].startswith("hot-"))
            self.assertEqual(core.fingerprint(converted),core.fingerprint(original))
            self.assertEqual(converted["server"],original["server"])
            self.assertEqual(converted["type"],original["type"])
    def test_alias_stable_across_rescan(self):
        publish(self.live,self.live_pool,self.new)
        core.run(self.args())
        first=[p["name"] for p in yaml.safe_load(self.output.read_text())["proxies"]]
        self.state.write_bytes(self.outstate.read_bytes())
        core.run(self.args())
        self.assertEqual([p["name"] for p in yaml.safe_load(self.output.read_text())["proxies"]],first)
    def test_existing_ready_proof_survives_addition_of_new_names(self):
        core.run(self.args())
        oldunion=yaml.safe_load(self.output.read_text())["proxies"]
        self.assertEqual(oldunion[0]["name"],"LegacyReady")
        self.assertIn(core.identity(self.old["name"],self.old["type"],self.old["server"],self.old["port"]),
                      json.loads(self.outstate.read_text())["checks"])
        self.state.write_bytes(self.outstate.read_bytes())
        publish(self.live,self.live_pool,self.new)
        core.run(self.args())
        united=yaml.safe_load(self.output.read_text())["proxies"]
        self.assertEqual(len(united),4)
        self.assertEqual(united[0]["name"],"LegacyReady")
        preserved=json.loads(self.outstate.read_text())["checks"]
        self.assertEqual(len(preserved),1)
        self.assertEqual(next(iter(preserved.values()))["passes"],[NOW-1500,NOW-700])
        self.assertTrue(all(core.NAME.fullmatch(p["name"]) for p in united))
    def test_staged_unicode_candidate_enters_protected_pending(self):
        publish(self.candidate,self.candidate_pool,self.new)
        core.run(self.args())
        vault=json.loads(self.vault.read_text())
        self.assertEqual(len(vault["pending"]),3)
        self.assertTrue(all(core.NAME.fullmatch(e["profile"]["name"]) for e in vault["pending"]))
        self.assertEqual({core.fingerprint(e["profile"]) for e in vault["pending"]},
                         {core.fingerprint(e) for e in self.new})
    def test_duplicate_names_get_unique_stable_aliases(self):
        same_name="🌍 One Location"
        items=[
            profile(same_name,server="9.9.9.9",key="first"),
            profile(same_name,server="1.1.1.1",key="second")
        ]
        publish(self.live,self.live_pool,items)
        core.run(self.args())
        names=[p["name"] for p in yaml.safe_load(self.output.read_text())["proxies"]]
        self.assertEqual(len(set(names)),2)
        self.assertTrue(all(core.NAME.fullmatch(name) for name in names))
    def test_control_char_and_oversize_name_rejected(self):
        self.assertFalse(core.valid_profile(profile("evil\nname",server="9.9.9.9",key="x")))
        self.assertFalse(core.valid_profile(profile("A"*300,server="9.9.9.9",key="x")))
        self.assertFalse(core.valid_profile(profile("   ",server="9.9.9.9",key="x")))
        self.assertTrue(core.valid_profile(self.new[0]))

if __name__=="__main__":
    unittest.main()
