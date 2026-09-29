#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/state"

cat >"$tmp/preflight" <<'EOF'
#!/usr/bin/env bash
cat <<'OUT'
=== Transit preflight ===
OK: mock preflight
ROUTER_MAC=02:11:22:33:44:55
TRANSIT_PREFLIGHT=OK
OUT
EOF

cat >"$tmp/renderer" <<'EOF'
#!/usr/bin/env bash
cat <<NFT
table inet awg_pbr {
  chain forward_guard {
    type filter hook forward priority filter; policy drop;
    iifname "awg0" oifname "eth0" ct state established,related accept
    iifname "eth0" ether saddr ${ROUTER_MAC} oifname "awg0" accept
  }
  chain prerouting_mark {
    type filter hook prerouting priority mangle; policy accept;
    iifname "eth0" ether saddr ${ROUTER_MAC} meta mark set 0x100
  }
  chain postrouting_nat {
    type nat hook postrouting priority srcnat; policy accept;
    oifname "awg0" masquerade
  }
}
NFT
EOF

cat >"$tmp/bin/nft" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"${MOCK_NFT_LOG:?}"

case "$*" in
  "-c -f "*)
    [[ "${MOCK_NFT_CHECK_FAIL:-0}" != 1 ]]
    ;;
  "-f "*)
    file="${2:-}"
    if grep -q 'transit-candidate' "$file" 2>/dev/null || grep -q 'ether saddr 02:11:22:33:44:55' "$file" 2>/dev/null; then
      echo transit >"${MOCK_NFT_STATE:?}"
    else
      echo restored >"${MOCK_NFT_STATE:?}"
    fi
    ;;
  "list table inet awg_pbr")
    cat <<'NFT'
table inet awg_pbr {
  chain old_selective {
    type filter hook forward priority filter; policy drop;
  }
}
NFT
    ;;
  "list chain inet awg_pbr forward_guard")
    if [[ "${MOCK_VERIFY_FAIL:-0}" == 1 ]]; then
      echo 'chain forward_guard { }'
    else
      echo 'chain forward_guard { iifname "eth0" ether saddr 02:11:22:33:44:55 oifname "awg0" accept }'
    fi
    ;;
  "list chain inet awg_pbr prerouting_mark")
    echo 'chain prerouting_mark { meta mark set 0x100 }'
    ;;
  "list chain inet awg_pbr postrouting_nat")
    echo 'chain postrouting_nat { oifname "awg0" masquerade }'
    ;;
  *)
    echo "unexpected nft call: $*" >&2
    exit 1
    ;;
esac
EOF

chmod +x "$tmp/preflight" "$tmp/renderer" "$tmp/bin/nft"

run_apply(){
  sudo env \
    AWG_TRANSIT_PREFLIGHT="$tmp/preflight" \
    AWG_TRANSIT_NFT_RENDERER="$tmp/renderer" \
    AWG_TRANSIT_STATE_DIR="$tmp/state" \
    NFT_BIN="$tmp/bin/nft" \
    MOCK_NFT_LOG="$tmp/nft.log" \
    MOCK_NFT_STATE="$tmp/nft.state" \
    MOCK_VERIFY_FAIL="${MOCK_VERIFY_FAIL:-0}" \
    bash "$repo_root/src/awg-transit-apply" "$@"
}

echo "=== transit prepare ==="
: >"$tmp/nft.log"
out="$(run_apply prepare)"
grep -Fqx 'TRANSIT_PREPARE=OK' <<<"$out"
sudo test -s "$tmp/state/transit-candidate.nft"
grep -Fq -- '-c -f' "$tmp/nft.log"

if sudo test -e "$tmp/state/pre-transit-table.nft"; then
  echo 'FAIL: prepare unexpectedly backed up/applied live table' >&2
  exit 1
fi

echo "=== transit apply success ==="
: >"$tmp/nft.log"
out="$(run_apply apply)"
grep -Fqx 'TRANSIT_NFT=APPLIED' <<<"$out"
grep -Fqx 'NOTE: operating mode state was not changed.' <<<"$out"
sudo test -s "$tmp/state/pre-transit-table.nft"
sudo test -s "$tmp/state/transit-apply.nft"
grep -Fq 'list table inet awg_pbr' "$tmp/nft.log"
grep -Fq 'list chain inet awg_pbr forward_guard' "$tmp/nft.log"

echo "=== transit apply rollback ==="
: >"$tmp/nft.log"
if MOCK_VERIFY_FAIL=1 run_apply apply >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: failed post-apply verification was accepted' >&2
  exit 1
fi
grep -Fq 'restoring previous table' "$tmp/err"
grep -Fq 'ROLLBACK=OK' "$tmp/err"
sudo test -s "$tmp/state/transit-rollback.nft"

echo "transit prepare/apply: OK"
