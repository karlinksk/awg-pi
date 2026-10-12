#!/usr/bin/env python3
"""Offline event-driven underlay tests: no real router operations."""
import importlib.util
from pathlib import Path
import sys
import time
import unittest

P=Path(__file__).resolve().parents[1]/"src"/"awg-router-event-policy.py"
spec=importlib.util.spec_from_file_location("router_event_policy",P)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
T=int(time.time())
EP={"ip":"194.38.11.86","port":443,"protocol":"tcp"}
SRC="192.168.112.34"
GW="192.168.112.1"

def state(**updates):
    values=dict(boot="boot1",interface="eth0",router=GW,pi_ip=SRC,
                main_routes="default via router",ip_rules="lookup main",
                addresses="eth0 inet 192.168.112.34/24",provider_sha="a"*64)
    values.update(updates)
    return m.build_snapshot(**values)

def proof(ep=EP,when=T):
    return dict(mode="DIRECT",scope="END_TO_END",router_verified=True,
                reason="router_underlay_verified",checked_at=when,
                valid_for_seconds=30,
                endpoint_binding_sha256=m.exact_binding(ep,SRC,GW))

def plan(**changes):
    p=dict(policy="event_driven",requested_switch=True,adapter_available=True,
           endpoint=EP,source_ip=SRC,router_ip=GW,now=T)
    p.update(changes)
    return m.plan(**p)

