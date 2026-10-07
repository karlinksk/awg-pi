#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "src" / "awg-mihomo-provider.py"


def run(*args, ok=True):
    cp = subprocess.run(
        [sys.executable, str(HELPER), *map(str, args)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if ok and cp.returncode != 0:
        raise AssertionError(f"command failed rc={cp.returncode}: {cp.stderr}")
    return cp


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    provider = td / "provider.yaml"
    provider.write_text(
        """proxies:
  - name: "🇫🇮 Finland"
    type: vless
    server: 45.86.66.170
    port: 443
    uuid: SECRET-UUID-MUST-NOT-LEAK
    reality-opts:
      public-key: SECRET-PUBLIC-KEY
  - name: "DE (backup)+1"
    type: vless
    server: 203.0.113.7
    port: 443
    uuid: ANOTHER-SECRET
""",
        encoding="utf-8",
    )

    listed = json.loads(run("list", provider).stdout)
    assert len(listed) == 2
    assert listed[0] == {
        "index": 1,
        "name": "🇫🇮 Finland",
        "type": "vless",
        "server": "45.86.66.170",
        "port": 443,
        "duplicate_name": False,
    }
    serialized = json.dumps(listed, ensure_ascii=False)
    assert "SECRET" not in serialized
    assert "uuid" not in serialized
    assert "public-key" not in serialized

    fi = json.loads(run("info", provider, "🇫🇮 Finland").stdout)
    assert fi["endpoint_ips"] == ["45.86.66.170"]
    assert fi["filter_regex"] == "^🇫🇮 Finland$"

    de = json.loads(run("info", provider, "DE (backup)+1").stdout)
    assert de["endpoint_ips"] == ["203.0.113.7"]
    assert de["filter_regex"] == r"^DE \(backup\)\+1$"

    duplicate = td / "duplicate.yaml"
    duplicate.write_text(
        """proxies:
  - {name: same, type: vless, server: 192.0.2.1, port: 443}
  - {name: same, type: vless, server: 192.0.2.2, port: 443}
""",
        encoding="utf-8",
    )
    dup_list = json.loads(run("list", duplicate).stdout)
    assert dup_list[1]["duplicate_name"] is True
    cp = run("info", duplicate, "same", ok=False)
    assert cp.returncode != 0
    assert "not unique" in cp.stderr

    bad = td / "bad.yaml"
    bad.write_text("rules: []\n", encoding="utf-8")
    cp = run("list", bad, ok=False)
    assert cp.returncode != 0
    assert "proxies" in cp.stderr

print("mihomo provider metadata parser: OK")
