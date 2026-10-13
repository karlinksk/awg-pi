#!/usr/bin/env python3
"""Read-only Mihomo active outbound from a local controller; never changes selection."""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def read_active(config_path, group="AWG-MIHOMO", timeout=1.5):
    try:
        import yaml
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            return "unknown (invalid configuration)"
        groups = config.get("proxy-groups", [])
        match = [x for x in groups if isinstance(x, dict) and x.get("name") == group]
        if len(match) != 1 or match[0].get("type") not in ("select", "fallback", "url-test"):
            return "unknown (no supported group)"
        controller = config.get("external-controller", "")
        host, port = controller.rsplit(":", 1)
        if host not in ("127.0.0.1", "localhost", "[::1]") or not port.isdigit() or not 1 <= int(port) <= 65535:
            return "unknown (no loopback controller)"
        headers = {}
        if config.get("secret"):
            headers["Authorization"] = "Bearer " + str(config["secret"])
        url = "http://" + controller + "/proxies/" + urllib.parse.quote(group, safe="")
        req = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as response:
            payload = json.loads(response.read(65536).decode("utf-8"))
        active = payload.get("now") if isinstance(payload, dict) else None
        allowed = set(match[0].get("proxies") or []) | set(payload.get("all") or [])
        if isinstance(active, str) and active and active in allowed and "\n" not in active and "\r" not in active:
            return active
        return "unknown (controller did not identify allowed node)"
    except Exception:
        return "unknown (controller unavailable)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--group", default="AWG-MIHOMO")
    args = ap.parse_args()
    print(read_active(args.config, args.group))


if __name__ == "__main__":
    main()
