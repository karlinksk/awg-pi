#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
: >"$tmp/clients"
echo awg >"$tmp/transport"

cat >"$tmp/env" <<'EOF'
LAN_IF='eth0'
LAN_CIDR='192.168.88.0/24'
ROUTER_IP='192.168.88.1'
VPN_IF='awg0'
VPN_MARK='0x100'
VPN_TABLE='100'
DNS_REDIRECT='1'
EOF

cat >"$tmp/bin/ping" <<'EOF'
#!/usr/bin/env bash
[[ "${MOCK_ROUTER_UP:-1}" == 1 ]]
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
    if [[ -n "${MOCK_CRITICAL_DIR:-}" ]]; then
      if ! mkdir "$MOCK_CRITICAL_DIR" 2>/dev/null; then
        echo overlap >>"$MOCK_OVERLAP_LOG"
        exit 91
      fi
      trap 'rmdir "$MOCK_CRITICAL_DIR" 2>/dev/null || true' EXIT
      sleep 0.2
    fi
    cp "${2}" "${MOCK_LAST_APPLY}"
    if [[ -n "${MOCK_CRITICAL_DIR:-}" ]]; then
      rmdir "$MOCK_CRITICAL_DIR"
      trap - EXIT
    fi
    ;;
  "add element inet awg_pbr clients4 "*)
    ;;
  *) exit 0 ;;
esac
EOF

cat >"$tmp/transit-nft" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
case "$(cat "${AWG_TRANSPORT_FILE}" 2>/dev/null || echo awg)" in
  mihomo) transport_if=mihomo0 ;;
  *) transport_if=awg0 ;;
esac
if [[ "${AWG_TRANSIT_LOCKDOWN:-0}" == 1 ]]; then
  cat <<'NFT'
table inet awg_pbr {
  chain forward_guard {
    type filter hook forward priority filter; policy drop;
  }
  chain prerouting_mark {
    type filter hook prerouting priority mangle; policy accept;
  }
  chain dns_redirect {
    type nat hook prerouting priority dstnat; policy accept;
  }
  chain postrouting_nat {
    type nat hook postrouting priority srcnat; policy accept;
  }
}
NFT
else
  cat <<NFT
table inet awg_pbr {
  chain forward_guard {
    type filter hook forward priority filter; policy drop;
    iifname "eth0" ether saddr ${ROUTER_MAC} oifname "${transport_if}" accept
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
    oifname "${transport_if}" masquerade
  }
}
NFT
fi
EOF

chmod +x "$tmp/bin/"* "$tmp/transit-nft"

run_setup(){
  sudo env \
    AWG_ENV_FILE="$tmp/env" AWG_COMMON_FILE="$repo_root/src/awg-common" AWG_MODE_FILE="$tmp/mode" AWG_TRANSPORT_FILE="$tmp/transport" \
    AWG_CLIENTS_FILE="$tmp/clients" AWG_NFT_FILE="$tmp/active.nft" AWG_TRANSIT_NFT="$tmp/transit-nft" \
    AWG_SETUP_LOCK_FILE="$tmp/setup.lock" \
    NFT_BIN="$tmp/bin/nft" IP_BIN="$tmp/bin/ip" PING_BIN="$tmp/bin/ping" \
    MOCK_IP_LOG="$tmp/ip.log" MOCK_NFT_LOG="$tmp/nft.log" MOCK_ROUTER_UP="${MOCK_ROUTER_UP:-1}" \
    MOCK_LAST_CHECK="$tmp/last-check.nft" MOCK_LAST_APPLY="$tmp/last-apply.nft" \
    MOCK_CRITICAL_DIR="${MOCK_CRITICAL_DIR:-}" MOCK_OVERLAP_LOG="$tmp/overlap.log" \
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

echo "=== selective setup with Mihomo transport ==="
echo mihomo >"$tmp/transport"
echo selective >"$tmp/mode"
out="$(run_setup)"
grep -Fqx 'AWG_SETUP_MODE=selective' <<<"$out"
sudo grep -Fq 'oifname "mihomo0" accept' "$tmp/active.nft"
sudo grep -Fq 'oifname "mihomo0" masquerade' "$tmp/active.nft"
if sudo grep -Fq 'oifname "awg0" accept' "$tmp/active.nft"; then
  echo 'FAIL: Selective Mihomo setup still allows awg0 egress' >&2
  exit 1
fi

echo "=== transit setup with Mihomo transport ==="
echo transit >"$tmp/mode"
out="$(run_setup)"
grep -Fqx 'AWG_SETUP_MODE=transit' <<<"$out"
sudo grep -Fq 'oifname "mihomo0" accept' "$tmp/active.nft"
sudo grep -Fq 'oifname "mihomo0" masquerade' "$tmp/active.nft"
echo awg >"$tmp/transport"

echo "=== transit router failure leaves lockdown ==="
echo transit >"$tmp/mode"
if MOCK_ROUTER_UP=0 run_setup >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: Transit setup accepted unreachable router' >&2
  exit 1
fi
grep -Fq 'lockdown remains active' "$tmp/err"
sudo grep -Fq 'policy drop;' "$tmp/active.nft"
if sudo grep -Fq 'ether saddr' "$tmp/active.nft"; then
  echo 'FAIL: router failure did not leave lockdown rules active' >&2
  exit 1
fi

echo "=== concurrent setup serialization ==="
echo transit >"$tmp/mode"
: >"$tmp/overlap.log"
MOCK_CRITICAL_DIR="$tmp/nft-critical" run_setup >"$tmp/concurrent-1.out" 2>"$tmp/concurrent-1.err" &
p1=$!
MOCK_CRITICAL_DIR="$tmp/nft-critical" run_setup >"$tmp/concurrent-2.out" 2>"$tmp/concurrent-2.err" &
p2=$!
wait "$p1"
wait "$p2"
if [[ -s "$tmp/overlap.log" ]]; then
  echo 'FAIL: concurrent awg-pbr-setup executions overlapped nft apply' >&2
  exit 1
fi
grep -Fqx 'AWG_SETUP_MODE=transit' "$tmp/concurrent-1.out"
grep -Fqx 'AWG_SETUP_MODE=transit' "$tmp/concurrent-2.out"

echo "mode-aware boot setup: OK"
