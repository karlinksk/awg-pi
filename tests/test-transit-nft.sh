#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cat >"$tmp/env" <<'EOF'
LAN_IF='eth0'
LAN_CIDR='192.168.88.0/24'
VPN_IF='awg0'
VPN_MARK='0x100'
EOF

AWG_ENV_FILE="$tmp/env" ROUTER_MAC='02:11:22:33:44:55' \
  bash "$repo_root/src/awg-transit-nft" >"$tmp/transit.nft"

grep -Fq 'set transit4 {' "$tmp/transit.nft"
grep -Fq 'elements = { 192.168.88.0/24 }' "$tmp/transit.nft"
grep -Fq 'ether saddr 02:11:22:33:44:55' "$tmp/transit.nft"
grep -Fq 'ip daddr != 192.168.88.0/24 meta mark set 0x100' "$tmp/transit.nft"
grep -Fq 'iifname "awg0" oifname "eth0" ct state established,related accept' "$tmp/transit.nft"
grep -Fq 'iifname "eth0" ether saddr 02:11:22:33:44:55 ip saddr @transit4 oifname "awg0" accept' "$tmp/transit.nft"
grep -Fq 'ip saddr @transit4 oifname "awg0" masquerade' "$tmp/transit.nft"

if grep -Fq 'oifname "eth0" accept' "$tmp/transit.nft"; then
  echo 'FAIL: Transit rules must not allow LAN-to-LAN forwarding fallback' >&2
  exit 1
fi

if grep -Fq 'redirect to :53' "$tmp/transit.nft"; then
  echo 'FAIL: Transit rules must not redirect client DNS' >&2
  exit 1
fi

if AWG_ENV_FILE="$tmp/env" ROUTER_MAC='not-a-mac' \
  bash "$repo_root/src/awg-transit-nft" >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: invalid router MAC was accepted' >&2
  exit 1
fi

sudo nft -c -f "$tmp/transit.nft"

echo "transit nft candidate: OK"
