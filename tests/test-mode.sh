#!/usr/bin/env bash
set -Eeuo pipefail

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export AWG_MODE_FILE="$tmp/mode"

# shellcheck disable=SC1091
source src/awg-common

fail(){
  echo "FAIL: $*" >&2
  exit 1
}

eq(){
  [[ "$1" == "$2" ]] || fail "expected '$2', got '$1'"
}

echo "=== mode validation ==="

awg_mode_valid selective || fail "selective should be valid"
awg_mode_valid transit || fail "transit should be valid"
! awg_mode_valid garbage || fail "garbage mode should be rejected"
! awg_mode_valid "" || fail "empty mode should be rejected"

echo "=== default mode ==="

[[ ! -e "$AWG_MODE_FILE" ]] || fail "mode file unexpectedly exists"
eq "$(awg_mode_get)" "selective"

echo "=== mode labels ==="

eq "$(awg_mode_label selective)" "Selective Gateway"
eq "$(awg_mode_label transit)" "MikroTik Transit / Backup VPN"
! awg_mode_label garbage >/dev/null 2>&1 ||
  fail "invalid mode label should fail"

echo "=== persistent mode ==="

awg_mode_set selective
eq "$(awg_mode_get)" "selective"
eq "$(cat "$AWG_MODE_FILE")" "selective"

mode_perms="$(stat -c '%a' "$AWG_MODE_FILE")"
eq "$mode_perms" "600"

awg_mode_set transit
eq "$(awg_mode_get)" "transit"
eq "$(cat "$AWG_MODE_FILE")" "transit"

awg_mode_set selective
eq "$(awg_mode_get)" "selective"

echo "=== corrupt mode protection ==="

printf '%s\n' garbage >"$AWG_MODE_FILE"

if awg_mode_get >"$tmp/out" 2>"$tmp/err"; then
  fail "corrupt mode file was accepted"
fi

grep -Fq "Invalid operating mode" "$tmp/err" ||
  fail "corrupt mode did not produce the expected error"

echo "=== invalid write protection ==="

printf '%s\n' selective >"$AWG_MODE_FILE"

if awg_mode_set garbage >"$tmp/out" 2>"$tmp/err"; then
  fail "invalid mode write was accepted"
fi

eq "$(cat "$AWG_MODE_FILE")" "selective"

echo "mode helpers: OK"
