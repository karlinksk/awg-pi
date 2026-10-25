#!/usr/bin/env python3
"""Fixture test for safe continuation after a failed fresh install."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
source = (root / "install.sh").read_text(encoding="utf-8")
start = source.index("UPGRADE_EXISTING=0\n")
end = source.index("# -----------------------------------------------------------------------------\n# 1. Preflight", start)
block = source[start:end]

def fixture(*, env=True, mode="selective", transport="unconfigured",
            version=False, conf=False, active=False, allow=True):
    with tempfile.TemporaryDirectory(prefix="awg-resume-") as d:
        folder = Path(d)
        if env:
            (folder / "env").write_text("LAN_IF=eth0\n")
        if mode is not None:
            (folder / "mode").write_text(mode+"\n")
        if transport is not None:
            (folder / "transport").write_text(transport+"\n")
        if version:
            (folder / "version").write_text("1.2.0\n")
        if conf:
            (folder / "awg0.conf").write_text("dummy\n")
        vals = dict(PBR_DIR=folder/"private",PUBLIC_VERSION_FILE=folder/"version",
                    VERSION_FILE=folder/"version-private",
                    ENV_FILE=folder/"env",
                    MODE_FILE=folder/"mode",
                    TRANSPORT_FILE=folder/"transport",
                    CONF_FILE=folder/"awg0.conf")
        prefix = "\n".join(f"{k}={shlex.quote(str(v))}" for k,v in vals.items())
        prefix += """\nVPN_IF=awg0
AWG_PI_VERSION=1.3.0
AWG_PI_UPGRADE_AUTO=1
AUTO_TRANSIT=''
TTY=/dev/null
warn(){ :; }
ok(){ :; }
die(){ echo "INSTALL_ABORT"; exit 77; }
confirm(){ [[ "${ALLOW_RESUME:-0}" == "1" ]]; }
systemctl(){
  case "$1" in
    is-enabled) echo disabled; return 1 ;;
    is-active)
      echo inactive
      [[ "${SERVICE_ACTIVE:-0}" != "1" ]] && return 3
      return 0 ;;
  esac
  return 3
}
"""
        shell = "set -Eeuo pipefail\n" + prefix + block + '\nprintf "PARTIAL=%s UPGRADE=%s\\n" "$PARTIAL_FRESH_RESUME" "$UPGRADE_EXISTING"\n'
        proc = subprocess.run(["bash","-c",shell],capture_output=True,text=True,
            env={**os.environ,"ALLOW_RESUME":"1" if allow else "0",
                 "SERVICE_ACTIVE":"1" if active else "0"},timeout=5)
        return proc

def assert_case(expected, **opts):
    proc=fixture(**opts)
    assert proc.returncode==0, f"rc={proc.returncode}: {proc.stderr}"
    assert expected in proc.stdout, proc.stdout

assert_case("PARTIAL=1 UPGRADE=0")
assert_case("PARTIAL=0 UPGRADE=0",env=False,mode=None,transport=None)
assert_case("PARTIAL=0 UPGRADE=1",version=True)
assert_case("PARTIAL=0 UPGRADE=1",conf=True)
assert_case("PARTIAL=0 UPGRADE=1",mode="transit")
assert_case("PARTIAL=0 UPGRADE=1",transport="awg")
assert_case("PARTIAL=0 UPGRADE=1",active=True)
refuse=fixture(allow=False)
assert refuse.returncode==77 and "INSTALL_ABORT" in refuse.stdout
assert 'PARTIAL_FRESH_RESUME=YES; установка завершится без VPN-профилей' in block
print("INTERRUPTED_INSTALL_RESUME=PASS (9 cases)")
