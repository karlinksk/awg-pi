#!/usr/bin/env python3
"""Synthetic, no-network validation of provider continuity safety boundaries."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
import yaml

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("hot_continuity",
                                               HERE / "awg-hot-pool-continuity.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
NOW = 200000


def proxy(name, key, ip):
    return {"name": name, "type": "vless", "server": ip, "port": 443,
            "uuid": key, "tls": True, "servername": "example.org"}


def emit_provider(path, items):
    path.write_text(yaml.safe_dump({"proxies": items}, sort_keys=False))


def emit_pool(path, provider, items, at=NOW):
    rows = [{"name": x["name"], "type": x["type"], "server": x["server"],
             "port": x["port"], "delay_ms": 900 + i, "healthy": True}
            for i, x in enumerate(items)]
    path.write_text(json.dumps({"provider_sha256": core.sha(provider),
                                "scanned_at": at, "geo_enriched": False,
                                "nodes": rows}))


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.live = self.base / "live.yaml"
        self.health = self.base / "live.json"
        self.candidate = self.base / "candidate.yaml"
        self.candidate_health = self.base / "candidate.json"
        self.state = self.base / "state.json"
        self.vault = self.base / "secret" / "vault.json"
        self.out = self.base / "ram" / "union.yaml"
        self.out_pool = self.base / "ram" / "union-pool.json"
        self.out_state = self.base / "ram" / "union-state.json"
        self.old = proxy("A", "secret-a", "193.0.2.10")
        # Tests use globally routable documentation analogues, no real accounts.
        self.old["server"] = "8.8.8.8"
        self.old_b = proxy("B", "secret-b", "9.9.9.9")
        self.new_c = proxy("C", "secret-c", "208.67.222.222")
        self.modified_b = proxy("B", "changed-key", "9.9.9.9")
        emit_provider(self.live, [self.old, self.old_b])
        emit_pool(self.health, self.live, [self.old, self.old_b])
        emit_provider(self.candidate, [self.modified_b, self.new_c])
        emit_pool(self.candidate_health, self.candidate,
                  [self.modified_b, self.new_c])
        checks = {}
        for item in (self.old, self.old_b):
            key = core.identity(item["name"], item["type"], item["server"], item["port"])
            checks[key] = {"passes": [NOW - 1550, NOW - 700],
                           "last_checked": NOW - 700, "last_result": "PASS"}
        self.state.write_text(json.dumps({"version": 1,
            "provider_sha256": core.sha(self.live), "checks": checks,
            "quarantine": {}, "geo_history": []}))

    def args(self, *, now=NOW, candidate=True):
        return types.SimpleNamespace(
            live_provider=self.live, live_pool=self.health,
            current_file=None,
            candidate_provider=self.candidate if candidate else None,
            candidate_pool=self.candidate_health if candidate else None,
            state=self.state, vault=self.vault, output_provider=self.out,
            output_pool=self.out_pool, output_state=self.out_state, now=now)

    def test_old_ready_profiles_and_new_candidates_coexist(self):
        core.run(self.args())
        merged = yaml.safe_load(self.out.read_text())["proxies"]
        self.assertEqual(len(merged), 4)
        self.assertEqual([p["name"] for p in merged[:2]], ["A", "B"])
        self.assertEqual(next(p["name"] for p in merged if p["uuid"] == "changed-key")[:4], "hot-")
        self.assertEqual(len(json.loads(self.vault.read_text())["entries"]), 2)
        self.assertEqual(len(json.loads(self.out_state.read_text())["checks"]), 2)

    def test_newly_qualified_candidate_becomes_retained_archive(self):
        core.run(self.args())
        state = json.loads(self.out_state.read_text())
        new_key = core.identity("C", "vless", "208.67.222.222", 443)
        state["checks"][new_key] = {"passes": [NOW-1300, NOW-200],
                                    "last_result": "PASS", "last_checked": NOW-200}
        self.state.write_text(json.dumps(state))
        # Candidate disappears before next collection; valid prior proof must
        # archive it, not leave it as a permanent READY without rechecks.
        core.run(self.args(now=NOW+20, candidate=False))
        data = yaml.safe_load(self.out.read_text())["proxies"]
        self.assertIn("secret-c", {p["uuid"] for p in data})
        archive = json.loads(self.vault.read_text())
        self.assertIn("secret-c", {x["profile"]["uuid"] for x in archive["entries"]})

    def test_pending_candidates_survive_staged_pool_expiration(self):
        core.run(self.args())
        self.state.write_text(self.out_state.read_text())
        # Candidate staged health scan expires after two hours, but admitted
        # pending profile remains probeable in the shadow union for one day.
        core.run(self.args(now=NOW + 8000))
        profiles = yaml.safe_load(self.out.read_text())["proxies"]
        self.assertIn("secret-c", {p["uuid"] for p in profiles})
        self.assertEqual(len(json.loads(self.vault.read_text())["pending"]), 2)

    def test_renamed_credential_collision_keeps_stable_shadow_alias(self):
        core.run(self.args())
        before = {p["uuid"]: p["name"] for p in
                  yaml.safe_load(self.out.read_text())["proxies"]}
        self.state.write_text(self.out_state.read_text())
        core.run(self.args(now=NOW + 25, candidate=False))
        after = {p["uuid"]: p["name"] for p in
                 yaml.safe_load(self.out.read_text())["proxies"]}
        self.assertEqual(after["changed-key"], before["changed-key"])
        self.assertEqual(after["secret-b"], before["secret-b"])

    def test_no_redundant_persistent_vault_write(self):
        core.run(self.args())
        ts = self.vault.stat().st_mtime_ns
        self.state.write_text(self.out_state.read_text())
        core.run(self.args(now=NOW + 60))
        self.assertEqual(ts, self.vault.stat().st_mtime_ns)

    def test_old_proofs_do_not_attach_to_changed_credentials(self):
        core.run(self.args())
        names = {p["uuid"]: p["name"] for p in yaml.safe_load(self.out.read_text())["proxies"]}
        self.assertNotEqual(names["secret-b"], names["changed-key"])
        proofs = json.loads(self.out_state.read_text())["checks"]
        changed_key = core.identity(names["changed-key"], "vless", "9.9.9.9", 443)
        self.assertNotIn(changed_key, proofs)

    def test_stale_candidate_pool_cannot_promote(self):
        emit_pool(self.candidate_health, self.candidate,
                  [self.modified_b, self.new_c], at=NOW - 8000)
        core.run(self.args())
        merged = yaml.safe_load(self.out.read_text())["proxies"]
        self.assertEqual(len(merged), 2)

    def test_old_profiles_survive_provider_rotation(self):
        core.run(self.args())
        self.state.write_text(self.out_state.read_text())
        emit_provider(self.live, [self.modified_b, self.new_c])
        emit_pool(self.health, self.live, [self.modified_b, self.new_c], at=NOW+200)
        core.run(self.args(now=NOW+200, candidate=False))
        merged = yaml.safe_load(self.out.read_text())["proxies"]
        uuids = {p["uuid"] for p in merged}
        self.assertIn("secret-a", uuids)
        self.assertIn("secret-b", uuids)
        self.assertIn("changed-key", uuids)
        self.assertIn("secret-c", uuids)
        self.assertEqual(len(json.loads(self.out_state.read_text())["checks"]), 2)

    def test_secret_files_not_world_readable(self):
        core.run(self.args())
        for path in (self.vault, self.out, self.out_pool, self.out_state):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_does_not_write_or_modify_live_provider_and_state(self):
        before = (self.live.read_bytes(), self.state.read_bytes())
        core.run(self.args())
        self.assertEqual(before, (self.live.read_bytes(), self.state.read_bytes()))

    def test_malformed_candidate_data_is_never_included(self):
        bad = dict(self.new_c, server="192.168.112.34")
        emit_provider(self.candidate, [bad])
        emit_pool(self.candidate_health, self.candidate, [bad])
        core.run(self.args())
        self.assertNotIn("secret-c", self.out.read_text())

    def test_proof_rejects_modified_profile_when_identity_same(self):
        old_state = json.loads(self.state.read_text())
        new_profiles = [self.old, self.modified_b]
        result, _ = core.rebind_state(old_state, core.sha(self.live),
                                       [self.old, self.old_b], {},
                                       new_profiles, "c"*64, NOW)
        self.assertEqual(len(result["checks"]), 1)

    def test_alias_does_not_reuse_proof(self):
        old_state = json.loads(self.state.read_text())
        renamed = dict(self.old, name="Renamed")
        result, _ = core.rebind_state(old_state, core.sha(self.live),
                                       [self.old, self.old_b], {},
                                       [renamed], "d"*64, NOW)
        self.assertEqual(result["checks"], {})

    def test_wrapper_passes_global_args_before_warm(self):
        wrapper = (HERE / "awg-mihomo-hot-continuity-run").read_text()
        start = wrapper.index('exec python3 -B "$POOL"')
        invocation = wrapper[start:]
        self.assertLess(invocation.index('--provider'), invocation.index('warm'))
        self.assertLess(invocation.index('--pool'), invocation.index('warm'))
        self.assertLess(invocation.index('--state'), invocation.index('warm'))

    def test_active_node_is_not_rebranded_as_standby(self):
        union, nodes = core.build_union(
            {"entries": [{"profile": self.old, "saved_at": NOW,
                           "last_delay_ms": 1200}]},
            [self.old, self.old_b],
            core.scan_health(self.health, self.live, NOW),
            [], [], current_name="A")
        self.assertEqual(sum(p["name"] == "A" for p in union), 1)
        self.assertEqual(sum(p["uuid"] == "secret-a" for p in union), 1)
        self.assertEqual(nodes[0]["origin"], "active")

    def test_archive_does_not_keep_unconfirmed_nodes(self):
        raw = json.loads(self.state.read_text())
        key = core.identity("B", "vless", "9.9.9.9", 443)
        raw["checks"][key]["passes"] = [NOW - 400]
        self.state.write_text(json.dumps(raw))
        core.run(self.args(candidate=False))
        self.assertEqual(len(json.loads(self.vault.read_text())["entries"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)