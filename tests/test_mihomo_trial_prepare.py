#!/usr/bin/env python3
"""Offline checks for the ephemeral <=480 kB root shortlist credential."""
from pathlib import Path
import importlib.util
import sys
import time
import unittest
from unittest.mock import patch

P = Path(__file__).resolve().parents[1] / "src" / "awg-mihomo-trial-prepare.py"
spec = importlib.util.spec_from_file_location("test_stage13_preparer", P)
prep = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prep
spec.loader.exec_module(prep)


def node(name, address, *, port=443, kind="vless"):
    return {"name": name, "type": kind, "server": address,
            "port": port, "delay_ms": 55, "healthy": True}


def source(n):
    return dict(n, uuid="EXAMPLE-SECRET-NEVER-PRINT")


class PrepareTests(unittest.TestCase):
    def context(self, picked=None, raw=None, extra=None, select=None):
        choices = picked or [node("alpha", "194.38.11.86")]
        provider = raw or [source(n) for n in choices]
        pool = {"provider_sha256": "a" * 64, "geo_enriched": True}
        pool.update(extra or {})
        selector = select or (lambda pool, raw, **kw: choices)
        return prep.prepare_payload(
            pool, provider, region="all", protocol="all",
            now=1_799_999_999, boot="boot1", generation=0,
            select_candidates=selector)

    def test_only_selected_proxy_secrets_are_copied(self):
        a, b = node("alpha", "194.38.11.86"), node("beta", "45.86.66.170")
        payload = self.context(picked=[a], raw=[source(a), source(b)])
        self.assertEqual(len(payload["proxies"]), 1)
        self.assertEqual(payload["proxies"][0]["name"], "alpha")
        self.assertNotIn("beta", str(payload))
        self.assertFalse(payload["service_ready"])
        self.assertFalse(payload["routing_verified"])

    def test_region_geography_required(self):
        a = node("alpha", "194.38.11.86")
        with self.assertRaises(ValueError):
            prep.prepare_payload({"provider_sha256": "a"*64,
                                  "geo_enriched": False},
                                  [source(a)], region="europe", protocol="all",
                                  now=10, boot="boot", generation=0,
                                  select_candidates=lambda *a, **k: [a])

    def test_mismatched_names_refused(self):
        a, b = node("alpha", "194.38.11.86"), node("beta", "45.86.66.170")
        with self.assertRaises(ValueError):
            self.context(picked=[a], raw=[source(b)])

    def test_reject_no_candidates(self):
        with self.assertRaises(ValueError):
            self.context(select=lambda *a, **kw: [])

    def test_reject_untrusted_hash(self):
        with self.assertRaises(ValueError):
            self.context(extra={"provider_sha256": "wrong"})

    def test_reject_missing_boot(self):
        a = node("alpha", "194.38.11.86")
        with self.assertRaises(ValueError):
            prep.prepare_payload(
                {"provider_sha256":"a"*64,"geo_enriched":True},
                [source(a)], region="all",protocol="all",
                now=10,boot="",generation=None,
                select_candidates=lambda *args,**kwargs: [a])

    def test_reject_credential_writes_outside_root_ram(self):
        with self.assertRaises(ValueError):
            prep.atomic_selection(self.context(),target=Path("/tmp/public-selection.json"))

    def test_reject_oversized_credential_before_write(self):
        credential=self.context()
        credential["proxies"][0]["secret"]="x"*prep.MAX_SIZE
        with self.assertRaises(ValueError):
            prep.atomic_selection(credential)

    def test_preparer_does_not_accept_nonroot(self):
        with patch.object(prep.os, "geteuid", return_value=1000):
            with self.assertRaises(PermissionError):
                prep.run()

    def test_preparation_never_authorizes_node_or_route(self):
        payload=self.context()
        self.assertEqual(payload["mode"],"SHADOW_ONLY")
        self.assertIs(payload["service_ready"],False)
        self.assertIs(payload["routing_verified"],False)

if __name__ == "__main__":
    unittest.main()
