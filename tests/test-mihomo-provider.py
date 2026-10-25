#!/usr/bin/env python3
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

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

    print("=== provider adapter: native Mihomo YAML ===")
    native_raw = td / "native-full.yaml"
    native_out = td / "native-normalized.yaml"
    native_raw.write_text(
        """proxies:
  - name: Native
    type: vless
    server: 192.0.2.20
    port: 443
    uuid: 11111111-1111-1111-1111-111111111111
proxy-groups:
  - name: SHOULD-BE-DROPPED
    type: select
    proxies: [Native]
rules:
  - MATCH,DIRECT
""",
        encoding="utf-8",
    )
    cp = run("normalize", native_raw, native_out)
    assert "MIHOMO_PROVIDER_FORMAT_DETECTED=mihomo" in cp.stdout
    normalized = native_out.read_text(encoding="utf-8")
    assert "SHOULD-BE-DROPPED" not in normalized
    assert "rules:" not in normalized
    assert "11111111-1111-1111-1111-111111111111" in normalized
    assert len(json.loads(run("list", native_out).stdout)) == 1

    print("=== provider adapter: plain VLESS Reality/TCP ===")
    reality_raw = td / "reality.txt"
    reality_out = td / "reality.yaml"
    reality_raw.write_text(
        "vless://11111111-1111-1111-1111-111111111111@45.86.66.170:443"
        "?encryption=none&security=reality&sni=www.cloudflare.com&fp=chrome"
        "&pbk=PUBLICKEY123&sid=abcd&type=tcp&flow=xtls-rprx-vision"
        "#Finland%20Reality\n",
        encoding="utf-8",
    )
    cp = run("normalize", reality_raw, reality_out)
    assert "MIHOMO_PROVIDER_FORMAT_DETECTED=vless" in cp.stdout
    reality = yaml.safe_load(reality_out.read_text(encoding="utf-8"))["proxies"][0]
    assert reality["name"] == "Finland Reality"
    assert reality["type"] == "vless"
    assert reality["server"] == "45.86.66.170"
    assert reality["port"] == 443
    assert reality["uuid"] == "11111111-1111-1111-1111-111111111111"
    assert reality["network"] == "tcp"
    assert reality["tls"] is True
    assert reality["servername"] == "www.cloudflare.com"
    assert reality["client-fingerprint"] == "chrome"
    assert reality["flow"] == "xtls-rprx-vision"
    assert reality["reality-opts"] == {"public-key": "PUBLICKEY123", "short-id": "abcd"}

    print("=== provider adapter: plain VLESS WebSocket/TLS ===")
    ws_raw = td / "ws.txt"
    ws_out = td / "ws.yaml"
    ws_raw.write_text(
        "vless://22222222-2222-2222-2222-222222222222@edge.example.com:443"
        "?encryption=none&security=tls&sni=edge.example.com&type=ws"
        "&path=%2Fws&host=cdn.example.com#WS%20TLS\n",
        encoding="utf-8",
    )
    run("normalize", ws_raw, ws_out, "--format", "vless")
    ws = yaml.safe_load(ws_out.read_text(encoding="utf-8"))["proxies"][0]
    assert ws["network"] == "ws"
    assert ws["tls"] is True
    assert ws["ws-opts"]["path"] == "/ws"
    assert ws["ws-opts"]["headers"]["Host"] == "cdn.example.com"

    print("=== provider adapter: base64 VLESS subscription ===")
    b64_raw = td / "subscription.b64"
    b64_out = td / "subscription.yaml"
    vless_lines = (
        "vless://11111111-1111-1111-1111-111111111111@192.0.2.30:443"
        "?encryption=none&security=none&type=tcp#One\n"
        "vless://22222222-2222-2222-2222-222222222222@192.0.2.31:443"
        "?encryption=none&security=none&type=grpc&serviceName=edge#Two\n"
    )
    b64_raw.write_text(base64.b64encode(vless_lines.encode()).decode().rstrip("="), encoding="utf-8")
    cp = run("normalize", b64_raw, b64_out)
    assert "MIHOMO_PROVIDER_FORMAT_DETECTED=base64" in cp.stdout
    b64_nodes = yaml.safe_load(b64_out.read_text(encoding="utf-8"))["proxies"]
    assert [node["name"] for node in b64_nodes] == ["One", "Two"]
    assert b64_nodes[1]["grpc-opts"]["grpc-service-name"] == "edge"

    print("=== provider adapter: explicit mismatch and unsupported transport ===")
    cp = run("normalize", reality_raw, td / "wrong.yaml", "--format", "mihomo", ok=False)
    assert cp.returncode != 0
    assert "not a Mihomo/Clash" in cp.stderr

    unsupported = td / "unsupported.txt"
    unsupported.write_text(
        "vless://33333333-3333-3333-3333-333333333333@192.0.2.40:443"
        "?encryption=none&security=tls&type=splithttp#Unsupported\n",
        encoding="utf-8",
    )
    cp = run("normalize", unsupported, td / "unsupported.yaml", ok=False)
    assert cp.returncode != 0
    assert "unsupported transport" in cp.stderr

    malformed = td / "malformed.txt"
    malformed.write_text(
        "vless://11111111-1111-1111-1111-111111111111@example.com:notaport"
        "?encryption=none&security=none&type=tcp#BadPort\n",
        encoding="utf-8",
    )
    cp = run("normalize", malformed, td / "malformed.yaml", ok=False)
    assert cp.returncode != 0
    assert "invalid server/port" in cp.stderr
    assert "Traceback" not in cp.stderr

    bad = td / "bad.yaml"
    bad.write_text("rules: []\n", encoding="utf-8")
    cp = run("list", bad, ok=False)
    assert cp.returncode != 0
    assert "proxies" in cp.stderr

print("mihomo provider metadata parser: OK")
