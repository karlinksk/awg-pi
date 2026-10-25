#!/usr/bin/env python3
"""Regression: Selective TUN mark recheck must be idempotent at commit.

The route-checker and persistent writes are mocked or isolated to temp files.
No real routes, services or subscriptions are accessed or modified.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "xray_selective_commit_recheck",
    ROOT/"src/awg-xray-live-backend.py")
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)


class SelectiveCommitRecheck(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.mode=self.root/"mode"
        self.mode.write_text("selective")
        self.enabled=self.root/"vpn-enabled"
        self.enabled.write_text("1")
        self.current=self.root/"node-name"
        self.current.write_text("failed-hy2\n")
        self.snapshot=self.root/"xray-failover-123-456"
        self.snapshot.mkdir()
        (self.snapshot/"state.json").write_text('{"state":"armed"}')
        self.backend=m.LinuxBackend("failed-hy2","xray-vless")
        self.backend.degraded_selective=True
        self.backend.snapshot=self.snapshot
        self.state={"enabled":False,"owner":"mihomo","add":0}
        self.calls=[]
        for attr,value in (("MODE",self.mode),
                           ("VPN_ENABLED",self.enabled),
                           ("CURRENT",self.current)):
            p=mock.patch.object(m,attr,value)
            p.start();self.addCleanup(p.stop)
        for attr,value in (("routes_ok",True),
                           ("active",True),
                           ("verified_selective_route_ownership",True)):
            p=mock.patch.object(m,attr,return_value=value)
            p.start();self.addCleanup(p.stop)
        p=mock.patch.object(self.backend,"check_tun_ready",return_value=True)
        p.start();self.addCleanup(p.stop)
        p=mock.patch.object(self.backend,"verify_committed_node",return_value=True)
        p.start();self.addCleanup(p.stop)
        p=mock.patch.object(m,"run",side_effect=self.command)
        p.start();self.addCleanup(p.stop)

    def command(self,*args,**kwargs):
        self.calls.append(args)
        if args[:4]==("ip","-4","rule","show"):
            return ("100: from all fwmark 0x100 lookup 100\n"
                    if self.state["enabled"] else "0: from all lookup local\n")
        if args[:4]==("ip","-4","rule","add"):
            self.state["add"]+=1
            self.state["enabled"]=True
            return ""
        if args==("/usr/local/sbin/awg-transport","get"):
            return self.state["owner"]
        raise AssertionError("unexpected command "+str(args))

    def test_first_rearms_second_commit_verifies_without_second_add(self):
        self.assertTrue(self.backend.check_policy_routes())
        self.assertTrue(self.backend.selective_rule_rearmed)
        self.assertEqual(self.state["add"],1)
        self.backend.commit()
        self.assertEqual(self.state["add"],1)
        self.assertEqual(self.current.read_text(),"xray-vless\n")
        self.assertEqual(json.loads((self.snapshot/"state.json").read_text())["state"],
                         "committed")

    def test_initial_preexisting_mark_rejected_even_if_tun_https_is_good(self):
        self.state["enabled"]=True
        self.assertFalse(self.backend.check_policy_routes())
        self.assertFalse(self.backend.selective_rule_rearmed)
        self.assertEqual(self.state["add"],0)

    def test_lost_mark_after_first_postcheck_fails_commit_no_rearm(self):
        self.assertTrue(self.backend.check_policy_routes())
        self.state["enabled"]=False
        with self.assertRaisesRegex(RuntimeError,"NOT_VERIFIED"):
            self.backend.commit()
        self.assertEqual(self.state["add"],1)
        self.assertEqual(self.current.read_text(),"failed-hy2\n")
        self.assertEqual(json.loads((self.snapshot/"state.json").read_text())["state"],
                         "armed")

    def test_failed_tun_https_after_first_postcheck_fails_commit(self):
        self.assertTrue(self.backend.check_policy_routes())
        with mock.patch.object(self.backend,"check_tun_ready",return_value=False):
            with self.assertRaisesRegex(RuntimeError,"NOT_VERIFIED"):
                self.backend.commit()
        self.assertEqual(self.state["add"],1)
        self.assertEqual(self.current.read_text(),"failed-hy2\n")

    def test_route_ownership_foreign_after_first_check_fails_commit(self):
        self.assertTrue(self.backend.check_policy_routes())
        with mock.patch.object(m,"verified_selective_route_ownership",
                               return_value=False):
            with self.assertRaisesRegex(RuntimeError,"NOT_VERIFIED"):
                self.backend.commit()
        self.assertEqual(self.state["add"],1)

    def test_vpn_policy_disabled_after_first_check_fails_commit(self):
        self.assertTrue(self.backend.check_policy_routes())
        self.enabled.write_text("0")
        with self.assertRaisesRegex(RuntimeError,"NOT_VERIFIED"):
            self.backend.commit()
        self.assertEqual(self.state["add"],1)

    def test_healthy_route_change_after_first_check_fails_commit(self):
        self.assertTrue(self.backend.check_policy_routes())
        with mock.patch.object(m,"routes_ok",return_value=False):
            with self.assertRaisesRegex(RuntimeError,"NOT_VERIFIED"):
                self.backend.commit()
        self.assertEqual(self.state["add"],1)

    def test_required_ssh_service_down_after_first_check_fails_commit(self):
        self.assertTrue(self.backend.check_policy_routes())
        with mock.patch.object(m,"active",
            side_effect=lambda s: s!="ssh.service"):
            with self.assertRaisesRegex(RuntimeError,"NOT_VERIFIED"):
                self.backend.commit()
        self.assertEqual(self.state["add"],1)


if __name__=="__main__":
    unittest.main()
