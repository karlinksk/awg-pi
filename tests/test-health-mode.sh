#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/state"

cat >"$tmp/env" <<'EOF'
VPN_IF='awg0'
VPN_MARK='0x100'
HEALTH_MARK='0x101'
VPN_TABLE='100'
HEALTH_TABLE='101'
HEALTH_INTERVAL='1'
HANDSHAKE_MAX_AGE='180'
EOF

cat >"$tmp/common" <<'EOF'
awg_mode_get(){ cat "${AWG_MODE_FILE}"; }
EOF

cat >"$tmp/bin/ip" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
case "$*" in
  "link show awg0") exit 0 ;;
  "-4 route replace default dev awg0 table 101") exit 0 ;;
  "-4 route replace default dev awg0 table 100") exit 0 ;;
  "-4 rule show")
    [[ -e "${MOCK_RULE_FILE}" ]] && echo '100: from all fwmark 0x100 lookup 100'
    ;;
  "-4 rule add priority 90 fwmark 0x101 lookup 101") exit 0 ;;
  "-4 rule add priority 100 fwmark 0x100 lookup 100") : >"${MOCK_RULE_FILE}" ;;
  "-4 rule del priority 100 fwmark 0x100 lookup 100")
    if [[ -e "${MOCK_RULE_FILE}" ]]; then rm -f "${MOCK_RULE_FILE}"; exit 0; fi
    exit 2
    ;;
  *) echo "unexpected ip: $*" >&2; exit 1 ;;
esac
EOF

cat >"$tmp/bin/awg" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == "show awg0 latest-handshakes" ]]; then
  printf 'peer\t%s\n' "$(date +%s)"
  exit 0
fi
exit 1
EOF

cat >"$tmp/bin/ping" <<'EOF'
#!/usr/bin/env bash
[[ "${MOCK_HEALTH:-up}" == up ]]
EOF

cat >"$tmp/bin/logger" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

cat >"$tmp/transit-routing" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "$1" >>"${MOCK_TRANSIT_LOG}"
case "$1" in
  apply) : >"${MOCK_RULE_FILE}" ;;
  disable) rm -f "${MOCK_RULE_FILE}" ;;
  *) exit 2 ;;
esac
EOF

chmod +x "$tmp/bin/"* "$tmp/transit-routing"
echo 1 >"$tmp/vpn-enabled"

run_health(){
  sudo env \
    AWG_ENV_FILE="$tmp/env" \
    AWG_COMMON_FILE="$tmp/common" \
    AWG_MODE_FILE="$tmp/mode" \
    AWG_VPN_ENABLED_FILE="$tmp/vpn-enabled" \
    AWG_STATE_DIR="$tmp/state" \
    AWG_TRANSIT_ROUTING="$tmp/transit-routing" \
    IP_BIN="$tmp/bin/ip" AWG_BIN="$tmp/bin/awg" PING_BIN="$tmp/bin/ping" LOGGER_BIN="$tmp/bin/logger" \
    MOCK_RULE_FILE="$tmp/rule" MOCK_TRANSIT_LOG="$tmp/transit.log" MOCK_HEALTH="${MOCK_HEALTH:-up}" \
    AWG_HEALTH_ONCE=1 \
    bash "$repo_root/src/awg-pbr-health"
}

echo "=== selective healthy ==="
echo selective >"$tmp/mode"
rm -f "$tmp/rule"
run_health
sudo test -e "$tmp/rule"
grep -Fqx up "$tmp/state/health.state"

echo "=== selective unhealthy is fail-open ==="
MOCK_HEALTH=down run_health
sudo test ! -e "$tmp/rule"
grep -Fqx down "$tmp/state/health.state"

echo "=== transit healthy ==="
echo transit >"$tmp/mode"
: >"$tmp/transit.log"
MOCK_HEALTH=up run_health
grep -Fqx apply "$tmp/transit.log"
grep -Fqx up "$tmp/state/health.state"

echo "=== transit unhealthy is fail-closed ==="
: >"$tmp/transit.log"
MOCK_HEALTH=down run_health
grep -Fqx disable "$tmp/transit.log"
grep -Fqx down "$tmp/state/health.state"

echo "mode-aware health monitor: OK"
