#!/usr/bin/env python3
"""Isolated real Mihomo controller test for proxy-group boot selection.

No TUN, no LAN bind, no real proxy endpoint connection, no service changes.
"""
from pathlib import Path
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
import yaml

MIHOMO=Path("/usr/local/bin/mihomo")


def free_port():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]


class SelectorDefaultRuntime(unittest.TestCase):
    def test_default_selected_is_effective_not_just_parser_accepted(self):
        if not MIHOMO.is_file():
            self.skipTest("Test Pi Mihomo executable unavailable")
        with tempfile.TemporaryDirectory(prefix="awg-xray-select-test-",dir="/dev/shm") as d:
            port=free_port()
            config={
              "mixed-port":0, "mode":"rule", "log-level":"silent",
              "ipv6":False, "external-controller":f"127.0.0.1:{port}",
              "profile":{"store-selected":False,"store-fake-ip":False},
              "proxies":[
                {"name":"NATIVE-ONE","type":"socks5","server":"127.0.0.1","port":9},
                {"name":"NATIVE-TWO","type":"socks5","server":"127.0.0.1","port":10}
              ],
              "proxy-groups":[{
                "name":"AWG-MIHOMO","type":"select",
                "proxies":["NATIVE-ONE","NATIVE-TWO"],
                "default-selected":"NATIVE-TWO"
              }],
              "rules":["MATCH,AWG-MIHOMO"]
            }
            config_path=Path(d)/"config.yaml"
            config_path.write_text(yaml.safe_dump(config))
            verify=subprocess.run([str(MIHOMO),"-t","-d",d,"-f",str(config_path)],
                stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15)
            self.assertEqual(verify.returncode,0,verify.stderr[-800:])
            proc=subprocess.Popen([str(MIHOMO),"-d",d,"-f",str(config_path)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                now=None
                for _ in range(50):
                    if proc.poll() is not None:
                        self.fail("isolated Mihomo exited before exposing controller")
                    try:
                        with urllib.request.urlopen(
                          f"http://127.0.0.1:{port}/proxies/AWG-MIHOMO",timeout=.3) as r:
                            now=json.load(r).get("now")
                        break
                    except (OSError,ValueError):
                        time.sleep(.08)
                self.assertEqual(now,"NATIVE-TWO","Mihomo ignored config default-selected")
            finally:
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)


if __name__=="__main__":unittest.main()
