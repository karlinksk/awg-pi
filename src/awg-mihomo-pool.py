#!/usr/bin/env python3
"""Health-pool scanner for AWG Pi Gateway Mihomo providers.

The scanner launches an isolated Mihomo instance with no TUN interface, probes
all provider nodes through Mihomo's controller API, and optionally determines
actual egress country through the selected proxy. Runtime health data lives in
/run by default so periodic scans do not create microSD write churn.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml

MIHOMO_BIN = os.environ.get("MIHOMO_BIN", "/usr/local/bin/mihomo")
CURL_BIN = os.environ.get("CURL_BIN", "curl")
LIVE_PROVIDER = Path(os.environ.get("MIHOMO_PROVIDER_FILE", "/var/lib/awg-pbr/mihomo/providers/subscription.yaml"))
CANDIDATE_PROVIDER = Path(os.environ.get("MIHOMO_CANDIDATE_FILE", "/var/lib/awg-pbr/mihomo/providers/candidate.yaml"))
POOL_DIR = Path(os.environ.get("MIHOMO_POOL_DIR", "/run/awg-pbr/mihomo-pool"))
LIVE_POOL = Path(os.environ.get("MIHOMO_LIVE_POOL_FILE", str(POOL_DIR / "live.json")))
CANDIDATE_POOL = Path(os.environ.get("MIHOMO_CANDIDATE_POOL_FILE", str(POOL_DIR / "candidate.json")))
POLICY_FILE = Path(os.environ.get("MIHOMO_POOL_POLICY_FILE", "/etc/awg-pbr/transports/mihomo/pool-policy.env"))
COOLDOWN_FILE = Path(os.environ.get("MIHOMO_POOL_COOLDOWN_FILE", str(POOL_DIR / "cooldown.json")))
HEALTH_URL = os.environ.get("MIHOMO_POOL_HEALTH_URL", "https://www.gstatic.com/generate_204")
GEO_URL = os.environ.get("MIHOMO_POOL_GEO_URL", "https://www.cloudflare.com/cdn-cgi/trace")
DELAY_TIMEOUT_MS = int(os.environ.get("MIHOMO_POOL_DELAY_TIMEOUT_MS", "4500"))
WORKERS = max(1, min(64, int(os.environ.get("MIHOMO_POOL_WORKERS", "24"))))
COOLDOWN_SECONDS = int(os.environ.get("MIHOMO_POOL_COOLDOWN_SECONDS", "900"))

# Geographic Europe, intentionally excluding RU for the anti-blocking pool.
EUROPE_CODES = {
    "AD", "AL", "AT", "AX", "BA", "BE", "BG", "BY", "CH", "CY", "CZ",
    "DE", "DK", "EE", "ES", "FI", "FO", "FR", "GB", "GG", "GI", "GR",
    "HR", "HU", "IE", "IM", "IS", "IT", "JE", "LI", "LT", "LU", "LV",
    "MC", "MD", "ME", "MK", "MT", "NL", "NO", "PL", "PT", "RO", "RS",
    "SE", "SI", "SJ", "SK", "SM", "TR", "UA", "VA", "XK",
}


def die(message: str, code: int = 2) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def target_paths(target: str) -> tuple[Path, Path]:
    if target == "live":
        return LIVE_PROVIDER, LIVE_POOL
    if target == "candidate":
        return CANDIDATE_PROVIDER, CANDIDATE_POOL
    die(f"Unsupported pool target: {target}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            value = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        die(f"Unable to read Mihomo pool state {path}: {exc}", 1)
    if not isinstance(value, dict):
        die(f"Invalid Mihomo pool state: {path}", 1)
    return value


def read_provider(path: Path) -> list[dict]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        die(f"Unable to read Mihomo provider {path}: {exc}", 1)
    proxies = data.get("proxies") if isinstance(data, dict) else None
    if not isinstance(proxies, list) or not proxies:
        die(f"Mihomo provider has no proxies: {path}", 1)
    return proxies


def clean_node(raw: object, index: int) -> dict:
    if not isinstance(raw, dict):
        return {"index": index, "valid": False, "reason": "not-a-mapping"}
    name = raw.get("name")
    ptype = raw.get("type")
    server = raw.get("server")
    port = raw.get("port")
    if not all(isinstance(v, str) and v and not any(c in v for c in "\r\n\t") for v in (name, ptype, server)):
        return {"index": index, "valid": False, "reason": "invalid-metadata"}
    if isinstance(port, str) and port.isdigit():
        port = int(port)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return {"index": index, "valid": False, "reason": "invalid-port"}
    return {
        "index": index,
        "valid": True,
        "name": name,
        "type": ptype,
        "server": server,
        "port": port,
        "raw": raw,
    }


def choose_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def controller_request(port: int, path: str, *, method: str = "GET", payload: dict | None = None, timeout: float = 3.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))


def wait_controller(proc: subprocess.Popen, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            controller_request(port, "/version", timeout=0.5)
            return
        except Exception as exc:  # controller is not ready yet
            last_error = str(exc)
            time.sleep(0.1)
    try:
        output = proc.stdout.read() if proc.stdout is not None else ""
    except Exception:
        output = ""
    detail = output[-1500:].strip() or last_error or "unknown startup error"
    die(f"Isolated Mihomo probe failed to start: {detail}", 1)


def make_probe_config(raw_nodes: list[dict], mixed_port: int, controller_port: int) -> tuple[dict, list[dict]]:
    seen_names: dict[str, int] = {}
    clean: list[dict] = []
    for index, raw in enumerate(raw_nodes, start=1):
        item = clean_node(raw, index)
        if not item.get("valid"):
            clean.append(item)
            continue
        seen_names[item["name"]] = seen_names.get(item["name"], 0) + 1
        clean.append(item)

    probe_proxies: list[dict] = []
    probe_names: list[str] = []
    for item in clean:
        if not item.get("valid"):
            continue
        probe = copy.deepcopy(item["raw"])
        probe_name = f"AWG-PROBE-{item['index']:06d}"
        probe["name"] = probe_name
        item["probe_name"] = probe_name
        item["duplicate_name"] = seen_names.get(item["name"], 0) > 1
        probe_proxies.append(probe)
        probe_names.append(probe_name)

    if not probe_proxies:
        die("Mihomo provider contains no probeable nodes", 1)

    config = {
        "mixed-port": mixed_port,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "mode": "rule",
        "log-level": "error",
        "ipv6": False,
        "external-controller": f"127.0.0.1:{controller_port}",
        "profile": {"store-selected": False, "store-fake-ip": False},
        "proxies": probe_proxies,
        "proxy-groups": [
            {"name": "AWG-PROBE-GROUP", "type": "select", "proxies": probe_names}
        ],
        "rules": ["MATCH,AWG-PROBE-GROUP"],
    }
    return config, clean


def probe_delay(controller_port: int, item: dict) -> tuple[bool, int | None, str]:
    if not item.get("valid"):
        return False, None, item.get("reason", "invalid")
    if item.get("duplicate_name"):
        # The live selector requires an exact unique provider name.
        return False, None, "duplicate-name"
    encoded = urllib.parse.quote(item["probe_name"], safe="")
    query = urllib.parse.urlencode({"url": HEALTH_URL, "timeout": DELAY_TIMEOUT_MS})
    try:
        result = controller_request(
            controller_port,
            f"/proxies/{encoded}/delay?{query}",
            timeout=(DELAY_TIMEOUT_MS / 1000.0) + 2.0,
        )
        delay = result.get("delay")
        if isinstance(delay, int) and delay > 0:
            return True, delay, ""
        return False, None, "no-delay"
    except urllib.error.HTTPError as exc:
        return False, None, f"http-{exc.code}"
    except Exception as exc:
        return False, None, type(exc).__name__


def select_probe(controller_port: int, probe_name: str) -> None:
    encoded = urllib.parse.quote("AWG-PROBE-GROUP", safe="")
    controller_request(
        controller_port,
        f"/proxies/{encoded}",
        method="PUT",
        payload={"name": probe_name},
        timeout=2.0,
    )


def egress_geo(controller_port: int, mixed_port: int, item: dict) -> tuple[str, str, str]:
    try:
        select_probe(controller_port, item["probe_name"])
        result = subprocess.run(
            [
                CURL_BIN,
                "-4fsS",
                "-x",
                f"http://127.0.0.1:{mixed_port}",
                "--connect-timeout",
                "3",
                "--max-time",
                "6",
                GEO_URL,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return "", "", f"curl-{result.returncode}"
        trace: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                trace[key.strip()] = value.strip()
        ip = trace.get("ip", "")
        loc = trace.get("loc", "").upper()
        if not ip or len(loc) != 2:
            return ip, "", "geo-missing"
        return ip, loc, ""
    except Exception as exc:
        return "", "", type(exc).__name__


def scan(target: str, geo: bool) -> dict:
    provider, pool_path = target_paths(target)
    if not provider.is_file():
        die(f"Mihomo {target} provider is missing: {provider}", 1)
    if not os.path.isfile(MIHOMO_BIN) or not os.access(MIHOMO_BIN, os.X_OK):
        die(f"Mihomo binary is unavailable: {MIHOMO_BIN}", 1)

    raw_nodes = read_provider(provider)
    mixed_port = choose_free_port()
    controller_port = choose_free_port()
    while controller_port == mixed_port:
        controller_port = choose_free_port()

    with tempfile.TemporaryDirectory(prefix="awg-mihomo-probe-", dir="/tmp") as tempdir:
        config, nodes = make_probe_config(raw_nodes, mixed_port, controller_port)
        cfg = Path(tempdir) / "config.yaml"
        cfg.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        os.chmod(cfg, 0o600)

        proc = subprocess.Popen(
            [MIHOMO_BIN, "-d", tempdir, "-f", str(cfg)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_controller(proc, controller_port)
            probeable = [item for item in nodes if item.get("valid")]
            completed = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
                futures = {executor.submit(probe_delay, controller_port, item): item for item in probeable}
                for future in concurrent.futures.as_completed(futures):
                    item = futures[future]
                    healthy, delay, error = future.result()
                    item["healthy"] = healthy
                    item["delay_ms"] = delay
                    item["error"] = error
                    completed += 1
                    if completed == 1 or completed % 25 == 0 or completed == len(probeable):
                        print(f"MIHOMO_POOL_HEALTH_PROGRESS={completed}/{len(probeable)}")

            for item in nodes:
                if not item.get("valid"):
                    item["healthy"] = False
                    item["delay_ms"] = None
                    item["error"] = item.get("reason", "invalid")
                item["egress_ip"] = ""
                item["country_code"] = ""
                item["europe"] = False
                item["geo_checked"] = False

            healthy_nodes = [item for item in nodes if item.get("healthy")]
            if geo:
                for n, item in enumerate(sorted(healthy_nodes, key=lambda x: (x.get("delay_ms") or 999999, x["index"])), start=1):
                    ip, loc, geo_error = egress_geo(controller_port, mixed_port, item)
                    item["egress_ip"] = ip
                    item["country_code"] = loc
                    item["europe"] = bool(loc and loc in EUROPE_CODES)
                    item["geo_checked"] = True
                    if geo_error and not item.get("error"):
                        item["geo_error"] = geo_error
                    if n == 1 or n % 10 == 0 or n == len(healthy_nodes):
                        print(f"MIHOMO_POOL_GEO_PROGRESS={n}/{len(healthy_nodes)}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

    now = int(time.time())
    result_nodes: list[dict] = []
    for item in nodes:
        if not item.get("valid"):
            result_nodes.append({
                "index": item["index"],
                "name": f"(invalid #{item['index']})",
                "type": "invalid",
                "server": "",
                "port": 0,
                "healthy": False,
                "delay_ms": None,
                "egress_ip": "",
                "country_code": "",
                "europe": False,
                "geo_checked": False,
                "error": item.get("error", item.get("reason", "invalid")),
            })
            continue
        result_nodes.append({
            "index": item["index"],
            "name": item["name"],
            "type": item["type"],
            "server": item["server"],
            "port": item["port"],
            "duplicate_name": bool(item.get("duplicate_name")),
            "healthy": bool(item.get("healthy")),
            "delay_ms": item.get("delay_ms"),
            "egress_ip": item.get("egress_ip", ""),
            "country_code": item.get("country_code", ""),
            "europe": bool(item.get("europe")),
            "geo_checked": bool(item.get("geo_checked")),
            "error": item.get("error", ""),
            "geo_error": item.get("geo_error", ""),
        })

    payload = {
        "version": 1,
        "target": target,
        "provider_sha256": sha256_file(provider),
        "scanned_at": now,
        "geo_enriched": geo,
        "total": len(result_nodes),
        "healthy": sum(1 for x in result_nodes if x.get("healthy")),
        "europe": sum(1 for x in result_nodes if x.get("healthy") and x.get("europe")),
        "nodes": result_nodes,
    }
    atomic_json(pool_path, payload)
    print(f"MIHOMO_POOL_TARGET={target}")
    print(f"MIHOMO_POOL_TOTAL={payload['total']}")
    print(f"MIHOMO_POOL_HEALTHY={payload['healthy']}")
    print(f"MIHOMO_POOL_EUROPE={payload['europe']}")
    print(f"MIHOMO_POOL_FILE={pool_path}")
    if payload["healthy"] == 0:
        die("Mihomo health scan found no working nodes", 1)
    return payload


def pool_current(target: str, require_geo: bool = False) -> bool:
    provider, pool_path = target_paths(target)
    if not provider.is_file() or not pool_path.is_file():
        return False
    try:
        pool = load_json(pool_path)
        if pool.get("provider_sha256") != sha256_file(provider):
            return False
        if require_geo and not pool.get("geo_enriched"):
            return False
        return True
    except SystemExit:
        return False


def read_policy() -> str:
    try:
        for line in POLICY_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("MIHOMO_POOL_REGION="):
                value = line.split("=", 1)[1].strip()
                if value in {"all", "europe"}:
                    return value
    except OSError:
        pass
    return "all"


def write_policy(value: str) -> None:
    if value not in {"all", "europe"}:
        die("Pool region must be all or europe")
    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(POLICY_FILE.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=".pool-policy.", dir=str(POLICY_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"MIHOMO_POOL_REGION={value}\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, POLICY_FILE)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def load_cooldown() -> dict[str, int]:
    now = int(time.time())
    try:
        data = load_json(COOLDOWN_FILE)
    except SystemExit:
        return {}
    raw = data.get("nodes", {})
    if not isinstance(raw, dict):
        return {}
    return {str(k): int(v) for k, v in raw.items() if isinstance(v, int) and v > now}


def save_cooldown(nodes: dict[str, int]) -> None:
    atomic_json(COOLDOWN_FILE, {"version": 1, "nodes": nodes})


def effective_nodes(pool: dict, *, show_all: bool, ignore_policy: bool, query: str = "") -> list[dict]:
    region = "all" if ignore_policy else read_policy()
    needle = query.casefold().strip()
    result = []
    for node in pool.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if not show_all and not node.get("healthy"):
            continue
        if not show_all and region == "europe" and not node.get("europe"):
            continue
        if needle:
            haystack = " ".join(
                str(node.get(key, ""))
                for key in ("name", "type", "server", "port", "egress_ip", "country_code")
            ).casefold()
            if needle not in haystack:
                continue
        result.append(node)
    result.sort(key=lambda x: (
        0 if x.get("healthy") else 1,
        x.get("delay_ms") if isinstance(x.get("delay_ms"), int) else 999999,
        x.get("index", 999999),
    ))
    return result


def cmd_scan(args) -> None:
    geo = args.geo or (args.geo_if_policy and read_policy() == "europe")
    scan(args.target, geo)


def cmd_ensure(args) -> None:
    require_geo = args.geo or (args.geo_if_policy and read_policy() == "europe")
    if not pool_current(args.target, require_geo=require_geo):
        scan(args.target, require_geo)
    else:
        pool = load_json(target_paths(args.target)[1])
        print(f"MIHOMO_POOL_CURRENT={args.target}")
        print(f"MIHOMO_POOL_TOTAL={pool.get('total', 0)}")
        print(f"MIHOMO_POOL_HEALTHY={pool.get('healthy', 0)}")
        print(f"MIHOMO_POOL_EUROPE={pool.get('europe', 0)}")


def cmd_list(args) -> None:
    _, pool_path = target_paths(args.target)
    if not pool_current(args.target, require_geo=(read_policy() == "europe" and not args.ignore_policy and not args.all)):
        die(f"Mihomo {args.target} health pool is missing or stale; run ensure first", 1)
    pool = load_json(pool_path)
    nodes = effective_nodes(pool, show_all=args.all, ignore_policy=args.ignore_policy, query=args.query or "")
    if args.format == "json":
        json.dump(nodes, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")
        return
    for node in nodes:
        duplicate = "DUPLICATE" if node.get("duplicate_name") else ""
        endpoint = f"{node.get('server', '')}:{node.get('port', '')}"
        health = "HEALTHY" if node.get("healthy") else "DEAD"
        country = node.get("country_code") or "??"
        delay = f"{node['delay_ms']}ms" if isinstance(node.get("delay_ms"), int) else "-"
        print(
            node.get("index", 0),
            node.get("name", ""),
            node.get("type", ""),
            endpoint,
            duplicate,
            health,
            country,
            delay,
            sep="\t",
        )


def cmd_status(args) -> None:
    _, pool_path = target_paths(args.target)
    region = read_policy()
    print(f"Mihomo pool target: {args.target}")
    print(f"Region filter: {region}")
    if not pool_path.is_file():
        print("Pool state: missing")
        return
    pool = load_json(pool_path)
    age = max(0, int(time.time()) - int(pool.get("scanned_at", 0)))
    print("Pool state: ready")
    print(f"Pool age: {age}s")
    print(f"Nodes total: {pool.get('total', 0)}")
    print(f"Nodes healthy: {pool.get('healthy', 0)}")
    print(f"Nodes Europe: {pool.get('europe', 0)}")
    print(f"Geo enriched: {'yes' if pool.get('geo_enriched') else 'no'}")


def cmd_best(args) -> None:
    require_geo = read_policy() == "europe" and not args.ignore_policy
    if not pool_current(args.target, require_geo=require_geo):
        die("Mihomo health pool is missing or stale", 1)
    pool = load_json(target_paths(args.target)[1])
    nodes = effective_nodes(pool, show_all=False, ignore_policy=args.ignore_policy)
    excluded = set(args.exclude or [])
    cooldown = load_cooldown()
    for node in nodes:
        name = str(node.get("name", ""))
        if not name or name in excluded or name in cooldown:
            continue
        print(name)
        return
    die("No healthy Mihomo node matches the current pool policy", 1)


def cmd_policy(args) -> None:
    if args.action == "get":
        print(read_policy())
    elif args.action == "status":
        value = read_policy()
        print(f"MIHOMO_POOL_REGION={value}")
        print(f"Europe only: {'yes' if value == 'europe' else 'no'}")
    elif args.action == "set":
        write_policy(args.value)
        print(f"MIHOMO_POOL_REGION={args.value}")


def cmd_cooldown(args) -> None:
    nodes = load_cooldown()
    if args.action == "clear":
        save_cooldown({})
        print("MIHOMO_POOL_COOLDOWN=CLEARED")
        return
    if args.action == "add":
        nodes[args.name] = int(time.time()) + int(args.seconds)
        save_cooldown(nodes)
        print(f"MIHOMO_POOL_COOLDOWN={args.name}")
        return
    if args.action == "status":
        now = int(time.time())
        for name, expiry in sorted(nodes.items()):
            print(f"{name}\t{max(0, expiry - now)}s")


def cmd_clear(args) -> None:
    _, pool_path = target_paths(args.target)
    try:
        pool_path.unlink()
    except FileNotFoundError:
        pass
    print(f"MIHOMO_POOL_CLEARED={args.target}")


def cmd_promote(_args) -> None:
    if not CANDIDATE_POOL.is_file():
        print("MIHOMO_POOL_PROMOTE=NO_CANDIDATE")
        return
    LIVE_POOL.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(LIVE_POOL.parent, 0o700)
    payload = load_json(CANDIDATE_POOL)
    payload["target"] = "live"
    atomic_json(LIVE_POOL, payload)
    try:
        CANDIDATE_POOL.unlink()
    except FileNotFoundError:
        pass
    print("MIHOMO_POOL_PROMOTE=OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="AWG Pi Gateway Mihomo health pool")
    sub = parser.add_subparsers(dest="command", required=True)

    for command in ("scan", "ensure"):
        p = sub.add_parser(command)
        p.add_argument("target", choices=("live", "candidate"))
        p.add_argument("--geo", action="store_true")
        p.add_argument("--geo-if-policy", action="store_true")
        p.set_defaults(func=cmd_scan if command == "scan" else cmd_ensure)

    p = sub.add_parser("list")
    p.add_argument("target", choices=("live", "candidate"))
    p.add_argument("--all", action="store_true")
    p.add_argument("--ignore-policy", action="store_true")
    p.add_argument("--query", default="")
    p.add_argument("--format", choices=("tsv", "json"), default="tsv")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("status")
    p.add_argument("target", choices=("live", "candidate"))
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("best")
    p.add_argument("target", choices=("live", "candidate"), default="live", nargs="?")
    p.add_argument("--exclude", action="append", default=[])
    p.add_argument("--ignore-policy", action="store_true")
    p.set_defaults(func=cmd_best)

    p = sub.add_parser("policy")
    p.add_argument("action", choices=("get", "status", "set"))
    p.add_argument("value", choices=("all", "europe"), nargs="?")
    p.set_defaults(func=cmd_policy)

    p = sub.add_parser("cooldown")
    p.add_argument("action", choices=("add", "clear", "status"))
    p.add_argument("name", nargs="?")
    p.add_argument("--seconds", type=int, default=COOLDOWN_SECONDS)
    p.set_defaults(func=cmd_cooldown)

    p = sub.add_parser("clear")
    p.add_argument("target", choices=("live", "candidate"))
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("promote")
    p.set_defaults(func=cmd_promote)

    args = parser.parse_args()
    if args.command == "policy" and args.action == "set" and not args.value:
        die("policy set requires all or europe")
    if args.command == "cooldown" and args.action == "add" and not args.name:
        die("cooldown add requires a node name")
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        raise SystemExit(0)
