#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat >"$tmp/common" <<'EOF'
AWG_MODE_FILE="${AWG_MODE_FILE:?}"
awg_mode_get(){
  [[ -e "$AWG_MODE_FILE" ]] && cat "$AWG_MODE_FILE" || echo selective
}
awg_mode_set(){
  printf '%s\n' "$1" >"$AWG_MODE_FILE"
  chmod 600 "$AWG_MODE_FILE"
}
EOF

cat >"$tmp/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "$*" >>"${MOCK_SYSTEMCTL_LOG}"
exit 0
EOF

cat >"$tmp/transit-apply" <<'EOF'
#!/usr/bin/env bash
echo "apply:$*" >>"${MOCK_SWITCH_LOG}"
[[ "${MOCK_TRANSIT_APPLY_FAIL:-0}" != 1 ]]
EOF

cat >"$tmp/transit-routing" <<'EOF'
#!/usr/bin/env bash
echo "routing:$*" >>"${MOCK_SWITCH_LOG}"
case "$1" in
  apply) [[ "${MOCK_ROUTING_FAIL:-0}" != 1 ]] ;;
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

cat >"$tmp/awg-route" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "route:$*" >>"${MOCK_SWITCH_LOG}"
if [[ "${MOCK_SELECTIVE_RELOAD_FAIL:-0}" == 1 && ! -e "${MOCK_RELOAD_FAILED_ONCE:?}" ]]; then
  : >"${MOCK_RELOAD_FAILED_ONCE}"
  exit 1
fi
exit 0
EOF

chmod +x "$tmp/bin/systemctl" "$tmp/transit-apply" "$tmp/transit-routing" "$tmp/awg-route"

run_switch(){
  sudo env \
    AWG_COMMON_FILE="$tmp/common" AWG_MODE_FILE="$tmp/mode" \
    AWG_ROUTE_BIN="$tmp/awg-route" AWG_TRANSIT_APPLY="$tmp/transit-apply" \
    AWG_TRANSIT_ROUTING="$tmp/transit-routing" SYSTEMCTL_BIN="$tmp/bin/systemctl" \
    AWG_HEALTH_SERVICE="awg-pbr-health.service" \
    MOCK_SYSTEMCTL_LOG="$tmp/systemctl.log" MOCK_SWITCH_LOG="$tmp/switch.log" \
    MOCK_RELOAD_FAILED_ONCE="$tmp/reload-failed-once" \
    MOCK_TRANSIT_APPLY_FAIL="${MOCK_TRANSIT_APPLY_FAIL:-0}" \
    MOCK_ROUTING_FAIL="${MOCK_ROUTING_FAIL:-0}" \
    MOCK_SELECTIVE_RELOAD_FAIL="${MOCK_SELECTIVE_RELOAD_FAIL:-0}" \
    bash "$repo_root/src/awg-mode-switch" "$1"
}

echo selective >"$tmp/mode"

echo "=== selective -> transit ==="
: >"$tmp/switch.log"; : >"$tmp/systemctl.log"
out="$(run_switch transit)"
grep -Fqx 'Mode ID: transit' <<<"$out"
grep -Fqx transit "$tmp/mode"
grep -Fq 'apply:apply' "$tmp/switch.log"
grep -Fq 'routing:apply' "$tmp/switch.log"

echo "=== transit -> selective ==="
: >"$tmp/switch.log"
out="$(run_switch selective)"
grep -Fqx 'Mode ID: selective' <<<"$out"
grep -Fqx selective "$tmp/mode"
grep -Fq 'route:reload' "$tmp/switch.log"

echo "=== failed transit activation restores selective ==="
echo selective >"$tmp/mode"
if MOCK_TRANSIT_APPLY_FAIL=1 run_switch transit >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: failed Transit activation returned success' >&2
  exit 1
fi
grep -Fqx selective "$tmp/mode"
grep -Fq 'ROLLBACK=OK' "$tmp/err"

echo "=== failed selective activation restores transit ==="
echo transit >"$tmp/mode"
rm -f "$tmp/reload-failed-once"
if MOCK_SELECTIVE_RELOAD_FAIL=1 run_switch selective >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: failed Selective activation returned success' >&2
  exit 1
fi
grep -Fqx transit "$tmp/mode"
grep -Fq 'route:reload' "$tmp/switch.log"
grep -Fq 'ROLLBACK=OK' "$tmp/err"

echo "transactional mode switch: OK"
