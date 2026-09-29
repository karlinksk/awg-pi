#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

: >"$tmp/env"

fail(){
  echo "FAIL: $*" >&2
  exit 1
}

eq(){
  [[ "$1" == "$2" ]] || fail "expected '$2', got '$1'"
}

route(){
  sudo env \
    AWG_ENV_FILE="$tmp/env" \
    AWG_COMMON_FILE="$repo_root/src/awg-common" \
    AWG_MODE_FILE="$tmp/mode" \
    AWG_LOCK_FILE="$tmp/maintenance.lock" \
    SOURCE_ROOT="$tmp/sources" \
    LOG_DIR="$tmp/log" \
    bash "$repo_root/src/awg-route" "$@"
}

echo "=== route mode default status ==="
out="$(route mode status)"
grep -Fqx 'Operating mode: Selective Gateway' <<<"$out" ||
  fail "default mode label missing"
grep -Fqx 'Mode ID: selective' <<<"$out" ||
  fail "default mode id missing"
[[ ! -e "$tmp/mode" ]] ||
  fail "status unexpectedly created a mode file"

echo "=== route mode transit ==="
out="$(route mode transit)"
grep -Fqx 'Operating mode state saved: MikroTik Transit / Backup VPN' <<<"$out" ||
  fail "transit save confirmation missing"
grep -Fqx 'Mode ID: transit' <<<"$out" ||
  fail "transit mode id missing"
grep -Fqx 'NOTE: network datapath is unchanged in the current framework stage.' <<<"$out" ||
  fail "framework-stage warning missing"
eq "$(cat "$tmp/mode")" "transit"

out="$(route mode status)"
grep -Fqx 'Operating mode: MikroTik Transit / Backup VPN' <<<"$out" ||
  fail "transit status label missing"
grep -Fqx 'Mode ID: transit' <<<"$out" ||
  fail "transit status id missing"

echo "=== route mode selective ==="
out="$(route mode selective)"
grep -Fqx 'Operating mode state saved: Selective Gateway' <<<"$out" ||
  fail "selective save confirmation missing"
grep -Fqx 'Mode ID: selective' <<<"$out" ||
  fail "selective mode id missing"
eq "$(cat "$tmp/mode")" "selective"

echo "=== route mode invalid command ==="
if route mode garbage >"$tmp/out" 2>"$tmp/err"; then
  fail "invalid mode subcommand was accepted"
fi

echo "route mode CLI: OK"
