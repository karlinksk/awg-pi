#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat >"$tmp/env" <<'EOF'
LAN_IF='eth0'
VPN_IF='awg0'
VPN_MARK='0x100'
VPN_TABLE='100'
EOF

cat >"$tmp/bin/nft" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$*" == "list chain inet awg_pbr forward_guard" ]]; then
  if [[ "${MOCK_GUARD_UNSAFE:-0}" == 1 ]]; then
    echo 'chain forward_guard { iifname "eth0" oifname "eth0" accept }'
  else
    echo 'chain forward_guard { iifname "eth0" ether saddr 02:11:22:33:44:55 oifname "awg0" accept }'
  fi
  exit 0
fi
exit 1
EOF

cat >"$tmp/bin/ip" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

state="${MOCK_IP_STATE:?}"
rule_file="$state.rule"
route_file="$state.route"

case "$*" in
  "link show dev awg0")
    exit 0
    ;;
  "-4 rule show")
    if [[ -e "$rule_file" ]]; then
      echo '100: from all fwmark 0x100 lookup 100'
    else
      echo '0: from all lookup local'
      echo '32766: from all lookup main'
    fi
    ;;
  "-4 rule add priority 100 fwmark 0x100 lookup 100")
    : >"$rule_file"
    ;;
  "-4 rule del priority 100 fwmark 0x100 lookup 100")
    if [[ -e "$rule_file" ]]; then
      rm -f "$rule_file"
      exit 0
    fi
    exit 2
    ;;
  "-4 route show table 100")
    [[ -e "$route_file" ]] && cat "$route_file"
    ;;
  "-4 route show table 100 default")
    [[ -e "$route_file" ]] && cat "$route_file"
    ;;
  "-4 route replace default dev awg0 table 100")
    echo 'default dev awg0' >"$route_file"
    ;;
  "-4 route del default table 100")
    rm -f "$route_file"
    ;;
  "-4 route add table 100 default dev old0")
    echo 'default dev old0' >"$route_file"
    ;;
  *)
    echo "unexpected ip call: $*" >&2
    exit 1
    ;;
esac
EOF

chmod +x "$tmp/bin/"*

run_route(){
  sudo env \
    AWG_ENV_FILE="$tmp/env" \
    IP_BIN="$tmp/bin/ip" \
    NFT_BIN="$tmp/bin/nft" \
    MOCK_IP_STATE="$tmp/ip-state" \
    MOCK_GUARD_UNSAFE="${MOCK_GUARD_UNSAFE:-0}" \
    bash "$repo_root/src/awg-transit-routing" "$@"
}

echo "=== transit routing initial status ==="
out="$(run_route status)"
grep -Fqx 'Transit guard: SAFE' <<<"$out"
grep -Fqx 'Transit policy rule: INACTIVE' <<<"$out"
grep -Fqx 'Transit VPN table: NOT_READY' <<<"$out"

echo "=== transit routing apply ==="
out="$(run_route apply)"
grep -Fqx 'TRANSIT_POLICY=ACTIVE' <<<"$out"
out="$(run_route status)"
grep -Fqx 'Transit policy rule: ACTIVE' <<<"$out"
grep -Fqx 'Transit VPN table: READY' <<<"$out"

echo "=== transit routing disable is fail-closed ==="
out="$(run_route disable)"
grep -Fqx 'TRANSIT_POLICY=DISABLED_FAIL_CLOSED' <<<"$out"
out="$(run_route status)"
grep -Fqx 'Transit policy rule: INACTIVE' <<<"$out"
grep -Fqx 'Transit guard: SAFE' <<<"$out"

echo "=== unsafe forward guard is rejected ==="
if MOCK_GUARD_UNSAFE=1 run_route apply >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: unsafe Transit guard was accepted' >&2
  exit 1
fi
grep -Fq 'Transit nftables forward guard is not active/safe' "$tmp/err"

echo "transit policy routing: OK"
