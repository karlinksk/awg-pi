#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT

: >"$tmp/env"

cat >"$tmp/mode-switch" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$1" >"${AWG_MODE_FILE:?}"
chmod 600 "${AWG_MODE_FILE}"
case "$1" in
  transit)
    echo 'Operating mode activated: MikroTik Transit / Backup VPN'
    echo 'Mode ID: transit'
    ;;
  selective)
    echo 'Operating mode activated: Selective Gateway'
    echo 'Mode ID: selective'
    ;;
  *) exit 2 ;;
esac
EOF

cat >"$tmp/transit-routing" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  status)
    cat <<'OUT'
Transit guard: SAFE
Transit policy rule: ACTIVE
Transit VPN table: READY
OUT
    ;;
  *) exit 2 ;;
esac
EOF

chmod +x "$tmp/mode-switch" "$tmp/transit-routing"

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
    AWG_MODE_SWITCH="$tmp/mode-switch" \
    AWG_TRANSIT_ROUTING="$tmp/transit-routing" \
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
grep -Fqx 'Operating mode activated: MikroTik Transit / Backup VPN' <<<"$out" ||
  fail "transit activation confirmation missing"
grep -Fqx 'Mode ID: transit' <<<"$out" ||
  fail "transit mode id missing"
eq "$(sudo cat "$tmp/mode")" "transit"

out="$(route mode status)"
grep -Fqx 'Operating mode: MikroTik Transit / Backup VPN' <<<"$out" ||
  fail "transit status label missing"
grep -Fqx 'Mode ID: transit' <<<"$out" ||
  fail "transit status id missing"

echo "=== transit rejects Selective vpn on/off controls ==="
for vpn_action in on off; do
  if route vpn "$vpn_action" >"$tmp/out" 2>"$tmp/err"; then
    fail "vpn $vpn_action was accepted in Transit mode"
  fi
  grep -Fq 'относится только к Selective Gateway' "$tmp/err" ||
    fail "vpn $vpn_action did not explain Transit behavior"
done

echo "=== route mode selective ==="
out="$(route mode selective)"
grep -Fqx 'Operating mode activated: Selective Gateway' <<<"$out" ||
  fail "selective activation confirmation missing"
grep -Fqx 'Mode ID: selective' <<<"$out" ||
  fail "selective mode id missing"
eq "$(sudo cat "$tmp/mode")" "selective"

echo "=== route mode invalid command ==="
if route mode garbage >"$tmp/out" 2>"$tmp/err"; then
  fail "invalid mode subcommand was accepted"
fi

echo "route mode CLI: OK"
