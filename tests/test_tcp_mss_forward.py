"""Rendered VPN MSS rules plus opt-in real, isolated Linux forwarding checks."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


def render(mode="transit", transport="awg", lockdown=False, mac="02:11:22:33:44:55"):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / "env").write_text("LAN_IF=eth0\nLAN_CIDR=192.0.2.0/24\n"
                               "ROUTER_IP=192.0.2.1\nVPN_IF=awg0\n"
                               "VPN_MARK=0x100\nVPN_TABLE=100\nDNS_REDIRECT=0\n")
        (p / "mode").write_text(mode)
        (p / "transport").write_text(transport)
        (p / "clients").write_text("")
        env = dict(os.environ, AWG_ENV_FILE=str(p / "env"),
                   AWG_COMMON_FILE=str(ROOT / "src/awg-common"),
                   AWG_MODE_FILE=str(p / "mode"), AWG_TRANSPORT_FILE=str(p / "transport"),
                   ROUTER_MAC=mac, AWG_TRANSIT_LOCKDOWN=str(int(lockdown)))
        if mode == "transit":
            return subprocess.check_output(["bash", str(ROOT / "src/awg-transit-nft")],
                                           env=env, text=True)
        # Execute the real Selective renderer without touching live nft/ip state.
        for name, text in {
            "nft": '#!/bin/sh\n[ "$1" != list ]\n',
            "ip": '#!/bin/sh\ncase "$*" in *"rule del"*) exit 2;; esac\nexit 0\n',
        }.items():
            f = p / name
            f.write_text(text)
            f.chmod(0o755)
        env.update(AWG_CLIENTS_FILE=str(p / "clients"), AWG_NFT_FILE=str(p / "rules"),
                   AWG_SETUP_LOCK_FILE=str(p / "setup.lock"),
                   NFT_BIN=str(p / "nft"), IP_BIN=str(p / "ip"))
        subprocess.run(["bash", str(ROOT / "src/awg-pbr-setup")],
                       env=env, check=True, capture_output=True, text=True)
        return (p / "rules").read_text()


@unittest.skipUnless(shutil.which("bash"), "Bash renderer required")
class RenderedMss(unittest.TestCase):
    def test_active_vpn_scope_and_guard_are_preserved(self):
        for mode in ("transit", "selective"):
            for transport, interface in (("awg", "awg0"), ("mihomo", "mihomo0")):
                with self.subTest(mode=mode, transport=transport):
                    rules = render(mode, transport)
                    lines = [s for s in rules.splitlines() if "tcp option maxseg" in s]
                    self.assertEqual(len(lines), 1)
                    line = lines[0]
                    self.assertIn('iifname "eth0"', line)
                    self.assertIn('oifname "' + interface + '"', line)
                    self.assertIn("meta nfproto ipv4", line)
                    self.assertIn("tcp flags & (syn | rst) == syn", line)
                    self.assertIn("tcp option maxseg size set rt mtu", line)
                    self.assertNotIn("accept", line)
                    self.assertIn("policy drop;", rules)
                    if mode == "transit":
                        self.assertIn("ether saddr 02:11:22:33:44:55 ip saddr @transit4", line)
                        self.assertNotIn('oifname "eth0" accept', rules)
                    else:
                        self.assertIn("ip saddr 192.0.2.0/24", line)
                        self.assertIn('oifname "eth0" accept', rules)

    def test_lockdown_and_unconfigured_do_not_mangle(self):
        self.assertNotIn("tcp option maxseg", render(lockdown=True))
        self.assertNotIn("tcp option maxseg", render(transport="unconfigured", lockdown=True))
        self.assertNotIn("tcp option maxseg", render("selective", "unconfigured"))


@unittest.skipUnless(os.environ.get("AWG_MSS_NETNS_TEST") == "1"
                     and hasattr(os, "geteuid") and os.geteuid() == 0
                     and shutil.which("ip") and shutil.which("nft"),
                     "Explicit root opt-in required for disposable network namespaces")
class RealForwardedMss(unittest.TestCase):
    def test_vpn_route_clamps_large_mss_and_preserves_small_mss(self):
        tag = uuid.uuid4().hex[:7]
        client, gateway, server = ["mss-" + x + "-" + tag for x in "cgs"]
        namespaces, links = [], []

        def run(*args, **kw):
            return subprocess.check_output(list(args), text=True, stderr=subprocess.STDOUT,
                                           timeout=15, **kw)

        def ip(ns, *args):
            return run("ip", "-n", ns, *args)

        try:
            for ns in (client, gateway, server):
                run("ip", "netns", "add", ns)
                namespaces.append(ns)
                ip(ns, "link", "set", "lo", "up")
                run("ip", "netns", "exec", ns, "sysctl", "-qw", "net.ipv4.tcp_timestamps=0")
            for left, right, lns, rns, lname, rname in (
                ("mc" + tag, "mg" + tag, client, gateway, "eth0", "eth0"),
                ("ms" + tag, "mp" + tag, gateway, server, "awg0", "eth0"),
            ):
                run("ip", "link", "add", left, "type", "veth", "peer", "name", right)
                links.append(left)
                run("ip", "link", "set", left, "netns", lns)
                run("ip", "link", "set", right, "netns", rns)
                ip(lns, "link", "set", left, "name", lname)
                ip(rns, "link", "set", right, "name", rname)
            for ns, dev, addr, mtu in (
                (client, "eth0", "192.0.2.2/24", "1500"),
                (gateway, "eth0", "192.0.2.1/24", "1500"),
                (gateway, "awg0", "198.51.100.1/24", "1420"),
                (server, "eth0", "198.51.100.2/24", "1500"),
            ):
                ip(ns, "link", "set", dev, "mtu", mtu, "up")
                ip(ns, "addr", "add", addr, "dev", dev)
            ip(client, "route", "add", "default", "via", "192.0.2.1")
            ip(server, "route", "add", "default", "via", "198.51.100.1")
            run("ip", "netns", "exec", gateway, "sysctl", "-qw", "net.ipv4.ip_forward=1")
            mac = json.loads(ip(client, "-j", "link", "show", "eth0"))[0]["address"]
            rules = render(mac=mac)

            def apply(text):
                run("ip", "netns", "exec", gateway, "nft", "-f", "-",
                    input="flush ruleset\n" + text)

            def observed_mss(port, small=False):
                program = ("import socket; s=socket.socket(); s.bind(('0.0.0.0'," + str(port) + "));"
                           "s.listen(); print('READY',flush=True); c,_=s.accept(); c.recv(1);"
                           "c.sendall(str(c.getsockopt(socket.IPPROTO_TCP,socket.TCP_MAXSEG)).encode()); c.close()")
                proc = subprocess.Popen(["ip", "netns", "exec", server, "python3", "-u", "-c", program],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    self.assertTrue(select.select([proc.stdout], [], [], 5)[0], "server startup timeout")
                    self.assertEqual(proc.stdout.readline().strip(), "READY")
                    program = ("import socket; s=socket.socket(); s.settimeout(5);" +
                               ("s.setsockopt(socket.IPPROTO_TCP,socket.TCP_MAXSEG,536);" if small else "") +
                               "s.connect(('198.51.100.2'," + str(port) + "));s.sendall(b'x');print(s.recv(32).decode())")
                    return int(run("ip", "netns", "exec", client, "python3", "-c", program).strip())
                finally:
                    proc.terminate()
                    proc.communicate(timeout=5)

            apply("\n".join(s for s in rules.splitlines() if "tcp option maxseg" not in s))
            self.assertGreater(observed_mss(19001), 1380)
            apply(rules)
            self.assertEqual(observed_mss(19002), 1380)
            self.assertLessEqual(observed_mss(19003, small=True), 536)
        finally:
            for ns in reversed(namespaces):
                subprocess.run(["ip", "netns", "del", ns], capture_output=True)
            for link in links:
                subprocess.run(["ip", "link", "del", link], capture_output=True)


if __name__ == "__main__":
    unittest.main()
