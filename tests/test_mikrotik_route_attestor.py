#!/usr/bin/env python3
"""Offline RouterOS v7 underlay attestor safety and mutation tests."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest

PATH = Path(__file__).resolve().parents[1] / "src" / "awg-mikrotik-route-attestor.py"
spec = importlib.util.spec_from_file_location("awg_router_attestor", PATH)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

IP = "142.251.1.1"
SRC = "192.168.1.34"
GATEWAY = "192.168.1.1"


def fixture():
    snap = {k: [] for k in m.ORDER}
    snap["MANGLE"] = [
        f"0 comment=AWG-PI-TRANSPORT-DIRECT chain=prerouting action=accept "
        f"src-address={SRC} in-interface=bridge",
        "1 comment=DNSAUTO-TO-VPN chain=prerouting action=mark-routing "
        "new-routing-mark=r_to_vpn passthrough=no dst-address-list=to_vpn_auto "
        "in-interface=bridge",
        "2 comment=router-test chain=output action=mark-routing "
        "new-routing-mark=r_to_vpn protocol=icmp"]
    snap["ROUTES"] = [
        "DAd dst-address=0.0.0.0/0 routing-table=main gateway=203.0.113.1 "
        "immediate-gw=203.0.113.1%ether1 distance=1",
        "DAc dst-address=192.168.1.0/24 routing-table=main gateway=bridge "
        "immediate-gw=bridge",
        "0 As dst-address=0.0.0.0/0 routing-table=r_to_vpn "
        "gateway=sstp-provider immediate-gw=sstp-provider distance=1"]
    snap["MANGLE_AFTER"] = snap["MANGLE"][:]
    snap["ROUTES_AFTER"] = snap["ROUTES"][:]
    snap["WAN"] = ["0 list=LAN interface=bridge dynamic=no",
                   "1 list=WAN interface=ether1 dynamic=no"]
    snap["NAT"] = ["0 comment=DNS redirect to MikroTik chain=dstnat action=redirect "
                   "to-ports=53 protocol=udp dst-port=53 src-address-type=!local",
                   "1 chain=dstnat action=redirect to-ports=53 protocol=tcp "
                   "dst-port=53 src-address-type=!local",
                   "2 comment=defconf masquerade chain=srcnat action=masquerade "
                   "out-interface-list=all ipsec-policy=out,none"]
    snap["TABLES"] = ["0 D name=main fib", "1 name=r_to_vpn fib"]
    snap["VRF"] = ["0 * name=main interfaces=all"]
    snap["IPSEC"] = [
        "0 T * group=default src-address=::/0 dst-address=::/0 "
        "protocol=all proposal=default template=yes",
        "1 D peer=l2tp-in-server tunnel=no src-address=203.0.113.22/32 "
        "src-port=1701 dst-address=198.51.100.22/32 dst-port=56725 "
        "protocol=udp action=encrypt"]
    snap["HOTSPOT"] = []
    return snap


def decide(snapshot=None, *, ip=IP, port=443, protocol="tcp", pi_ip=SRC):
    return m.reasoned(ip, port, protocol, pi_ip, "eth0", GATEWAY,
                      snapshot if snapshot is not None else fixture())


class RouterAttestationTests(unittest.TestCase):
    def test_verified_main_wan_tcp(self):
        outcome=decide()
        self.assertEqual((outcome["mode"],outcome["router_verified"]),
                         ("DIRECT",True))

    def test_verified_main_wan_udp(self):
        self.assertEqual(decide(port=51820,protocol="udp")["mode"],"DIRECT")

    def test_pi_exception_must_precede_vpn_routing(self):
        doc=fixture()
        doc["MANGLE"].insert(0,"0 chain=prerouting action=mark-routing "
                            "new-routing-mark=r_to_vpn src-address="+SRC)
        doc["MANGLE_AFTER"]=doc["MANGLE"][:]
        self.assertEqual(decide(doc)["reason"],
                         "direct_mangle_exemption_missing_or_not_first")

    def test_first_exception_disabled_is_ignored(self):
        doc=fixture()
        doc["MANGLE"][0]="0 X " + doc["MANGLE"][0].split(" ",1)[1]
        doc["MANGLE_AFTER"]=doc["MANGLE"][:]
        self.assertFalse(decide(doc)["router_verified"])

    def test_first_rule_cannot_be_overbroad(self):
        doc=fixture()
        doc["MANGLE"][0]=doc["MANGLE"][0].replace(" in-interface=bridge","")
        doc["MANGLE_AFTER"]=doc["MANGLE"][:]
        self.assertFalse(decide(doc)["router_verified"])

    def test_another_source_cannot_use_pi_exemption(self):
        self.assertEqual(decide(pi_ip="192.168.1.11")["reason"],
                         "direct_mangle_exemption_missing_or_not_first")

    def test_main_default_to_sstp_is_not_direct(self):
        doc=fixture()
        doc["ROUTES"][0]=doc["ROUTES"][0].replace(
            "gateway=203.0.113.1 immediate-gw=203.0.113.1%ether1",
            "gateway=sstp-provider immediate-gw=sstp-provider")
        doc["ROUTES_AFTER"]=doc["ROUTES"][:]
        self.assertEqual(decide(doc)["reason"],"main_route_not_wan_direct")

    def test_more_specific_main_sstp_route_overrides_default(self):
        doc=fixture()
        doc["ROUTES"].append("1 As dst-address=142.251.1.1/32 routing-table=main "
                             "gateway=sstp-provider immediate-gw=sstp-provider")
        doc["ROUTES_AFTER"]=doc["ROUTES"][:]
        self.assertEqual(decide(doc)["reason"],"main_route_not_wan_direct")

    def test_equal_cost_routes_refuse(self):
        doc=fixture()
        doc["ROUTES"].append(doc["ROUTES"][0])
        doc["ROUTES_AFTER"]=doc["ROUTES"][:]
        self.assertEqual(decide(doc)["reason"],"ambiguous_main_route")

    def test_inactive_main_sstp_route_does_not_override(self):
        doc=fixture()
        doc["ROUTES"].append("1 s dst-address=142.251.1.1/32 routing-table=main "
                             "gateway=sstp-provider immediate-gw=sstp-provider")
        doc["ROUTES_AFTER"]=doc["ROUTES"][:]
        self.assertTrue(decide(doc)["router_verified"])

    def test_nondefault_vrf_refuses(self):
        doc=fixture()
        doc["VRF"]=["0 name=main interfaces=ether1",
                    "1 name=transit interfaces=bridge"]
        self.assertEqual(decide(doc)["reason"],"nondefault_vrf_unverified")

    def test_routing_rule_refuses(self):
        doc=fixture()
        doc["RULES"]=["0 src-address=192.168.1.34/32 action=lookup "
                      "table=r_to_vpn"]
        self.assertEqual(decide(doc)["reason"],"routing_rules_unverified")

    def test_other_ipsec_tunnel_policy_refuses(self):
        doc=fixture()
        doc["IPSEC"].append("3 action=encrypt src-address=0.0.0.0/0 "
                             "dst-address=0.0.0.0/0 protocol=all")
        self.assertEqual(decide(doc)["reason"], "ipsec_policy_unverified")

    def test_l2tp_policy_restricted_to_its_exact_peer_port(self):
        doc=fixture()
        doc["IPSEC"].append("4 D peer=l2tp-in-server tunnel=no "
                             "src-address=203.0.113.22/32 src-port=1701 "
                             "dst-address=142.251.1.1/32 dst-port=52123 "
                             "protocol=udp action=encrypt")
        self.assertEqual(decide(doc, protocol="udp",port=52123)["reason"],
                         "endpoint_matches_ipsec_policy")
        self.assertEqual(decide(doc, protocol="udp",port=8443)["mode"],"DIRECT")

    def test_hotspot_policy_refuses(self):
        doc=fixture()
        doc["HOTSPOT"].append("0 name=hotspot1 interface=bridge disabled=no")
        self.assertEqual(decide(doc)["reason"],"unsupported_packet_interception")

    def test_raw_rules_refuse(self):
        doc=fixture()
        doc["RAW"]=["0 chain=prerouting action=drop src-address=0.0.0.0/0"]
        self.assertEqual(decide(doc)["reason"],"unsupported_packet_interception")

    def test_bridge_filter_refuses(self):
        doc=fixture()
        doc["BRIDGE_FILTER"]=["0 chain=forward action=mark-packet"]
        self.assertEqual(decide(doc)["reason"],"unsupported_packet_interception")

    def test_unexpected_dstnat_refuses(self):
        doc=fixture()
        doc["NAT"].append("3 chain=dstnat action=redirect protocol=tcp dst-port=443")
        self.assertEqual(decide(doc)["reason"],"unsupported_destination_nat")

    def test_dns_port_interception_refuses_but_web_can_pass(self):
        self.assertEqual(decide(port=53,protocol="udp")["reason"],"dns_port_intercepted")
        self.assertEqual(decide(port=53,protocol="tcp")["reason"],"dns_port_intercepted")
        self.assertEqual(decide(port=443,protocol="tcp")["mode"],"DIRECT")

    def test_unsupported_wan_membership_refuses(self):
        doc=fixture()
        doc["WAN"].append("2 list=WAN interface=sstp-provider dynamic=no")
        self.assertEqual(decide(doc)["reason"],"unknown_wan_or_lan_membership")

    def test_incomplete_and_mutating_snapshot_refuse(self):
        doc=fixture()
        doc["ROUTES_AFTER"].append("1 As dst-address=1.2.3.4/32")
        self.assertEqual(decide(doc)["reason"],"router_policy_changed")
        del doc["ROUTES"]
        self.assertEqual(decide(doc)["reason"],"incomplete_policy_snapshot")

    def test_private_and_hostname_destination_refuses(self):
        self.assertFalse(decide(ip="10.1.1.1")["router_verified"])
        self.assertFalse(decide(ip="node.example.com")["router_verified"])

    def test_invalid_transport_port_refuses(self):
        self.assertFalse(decide(port=0)["router_verified"])
        self.assertFalse(decide(protocol="icmp")["router_verified"])

    def test_snapshot_protocol_has_balanced_markers(self):
        data=fixture()
        lines=[]
        for key in m.ORDER:
            lines.append(f"{m.MARKER}{key}__")
            lines.extend(data[key])
        lines.append(f"{m.MARKER}END__")
        parsed=m.parse_sections("\r\n".join(lines))
        self.assertEqual(parsed, data)
        with self.assertRaisesRegex(ValueError,"incomplete"):
            m.parse_sections("\n".join(lines[:-1]))
        with self.assertRaisesRegex(ValueError,"duplicate"):
            m.parse_sections("\n".join([lines[0],lines[0],*lines[1:]]))

    def test_ssh_runner_prohibits_password_and_hostkey_bypass(self):
        args=[]
        def runner(command, **kwargs):
            args.append(command)
            doc=fixture()
            lines=[]
            for key in m.ORDER:
                lines += [f"{m.MARKER}{key}__", *doc[key]]
            lines += [f"{m.MARKER}END__"]
            return types.SimpleNamespace(returncode=0, stdout="\n".join(lines))
        result=m.router_snapshot(runner=runner)
        joined=" ".join(args[0])
        self.assertIn("StrictHostKeyChecking=yes",joined)
        self.assertIn("BatchMode=yes",joined)
        self.assertNotIn("set ",args[0][-1])
        self.assertEqual(result["VRF"],fixture()["VRF"])

    def test_ssh_invalid_alias_rejected_before_process(self):
        with self.assertRaises(ValueError):
            m.router_snapshot("-oBad")
        with self.assertRaises(ValueError):
            m.router_snapshot("something;:set")

    def test_attest_refuses_pi_source_route_mismatch(self):
        called=[]
        def loader(*args):
            called.append("ssh")
            return fixture()
        att=m.attest_ip(IP,443,"tcp",SRC,"eth0",GATEWAY,
                        snapshot_loader=loader,alias_check=lambda *x:True,
                        local_check=lambda *x:False)
        self.assertFalse(att["router_verified"])
        self.assertEqual(called,[])

    def test_attest_refuses_changed_pi_route_after_ssh(self):
        passes=iter([True,False])
        att=m.attest_ip(IP,443,"tcp",SRC,"eth0",GATEWAY,
                        snapshot_loader=lambda *_: fixture(),
                        alias_check=lambda *x:True,
                        local_check=lambda *x:next(passes))
        self.assertEqual(att["reason"],"pi_route_changed_during_audit")

    def test_alias_must_point_to_current_gateway(self):
        called=[]
        result=m.attest_ip(IP,443,"tcp",SRC,"eth0",GATEWAY,
                           alias_check=lambda *args:False,
                           local_check=lambda *args:called.append(1) or True)
        self.assertEqual(called,[])
        self.assertFalse(result["router_verified"])

    def test_batch_reuses_one_ssh_snapshot_and_checks_all_routes_twice(self):
        calls=[]
        def loader(*args):
            calls.append("ssh")
            return fixture()
        def local(ip, *_):
            calls.append("route_" + ip)
            return True
        result=m.attest_batch(
            [{"ip":IP,"port":443,"protocol":"tcp"},
             {"ip":IP,"port":51820,"protocol":"udp"}],
            SRC,"eth0",GATEWAY,
            snapshot_loader=loader,
            local_check=local,alias_check=lambda *args:True)
        self.assertEqual(calls.count("ssh"), 1)
        self.assertEqual(calls.count("route_"+IP), 4)
        self.assertTrue(all(row["router_verified"] for row in result))

    def test_batch_changed_route_is_never_promoted(self):
        used=0
        def local(*args):
            nonlocal used
            used+=1
            return used==1
        results=m.attest_batch([{"ip":IP,"port":443,"protocol":"tcp"}],
                               SRC,"eth0",GATEWAY,
                               snapshot_loader=lambda _:fixture(),
                               local_check=local,alias_check=lambda *args:True)
        self.assertEqual(results[0]["reason"],"pi_route_changed_during_audit")
        self.assertFalse(results[0]["router_verified"])

    def test_batch_rejects_large_job(self):
        with self.assertRaises(ValueError):
            m.attest_batch([{}]*21,SRC,"eth0",GATEWAY)

    def test_batch_no_local_routes_never_uses_ssh(self):
        out=m.attest_batch([{"ip":IP,"port":443,"protocol":"tcp"}],
                            SRC,"eth0",GATEWAY,
                            snapshot_loader=lambda *x:self.fail("SSH not allowed"),
                            local_check=lambda *x:False,
                            alias_check=lambda *x:True)
        self.assertEqual(out[0]["reason"],"local_route_unverified")

    def test_attestation_is_bound_and_expires(self):
        proof=m.attest_ip(IP,443,"tcp",SRC,"eth0",GATEWAY,
                          snapshot_loader=lambda *_: fixture(),
                          alias_check=lambda *x:True,
                          local_check=lambda *x:True)
        self.assertEqual(proof["valid_for_seconds"],30)
        self.assertEqual(len(proof["endpoint_binding_sha256"]),64)
        altered=m.attest_ip(IP,8443,"tcp",SRC,"eth0",GATEWAY,
                            snapshot_loader=lambda *_:fixture(),
                            alias_check=lambda *x:True,
                            local_check=lambda *x:True)
        self.assertNotEqual(proof["endpoint_binding_sha256"],altered["endpoint_binding_sha256"])


if __name__ == "__main__":
    unittest.main()
