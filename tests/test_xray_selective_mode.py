#!/usr/bin/env python3
"""Rootless Selective Xray watchdog and fail-open contract tests."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/awg-xray-live-backend.py"
spec = importlib.util.spec_from_file_location("xray_selective_backend", PATH)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class SelectiveXraySafety(unittest.TestCase):
    def setUp(self):
        # Isolate the global maintenance lock from the running gateway.
        lockdir=tempfile.TemporaryDirectory()
        self.addCleanup(lockdir.cleanup)
        patch=mock.patch.object(m,"MAINTENANCE_LOCK",Path(lockdir.name)/"maintenance.lock")
        patch.start()
        self.addCleanup(patch.stop)
        consent=mock.patch.object(m,"xray_auto_authorized",return_value=True)
        consent.start(); self.addCleanup(consent.stop)

    # Historical test-Pi scenarios explicitly authorized this AUTO path.
    def test_auto_optin_required(self):
        with mock.patch.object(m, "xray_auto_authorized", return_value=False):
            self.assertFalse(m.verified_degraded_selective_baseline())

    def modefile(self, root, value="selective"):
        mode = root / "mode"
        mode.write_text(value)
        return mode

    def test_preserves_already_healthy_awg_without_any_mutations(self):
        with tempfile.TemporaryDirectory() as d:
            mode = self.modefile(Path(d))
            with (mock.patch.object(m, "MODE", mode),
                  mock.patch.object(m, "verified_awg_backup_safe", return_value=True),
                  mock.patch.object(m, "run") as command):
                self.assertTrue(m.failclosed())
                command.assert_not_called()

    def test_selective_awg_preservation_requires_https_and_exact_routes(self):
        with tempfile.TemporaryDirectory() as d:
            mode = self.modefile(Path(d))
            def command(*args, **kw):
                if args[0] == "ip":return "default dev awg0 scope link"
                if args[-1] == "get":return "awg"
                if args[-2:] == ("check","awg"):return "healthy"
                raise AssertionError(args)
            with (mock.patch.object(m, "MODE", mode),
                  mock.patch.object(m, "run", side_effect=command),
                  mock.patch.object(m, "active", return_value=True),
                  mock.patch.object(m, "tun_runtime_ready", return_value=True)):
                self.assertTrue(m.verified_awg_backup_safe())
                with mock.patch.object(m, "tun_runtime_ready", side_effect=AssertionError("AWG must not depend on Mihomo/HTTPS")):
                    self.assertTrue(m.verified_awg_backup_safe())
                with mock.patch.object(m, "run", side_effect=lambda *a, **kw:
                       "default dev mihomo0" if a[0]=="ip" else command(*a, **kw)):
                    self.assertFalse(m.verified_awg_backup_safe())

    def test_selective_failopen_before_stop_and_no_transit_disable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            mode=self.modefile(root)
            bridge=root/"bridge"
            bridge.write_bytes(b'Environment="MIHOMO_XRAY_VLESS_BRIDGE=1"\n')
            runtime=root/"runtime"
            runtime.write_bytes(bridge.read_bytes())
            selected=root/"selected"
            selected.write_text("{}")
            calls=[]
            def command(*args,**kw):
                calls.append(args)
                if args[:4]==("ip","-4","rule","show"):
                    return "0: from all lookup local\n32766: from all lookup main\n"
                return ""
            def active(service):
                return service in ("ssh.service","dnsmasq.service")
            with (mock.patch.object(m,"MODE",mode),
                  mock.patch.object(m,"BRIDGE",bridge),
                  mock.patch.object(m,"BRIDGE_RUNTIME",runtime),
                  mock.patch.object(m,"SELECTED",selected),
                  mock.patch.object(m,"verified_awg_backup_safe",return_value=False),
                  mock.patch.object(m,"run",side_effect=command),
                  mock.patch.object(m,"active",side_effect=active)):
                self.assertTrue(m.failclosed())
            self.assertIn(("/usr/local/sbin/awg-pbr-failopen",),calls)
            self.assertNotIn(("/usr/local/sbin/awg-transit-routing","disable"),calls)
            self.assertLess(calls.index(("/usr/local/sbin/awg-pbr-failopen",)),
                            calls.index(("systemctl","stop",m.MIHOMO)))
            self.assertFalse(bridge.exists())
            self.assertFalse(runtime.exists())
            self.assertFalse(selected.exists())

    def test_foreign_override_rejected_before_any_network_modification(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);mode=self.modefile(root)
            bridge=root/"foreign";bridge.write_text("OTHER_OWNER")
            with (mock.patch.object(m,"MODE",mode),
                  mock.patch.object(m,"BRIDGE",bridge),
                  mock.patch.object(m,"BRIDGE_RUNTIME",root/"nothing"),
                  mock.patch.object(m,"verified_awg_backup_safe",return_value=False),
                  mock.patch.object(m,"run") as command):
                self.assertFalse(m.failclosed())
                command.assert_not_called()

    def test_failopen_cannot_pass_while_old_0x100_rule_remains(self):
        with tempfile.TemporaryDirectory() as d:
            mode=self.modefile(Path(d))
            def command(*args,**kw):
                if args[:4]==("ip","-4","rule","show"):
                    return "100: from all fwmark 0x100 lookup 100\n"
                return ""
            with (mock.patch.object(m,"MODE",mode),
                  mock.patch.object(m,"BRIDGE",Path(d)/"absent-bridge"),
                  mock.patch.object(m,"BRIDGE_RUNTIME",Path(d)/"absent-runtime"),
                  mock.patch.object(m,"SELECTED",Path(d)/"absent-selected"),
                  mock.patch.object(m,"verified_awg_backup_safe",return_value=False),
                  mock.patch.object(m,"run",side_effect=command),
                  mock.patch.object(m,"active",side_effect=lambda v:v in ("ssh.service","dnsmasq.service"))):
                self.assertFalse(m.failclosed())

    def test_postcheck_requires_live_route_and_mark(self):
        with tempfile.TemporaryDirectory() as d:
            mode=self.modefile(Path(d))
            backend=m.LinuxBackend("dead","xray")
            def command(*args,**kw):
                if args[-1]=="get":return "mihomo"
                if args[:4]==("ip","-4","rule","show"):
                    return "100: from all fwmark 0x100 lookup 100\n"
                raise AssertionError(args)
            with (mock.patch.object(m,"MODE",mode),
                  mock.patch.object(m,"routes_ok",return_value=True),
                  mock.patch.object(m,"active",return_value=True),
                  mock.patch.object(m,"run",side_effect=command)):
                self.assertTrue(backend.check_policy_routes())
                with mock.patch.object(m,"run",return_value="0: from all lookup local"):
                    self.assertFalse(backend.check_policy_routes())
                with mock.patch.object(m,"routes_ok",return_value=False):
                    self.assertFalse(backend.check_policy_routes())

    def test_selective_watchdog_healthy_commit_never_runs_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            base=root/"backup";base.mkdir()
            snap=base/"xray-failover-123-456";snap.mkdir()
            (snap/"state.json").write_text(json.dumps({"state":"committed"}))
            mode=self.modefile(root)
            def command(*args,**kw):
                if args[-1]=="get":return "mihomo"
                if args[:4]==("ip","-4","rule","show"):
                    return "100: from all fwmark 0x100 lookup 100"
                raise AssertionError(args)
            with (mock.patch.object(m,"BASE",base),
                  mock.patch.object(m,"MODE",mode),
                  mock.patch.object(m,"run",side_effect=command),
                  mock.patch.object(m,"active",return_value=True),
                  mock.patch.object(m,"routes_ok",return_value=True),
                  mock.patch.object(m,"tun_runtime_ready",return_value=True),
                  mock.patch.object(m,"failclosed") as restore):
                m.watchdog(snap)
                restore.assert_not_called()


    def test_degraded_selective_requires_testpi_auto_dead_mihomo_and_safe_awg(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            mode=self.modefile(root)
            nodepolicy=root/"node-policy.mode";nodepolicy.write_text("auto")
            vpn=root/"vpn-enabled";vpn.write_text("1")
            services={"ssh.service","dnsmasq.service","awg-pbr-health.service","awg-quick@awg0.service"}
            def run(*args,**kw):
                if args[0]=="ip" and args[2]=="rule":return "0: from all lookup local"
                if args[0]=="ip" and args[2]=="route":return "default dev mihomo0 scope link"
                if args[-1]=="get":return "mihomo"
                if args[-2:]==("check","awg"):return "healthy"
                raise AssertionError(args)
            with (mock.patch.object(m,"MODE",mode),
                  mock.patch.object(m,"NODE_POLICY_MODE",nodepolicy),
                  mock.patch.object(m,"VPN_ENABLED",vpn),
                  mock.patch.object(m.socket,"gethostname",return_value="awg-upgrade"),
                  mock.patch.object(m,"active",side_effect=lambda s:s in services),
                  mock.patch.object(m,"run",side_effect=run),
                  mock.patch.dict(m.os.environ,{"MIHOMO_XRAY_SELECTIVE_CANARY":"1",
                                               "MIHOMO_XRAY_AUTO_FAILOVER_CANARY":"1"})):
                self.assertTrue(m.verified_degraded_selective_baseline())
                with mock.patch.dict(m.os.environ,{"MIHOMO_XRAY_SELECTIVE_CANARY":"0"}):
                    self.assertFalse(m.verified_degraded_selective_baseline())
                with mock.patch.object(m,"active",return_value=True):
                    self.assertFalse(m.verified_degraded_selective_baseline())
                with mock.patch.object(m,"run",side_effect=lambda *a,**kw:
                    "100: from all fwmark 0x100 lookup 100" if a[:4]==("ip","-4","rule","show") else run(*a,**kw)):
                    self.assertFalse(m.verified_degraded_selective_baseline())
                with mock.patch.object(m,"run",side_effect=lambda *a,**kw:
                    "default dev awg0" if a[:4]==("ip","-4","route","show") else run(*a,**kw)):
                    self.assertFalse(m.verified_degraded_selective_baseline())
                vpn.write_text("0")
                self.assertFalse(m.verified_degraded_selective_baseline())

    def test_degraded_selective_rearms_mark_only_after_verified_new_tun(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);mode=self.modefile(root);vpn=root/"vpn-enabled";vpn.write_text("1")
            backend=m.LinuxBackend("dead","vless")
            backend.degraded_selective=True
            state={"enabled":False}; calls=[]
            def run(*args,**kw):
                calls.append(args)
                if args[:4]==("ip","-4","rule","show"):
                    return ("100: from all fwmark 0x100 lookup 100" if state["enabled"] else
                            "0: from all lookup local")
                if args[:4]==("ip","-4","rule","add"):
                    state["enabled"]=True
                    return ""
                if args[-1]=="get":return "mihomo"
                raise AssertionError(args)
            with (mock.patch.object(m,"MODE",mode),
                  mock.patch.object(m,"VPN_ENABLED",vpn),
                  mock.patch.object(m,"routes_ok",return_value=True),
                  mock.patch.object(m,"verified_selective_route_ownership",return_value=True),
                  mock.patch.object(m,"active",return_value=True),
                  mock.patch.object(m,"run",side_effect=run),
                  mock.patch.object(backend,"check_tun_ready",return_value=True)):
                self.assertTrue(backend.check_policy_routes())
                self.assertTrue(state["enabled"])
                self.assertEqual(sum(1 for a in calls if a[:4]==("ip","-4","rule","add")),1)
                state["enabled"]=False;calls.clear()
                with mock.patch.object(backend,"check_tun_ready",return_value=False):
                    self.assertFalse(backend.check_policy_routes())
                self.assertFalse(state["enabled"])
                self.assertFalse(any(a[:4]==("ip","-4","rule","add") for a in calls))
                with mock.patch.object(m,"verified_selective_route_ownership",return_value=False):
                    self.assertFalse(backend.check_policy_routes())
                vpn.write_text("0")
                self.assertFalse(backend.check_policy_routes())

if __name__=="__main__":
    unittest.main()
