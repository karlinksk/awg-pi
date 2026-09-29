#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat >"$tmp/env" <<'EOF'
LAN_IF='eth0'
PI_IP='192.168.88.2'
ROUTER_IP='192.168.88.1'
VPN_IF='awg0'
EOF

cat >"$tmp/bin/sysctl" <<'EOF'
#!/usr/bin/env bash
case "${*: -1}" in
  net.ipv4.ip_forward) echo 1 ;;
  net.ipv4.conf.all.src_valid_mark) echo 1 ;;
  *) exit 1 ;;
esac
EOF

cat >"$tmp/bin/ping" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

cat >"$tmp/bin/awg" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == "show awg0 endpoints" ]]; then
  printf 'peerkey\t203.0.113.7:51820\n'
  exit 0
fi
exit 1
EOF

cat >"$tmp/bin/ip" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "link show dev eth0")
    echo '2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>'
    ;;
  "link show dev awg0")
    echo '9: awg0: <POINTOPOINT,NOARP,UP,LOWER_UP>'
    ;;
  "-4 route get 1.1.1.1")
    echo '1.1.1.1 via 192.168.88.1 dev eth0 src 192.168.88.2'
    ;;
  "neigh show to 192.168.88.1 dev eth0")
    echo '192.168.88.1 lladdr 02:11:22:33:44:55 REACHABLE'
    ;;
  "-4 route get 203.0.113.7")
    if [[ "${MOCK_ENDPOINT_ROUTE:-direct}" == awg0 ]]; then
      echo '203.0.113.7 dev awg0 src 10.8.0.2'
    else
      echo '203.0.113.7 via 192.168.88.1 dev eth0 src 192.168.88.2'
    fi
    ;;
  *)
    echo "unexpected ip call: $*" >&2
    exit 1
    ;;
esac
EOF

chmod +x "$tmp/bin/"*

run_preflight(){
  PATH="$tmp/bin:$PATH" AWG_ENV_FILE="$tmp/env" \
    bash "$repo_root/src/awg-transit-preflight"
}

echo "=== transit preflight success ==="
out="$(run_preflight)"
grep -Fqx 'OK: IPv4 forwarding is enabled' <<<"$out"
grep -Fqx 'OK: src_valid_mark is enabled' <<<"$out"
grep -Fqx 'OK: main IPv4 route is DIRECT via 192.168.88.1 on eth0' <<<"$out"
grep -Fqx 'OK: MikroTik/router MAC resolved: 02:11:22:33:44:55' <<<"$out"
grep -Fqx 'OK: AWG endpoint stays DIRECT: 203.0.113.7 via 192.168.88.1 on eth0' <<<"$out"
grep -Fqx 'ROUTER_MAC=02:11:22:33:44:55' <<<"$out"
grep -Fqx 'TRANSIT_PREFLIGHT=OK' <<<"$out"

echo "=== transit preflight rejects recursive endpoint route ==="
if MOCK_ENDPOINT_ROUTE=awg0 run_preflight >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: endpoint routed through awg0 was accepted' >&2
  exit 1
fi
grep -Fq 'AWG endpoint 203.0.113.7 is not DIRECT' "$tmp/err"

echo "transit preflight: OK"