class RouterEvents(unittest.TestCase):
    def test_init_and_idle_zero_router_queries(self):
        self.assertEqual(m.detect_events(None,state()),("INIT_OR_UNKNOWN",))
        self.assertEqual(m.detect_events(state(),state()),())
        for mode in m.MODES:
            self.assertEqual(plan(policy=mode,requested_switch=False).status,"IDLE")

    def test_generation_increments_once_per_change(self):
        first, event = m.advance_generation(None, state(), now=T)
        self.assertEqual((first["generation"], event), (1, ("INIT_OR_UNKNOWN",)))
        again, event = m.advance_generation(first, state(), now=T+10)
        self.assertEqual((again["generation"], event), (1, ()))
        changed, event = m.advance_generation(
            again, state(router="192.168.112.2"), now=T+11)
        self.assertEqual(changed["generation"], 2)
        self.assertEqual(changed["invalidated_at"], T+11)
        self.assertIn("LAN_CHANGED", event)

    def test_saved_generation_is_not_a_router_verified_proof(self):
        initial, _ = m.advance_generation(None, state())
        self.assertTrue(m.validate_snapshot(initial))
        self.assertEqual(plan(evidence=initial, in_process=False).status,
                         "AUDIT_ON_DEMAND")

    def test_network_and_provider_invalidation(self):
        original=state()
        for change,expected in [
            ({"boot":"boot2"},"BOOT_CHANGED"),
            ({"router":"192.168.112.2"},"LAN_CHANGED"),
            ({"main_routes":"default via awg0"},"MAIN_ROUTE_CHANGED"),
            ({"ip_rules":"fwmark lookup 100"},"IP_RULES_CHANGED"),
            ({"addresses":"eth0 inet 192.168.112.35/24"},"LINK_ADDR_CHANGED"),
            ({"provider_sha":"b"*64},"PROVIDER_CHANGED")]:
            changes=m.detect_events(original,state(**change))
            self.assertIn(expected,changes)
            self.assertTrue(m.invalidate_endpoint_proofs(changes))

    def test_expired_unsigned_or_changed_proof_requires_new_audit(self):
        self.assertEqual(plan(evidence=proof(),in_process=False).status,
                         "AUDIT_ON_DEMAND")
        self.assertEqual(plan(evidence=proof(when=T-31),in_process=True).status,
                         "AUDIT_ON_DEMAND")
        self.assertEqual(plan(evidence=proof(),in_process=True,
                              events=("LAN_CHANGED",)).status,"AUDIT_ON_DEMAND")
        self.assertEqual(plan(evidence=proof(),in_process=True,
                              endpoint=dict(EP,port=8443)).status,"AUDIT_ON_DEMAND")

    def test_exact_current_proof_reusable_only_in_process(self):
        good=plan(evidence=proof(),in_process=True)
        self.assertEqual(good.status,"READY_TO_PREFLIGHT")
        self.assertTrue(good.router_verified)
        self.assertTrue(good.advisory_only)
        self.assertEqual(plan(policy="strict",evidence=proof(),
                              in_process=True).status,"AUDIT_ON_DEMAND")

    def test_missing_router_or_untrusted_endpoint(self):
        self.assertEqual(plan(adapter_available=False).status,"BLOCKED")
        for bad in (dict(EP,ip="10.0.0.1"),dict(EP,ip="host.example"),
                    dict(EP,port=0),dict(EP,protocol="other")):
            self.assertEqual(plan(endpoint=bad).status,"BLOCKED")

    def test_generic_router_is_explicitly_unverified(self):
        self.assertEqual(plan(policy="unmanaged",adapter_available=False).status,
                         "BLOCKED")
        mode=plan(policy="unmanaged",adapter_available=False,admin_trust=True)
        self.assertEqual(mode.status,"UNVERIFIED")
        self.assertFalse(mode.router_verified)

    def test_audit_is_on_demand_and_one_call_only(self):
        calls=[]
        def verify(*args):
            calls.append(args)
            return proof()
        result=m.on_demand(policy="event_driven",endpoint=EP,
                            source_ip=SRC,router_ip=GW,interface="eth0",
                            verifier=verify,now=T)
        self.assertEqual(result.status,"READY_TO_PREFLIGHT")
        self.assertEqual(len(calls),1)

    def test_denied_audit_cannot_authorize(self):
        result=m.on_demand(policy="event_driven",endpoint=EP,
                            source_ip=SRC,router_ip=GW,interface="eth0",
                            verifier=lambda *args:proof(dict(EP,port=8443)),now=T)
        self.assertEqual(result.status,"BLOCKED")

    def test_unavailable_live_verifier_times_out_conservatively(self):
        import subprocess
        def slow(*args):
            raise subprocess.TimeoutExpired(cmd="router-readonly", timeout=2)
        response=m.on_demand(
            policy="event_driven",endpoint=EP,source_ip=SRC,router_ip=GW,
            interface="eth0",verifier=slow,now=T)
        self.assertEqual(response.status, "BLOCKED")
        self.assertFalse(response.router_verified)

    def test_spoofed_source_and_router_are_not_valid_binding(self):
        self.assertEqual(m.exact_binding(EP, "bad", GW), "")
        self.assertEqual(m.exact_binding(EP, SRC, "not-an-ip"), "")

    def test_simulated_pi_snapshot_has_no_router_ssh(self):
        from tempfile import TemporaryDirectory
        import types
        calls=[]
        def local(cmd, **kwargs):
            calls.append(cmd)
            if "addr" in cmd:
                raw="2: eth0 inet 192.168.112.34/24 scope global eth0"
            elif "rule" in cmd:
                raw="0: from all lookup local\n32766: from all lookup main"
            else:
                raw="default via 192.168.112.1 dev eth0"
            return types.SimpleNamespace(returncode=0, stdout=raw)
        with TemporaryDirectory(dir="/dev/shm") as tmp:
            e=Path(tmp)/"env"
            e.write_text("LAN_IF='eth0'\nROUTER_IP='192.168.112.1'\n")
            b=Path(tmp)/"boot";b.write_text("local-boot-id")
            state=m.read_local_snapshot(env_path=e,boot_path=b,runner=local)
        self.assertTrue(m.validate_snapshot(state))
        self.assertEqual(len(calls),3)
        self.assertTrue(all(cmd[0]=="/usr/sbin/ip" for cmd in calls))

    def test_generic_never_uses_adapter(self):
        result=m.on_demand(policy="unmanaged",endpoint=EP,
                            source_ip=SRC,router_ip=GW,interface="eth0",
                            verifier=lambda *args:self.fail("should not call"),
                            admin_trust=True)
        self.assertEqual(result.status,"UNVERIFIED")

    def test_only_local_read_commands_allowed(self):
        with self.assertRaises(ValueError):
            m.safe_runner(["/usr/bin/ssh","router","/ip/route/print"])
        with self.assertRaises(ValueError):
            m.safe_runner(["/usr/sbin/ip","route","replace","default"])

    def test_debounced_netlink_events_run_only_when_signaled(self):
        now=[0.0]
        seen=[]
        def clock(): return now[0]
        def sleep(sec): now[0] += sec
        calls=m.handle_netlink_events(
            ["", "route change", "address change", "rule change"],
            callback=lambda: seen.append(now[0]), sleeper=sleep, clock=clock,
            debounce=2.0)
        self.assertEqual((calls,seen), (3,[0.0,2.0,4.0]))

    def test_no_netlink_events_no_calls(self):
        count=m.handle_netlink_events([], callback=lambda: self.fail("no event"))
        self.assertEqual(count,0)

    def test_invalid_disk_or_saved_cache(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir="/dev/shm") as temp:
            f=Path(temp)/"state.json"
            with self.assertRaises(ValueError):
                m.write_state(f,state())
            f.write_text('{"version":1,"parts":{}}')
            self.assertIsNone(m.read_state(f))

if __name__=="__main__":
    unittest.main()
