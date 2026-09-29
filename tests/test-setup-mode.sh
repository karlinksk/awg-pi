#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
: >"$tmp/clients"

cat >"$tmp/env" <<'EOF'
LAN_IF='eth0'
LAN_CIDR='192.168.88.0/24'
ROUTER_IP='192.168.88.1'
VPN_IF='awg0'
VPN_MARK='0x100'
VPN_TABLE='100'
DNS_REDIRECT='1'
EOF

cat >"$tmp/common" <<'EOF'
awg_mode_get(){ cat "${AWG_MODE_FILE}"; }
EOF

cat >"$tmp/bin/ping" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

cat >"$tmp/bin/ip" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "$*" >>"${MOCK_IP_LOG}"
case "$*" in
  "neigh show to 192.168.88.1 dev eth0")
    echo '192.168.88.1 lladdr 02:11:22:33:44:55 REACHABLE'
    ;;
  "-4 rule del priority 100 fwmark 0x100 lookup 100")
    exit 2
    ;;
  "-4 route flush table 100")
    exit 0
    ;;
  *) exit 0 ;;
esac
EOF

cat >"$tmp/bin/nft" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "$*" >>"${MOCK_NFT_LOG}"
case "$*" in
  "list table inet awg_pbr") exit 1 ;;
  "-c -f "*)
    cp "${3}" "${MOCK_LAST_CHECK}"
    ;;
  "-f "*)
    cp "${2}" "${MOCK_LAST_APPLY}"
    ;;
  "add element inet awg_pbr clients4 "*)
    ;;
  *) exit 0 ;;
esac
EOF

cat >"$tmp/transit-nft" <<'EOF'
#!/usr/bin/env bash
cat <<NFT
table inet awg_pbr {
  chain forward_guard {
    type filter hook forward priority filter; policy drop;
    iifname "eth0" ether saddr ${ROUTER_MAC} oifname "awg0" accept
  }
  chain prerouting_mark {
    type filter hook prerouting priority mangle; policy accept;
    iifname "eth0" ether saddr ${ROUTER_MAC} meta mark set 0x100
  }
  chain dns_redirect {
    type nat hook prerouting priority dstnat; policy accept;
  }
  chain postrouting_nat {
    type nat hook postrouting priority srcnat; policy accept;
    oifname "awg0" masquerade
  }
}
NFT
EOF

chmod +x "$tmp/bin/"* "$tmp/transit-nft"

run_setup(){
  sudo env \
    AWG_ENV_FILE="$tmp/env" AWG_COMMON_FILE="$tmp/common" AWG_MODE_FILE="$tmp/mode" \
    AWG_CLIENTS_FILE="$tmp/clients" AWG_NFT_FILE="$tmp/active.nft" AWG_TRANSIT_NFT="$tmp/transit-nft" \
    NFT_BIN="$tmp/bin/nft" IP_BIN="$tmp/bin/ip" PING_BIN="$tmp/bin/ping" \
    MOCK_IP_LOG="$tmp/ip.log" MOCK_NFT_LOG="$tmp/nft.log" \
    MOCK_LAST_CHECK="$tmp/last-check.nft" MOCK_LAST_APPLY="$tmp/last-apply.nft" \
    bash "$repo_root/src/awg-pbr-setup"
}

echo "=== selective boot setup ==="
echo selective >"$tmp/mode"
out="$(run_setup)"
grep -Fqx 'AWG_SETUP_MODE=selective' <<<"$out"
sudo grep -Fq 'redirect to :53' "$tmp/active.nft"
sudo grep -Fq 'oifname "eth0" accept' "$tmp/active.nft"
if sudo grep -Fq 'ether saddr' "$tmp/active.nft"; then
  echo 'FAIL: selective setup contains Transit MAC guard' >&2
  exit 1
fi

echo "=== transit boot setup ==="
echo transit >"$tmp/mode"
out="$(run_setup)"
grep -Fqx 'AWG_SETUP_MODE=transit' <<<"$out"
grep -Fqx 'ROUTER_MAC=02:11:22:33:44:55' <<<"$out"
sudo grep -Fq 'ether saddr 02:11:22:33:44:55' "$tmp/active.nft"
if sudo grep -Fq 'redirect to :53' "$tmp/active.nft"; then
  echo 'FAIL: transit setup redirects DNS' >&2
  exit 1
fi
grep -Fq -- '-4 route flush table 100' "$tmp/ip.log"

echo "mode-aware boot setup: OK"
