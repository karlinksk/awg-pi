#!/usr/bin/env python3
"""SHADOW-only cold-start timing and service checks for Hot Pool.

Uses a temporary TUN-disabled Mihomo instance and the existing preflight,
provider, gate and video decoder. Never changes a live selector or route.
Only bounded status families, timings and checks go to stdout.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import importlib.machinery
import importlib.util
import ipaddress
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error

SMART = Path('/usr/local/sbin/awg-mihomo-smart')
CONNECT_BUDGET_SECONDS = 22
CONNECT_ATTEMPTS = 4
CONNECT_PAUSE_SECONDS = 1
PROBE_TIMEOUT_SECONDS = 5
NAME = re.compile(r'^[A-Za-z0-9_.-]{1,100}$')
COUNTRY = re.compile(r'^[A-Z]{2}$')
REASON = re.compile(r'^[A-Z0-9_]{1,48}$')


def error_family(exc: Exception) -> str:
    """Never print raw exceptions: they can contain URLs or provider secrets."""
    obj = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(obj, (TimeoutError, socket.timeout)):
        return 'TIMEOUT'
    if isinstance(obj, socket.gaierror):
        return 'DNS'
    if isinstance(obj, ssl.SSLError):
        return 'TLS'
    if isinstance(obj, ConnectionRefusedError):
        return 'CONNECTION_REFUSED'
    if isinstance(obj, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
        return 'CONNECTION_RESET'
    if isinstance(obj, OSError):
        if obj.errno == errno.ENETUNREACH or obj.errno == errno.EHOSTUNREACH:
            return 'UNREACHABLE'
        if obj.errno in (errno.ETIMEDOUT,):
            return 'TIMEOUT'
        if obj.errno in (errno.ECONNREFUSED,):
            return 'CONNECTION_REFUSED'
        if obj.errno in (errno.ECONNRESET, errno.EPIPE):
            return 'CONNECTION_RESET'
    return 'CONNECTION_UNKNOWN'


def cold_connect(fetch, port: int, *, clock=time.monotonic, pause=time.sleep,
                 attempts=CONNECT_ATTEMPTS, budget=CONNECT_BUDGET_SECONDS,
                 interval=CONNECT_PAUSE_SECONDS) -> tuple[bool, int, int, str]:
    """Confirm first HTTPS through the same isolated proxy, not controller visibility.

    A valid TLS-verified HTTP response is transport readiness, not service
    eligibility. The subsequent normal balanced gate remains mandatory.
    """
    began = clock()
    last_error = 'NO_HTTPS'
    used = 0
    for i in range(attempts):
        left = budget - (clock() - began)
        if left <= 0:
            break
        used += 1
        try:
            # Existing fetch pins HTTPS destinations and forces loopback proxy.
            code, _, _ = fetch(port, 'https://api.openai.com/v1/models',
                               timeout=min(float(PROBE_TIMEOUT_SECONDS), left),
                               max_bytes=8192)
            if type(code) is int and 200 <= code < 600:
                return True, round((clock() - began) * 1000), used, 'HTTPS_OK'
            last_error = 'HTTP_INVALID'
        except Exception as exc:
            last_error = error_family(exc)
        left = budget - (clock() - began)
        if i + 1 < attempts and left > 0:
            pause(min(interval, left))
    return False, round((clock() - began) * 1000), used, last_error



def safe_egress(ip: object, country: object) -> tuple[str, str, str]:
    # Trace text is untrusted. Never report private or malformed addresses.
    try:
        address = ipaddress.ip_address(ip)
        if address.version != 4 or not address.is_global:
            return 'UNKNOWN', 'UNKNOWN', 'INVALID_EGRESS_IPV4'
        if not isinstance(country, str) or not COUNTRY.fullmatch(country):
            return 'UNKNOWN', 'UNKNOWN', 'INVALID_COUNTRY'
        return str(address), country, 'VERIFIED'
    except (ValueError, TypeError):
        return 'UNKNOWN', 'UNKNOWN', 'INVALID_EGRESS_IPV4'


def isolated_egress(helper, controller: int, mixed: int, item: dict) -> tuple[str, str, str, str]:
    # Reuse existing egress_geo (Cloudflare Trace over the selected proxy).
    # Clear environment proxy bypasses only in this short-lived probe process.
    bypass = {key: os.environ.pop(key, None) for key in ('NO_PROXY', 'no_proxy')}
    try:
        ip, country, error = helper.egress_geo(controller, mixed, item)
    except Exception as exc:
        return 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', error_family(exc)
    finally:
        for key, value in bypass.items():
            if value is not None:
                os.environ[key] = value
    result_ip, result_country, state = safe_egress(ip, country)
    if state == 'VERIFIED':
        return result_ip, result_country, 'VERIFIED', 'NONE'
    if isinstance(error, str) and re.fullmatch(r'curl-[0-9]{1,3}', error):
        return 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'CURL_ERROR'
    return 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', state


def print_geo(ip: str, country: str, state: str, reason: str) -> None:
    # All arguments come from strict allow-lists, never raw trace or stderr.
    assert REASON.fullmatch(state) and REASON.fullmatch(reason)
    assert (ip == 'UNKNOWN' or (safe_egress(ip, country)[2] == 'VERIFIED'))
    print('SERVICE_GEO_EGRESS_IPV4=' + ip)
    print('SERVICE_GEO_COUNTRY=' + country)
    print('SERVICE_GEO_STATE=' + state)
    print('SERVICE_GEO_REASON=' + reason, flush=True)


def diagnose_first_fail(result, smart, proxy_port):
    """Shadow-only extra decode after first-stage YouTube HTTP denial.

    Never mutates result, so eligibility remains determined by the ORIGINAL
    balanced gate. Only genuine first-stage HTTP 403/451 failures qualify.
    """
    checks = result.get('checks', {})
    video = checks.get('youtube_video', {})
    if (checks.get('openai_api', {}).get('state') != 'PASS'
            or video.get('state') != 'FAIL'
            or video.get('reason') not in
            ('youtube_media_http_403', 'youtube_media_http_451')):
        return None
    try:
        module = smart.load_video_decode_code()
        if module is None:
            return ('UNKNOWN', 'VIDEO_MODULE_UNAVAILABLE')
        state, reason = module.decode_24_frames(proxy_port)
        if state not in ('PASS', 'UNKNOWN', 'FAIL'):
            return ('UNKNOWN', 'INVALID_DIAG_STATE')
        if not re.fullmatch(r'[a-zA-Z0-9_]{1,64}', reason):
            return ('UNKNOWN', 'INVALID_DIAG_REASON')
        return state, reason
    except Exception:
        # No raw exception or provider data in stdout.
        return ('UNKNOWN', 'DIAG_EXCEPTION')


def trusted_shadow_provider(path: Path) -> bool:
    """Allow only root-controlled RAM union provider, never arbitrary paths."""
    try:
        physical = path.resolve(strict=True)
        root = Path('/run/awg-pbr/hot-pool').resolve(strict=True)
        st = physical.stat()
        return (physical != root and physical.is_relative_to(root)
                and st.st_uid == 0 and st.st_mode & 0o077 == 0
                and physical.is_file())
    except (OSError, ValueError):
        return False


def load_smart():
    loader = importlib.machinery.SourceFileLoader('awg_shadow_cold_smart', str(SMART))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    loader.exec_module(obj)
    return obj


def inspect_node(name: str, provider: Path | None = None) -> int:
    if os.geteuid() != 0:
        print('SERVICE_SHADOW_ERROR=REQUIRES_ROOT')
        return 2
    if not Path('/dev/shm').is_dir():
        print('SERVICE_SHADOW_ERROR=NO_RAM')
        return 2
    smart = load_smart()
    if provider is not None:
        if not trusted_shadow_provider(provider):
            print('SERVICE_SHADOW_ERROR=UNTRUSTED_PROVIDER')
            return 2
        smart.PROVIDER = provider
    helper, gate = smart.load_pool_code(), smart.load_service_code()
    raw = helper.read_provider(smart.PROVIDER)
    matched = [n for n in raw if isinstance(n, dict) and n.get('name') == name]
    if len(matched) != 1:
        print('SERVICE_SHADOW_ERROR=NODE_NOT_UNIQUE')
        return 2
    smart.verify_candidate_direct(matched[0])
    smart.STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    print('SERVICE_DIAG_MODE=ISOLATED_SHADOW_ONLY', flush=True)
    with (smart.STATE_DIR / 'lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mixed = helper.choose_free_port()
        controller = helper.choose_free_port()
        while mixed == controller:
            controller = helper.choose_free_port()
        with tempfile.TemporaryDirectory(prefix='awg-hot-cold-', dir='/dev/shm') as tmp:
            config, entries = helper.make_probe_config(matched, mixed, controller)
            if len(entries) != 1 or not entries[0].get('probe_name'):
                print('SERVICE_SHADOW_ERROR=INVALID_PROFILE')
                return 2
            import yaml
            cfg = Path(tmp) / 'config.yaml'
            cfg.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
            os.chmod(cfg, 0o600)
            start = time.monotonic()
            instance = subprocess.Popen([smart.MIHOMO, '-d', tmp, '-f', str(cfg)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        stdin=subprocess.DEVNULL)
            try:
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    if instance.poll() is not None:
                        print('SERVICE_SHADOW_ERROR=MIHOMO_EARLY_EXIT')
                        return 2
                    try:
                        proxies = helper.controller_request(controller, '/proxies',
                                                            timeout=0.7).get('proxies', {})
                        if entries[0]['probe_name'] in proxies:
                            break
                    except Exception:
                        pass
                    time.sleep(0.2)
                else:
                    print('SERVICE_SHADOW_ERROR=CONTROLLER_START_TIMEOUT')
                    return 2
                controller_ms = round((time.monotonic() - start) * 1000)
                helper.select_probe(controller, entries[0]['probe_name'])
                ok, wait_ms, attempts, family = cold_connect(gate.fetch, mixed)
                print('SERVICE_CONNECT_STATE=' + ('PASS' if ok else 'UNKNOWN'))
                print('SERVICE_CONTROLLER_READY_MS=' + str(controller_ms))
                print('SERVICE_CONNECT_WAIT_MS=' + str(wait_ms))
                print('SERVICE_COLD_READY_MS=' +
                      str(round((time.monotonic() - start) * 1000)))
                print('SERVICE_CONNECT_ATTEMPTS=' + str(attempts))
                print('SERVICE_CONNECT_FAMILY=' + family, flush=True)
                if not ok:
                    print('SERVICE_ELIGIBILITY=UNKNOWN')
                    for key in ('OPENAI_API', 'CHATGPT_WEB', 'YOUTUBE_VIDEO'):
                        print('SERVICE_CHECK_' + key + '=UNKNOWN')
                    print('SERVICE_REASON_CHATGPT_WEB=connect_not_ready')
                    print_geo('UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'CONNECT_NOT_READY')
                    return 1
                result = smart.assess_services_with_stage18(
                    gate, mixed, force_media=True)
                diagnostic = diagnose_first_fail(result, smart, mixed)
                if diagnostic is not None:
                    print('SERVICE_DIAG_AFTER_FIRST_FAIL_24=' + diagnostic[0])
                    print('SERVICE_DIAG_AFTER_FIRST_FAIL_REASON=' + diagnostic[1],
                          flush=True)
                # Geo is telemetry only. It MUST NOT influence the balanced gate.
                geo_ip, geo_country, geo_state, geo_reason = isolated_egress(
                    helper, controller, mixed, entries[0])
                print_geo(geo_ip, geo_country, geo_state, geo_reason)
            finally:
                if instance.poll() is None:
                    instance.terminate()
                    try:
                        instance.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        instance.kill()
                        instance.wait(timeout=4)
    print('SERVICE_ELIGIBILITY=' + result['status'])
    for key in ('openai_api', 'chatgpt_web', 'youtube_video'):
        print('SERVICE_CHECK_' + key.upper() + '=' + result['checks'][key]['state'])
    print('SERVICE_REASON_CHATGPT_WEB=' + result['checks']['chatgpt_web']['reason'])
    print('SERVICE_REASON_YOUTUBE_VIDEO=' + result['checks']['youtube_video']['reason'])
    return 0 if result['status'] == 'PASS' else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--provider', type=Path,
                        help='Root-owned 0600 profile under /run/awg-pbr/hot-pool')
    args = parser.parse_args()
    if not NAME.fullmatch(args.node):
        print('SERVICE_SHADOW_ERROR=INVALID_NAME')
        return 2
    try:
        return inspect_node(args.node, args.provider)
    except Exception as exc:
        # Hardened unit may be missing NETLINK, provider permissions, etc.
        # Never print the raw exception.
        print('SERVICE_SHADOW_ERROR=' + error_family(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())