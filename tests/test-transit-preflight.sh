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
HEALTH_MARK='0x101'
HEALTH_TABLE='101'
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
if [[ "$*" == *"-I awg0"* && "$*" == *"-m 257"* && "${MOCK_TUNNEL_HEALTH:-up}" != up ]]; then
  exit 1
fi
exit 0
EOF

cat >"$tmp/bin/awg" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "show awg0 endpoints")
    printf 'peerkey\t203.0.113.7:51820\n'
    ;;
  "show awg0 latest-handshakes")
    printf 'peerkey\t%s\n' "$(date +%s)"
    ;;
  *) exit 1 ;;
esac
EOF

cat >"$tmp/bin/ip" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${MOCK_IP_LOG:?}"
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
  "-4 route replace default dev awg0 table 101")
    ;;
  "-4 rule show")
    if [[ "${MOCK_HEALTH_RULE:-missing}" == present ]]; then
      echo '90: from all fwmark 0x101 lookup 101'
    fi
    ;;
  "-4 rule add priority 90 fwmark 0x101 lookup 101")
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
  PATH="$tmp/bin:$PATH" AWG_ENV_FILE="$tmp/env" MOCK_IP_LOG="$tmp/ip.log" \
    bash "$repo_root/src/awg-transit-preflight"
}

echo "=== transit preflight success ==="
: >"$tmp/ip.log"
out="$(run_preflight)"
grep -Fqx 'OK: IPv4 forwarding is enabled' <<<"$out"
grep -Fqx 'OK: src_valid_mark is enabled' <<<"$out"
grep -Fqx 'OK: main IPv4 route is DIRECT via 192.168.88.1 on eth0' <<<"$out"
grep -Fqx 'OK: MikroTik/router MAC resolved: 02:11:22:33:44:55' <<<"$out"
grep -Fqx 'OK: AWG tunnel transport is usable' <<<"$out"
grep -Fq 'OK: AWG handshake is fresh:' <<<"$out"
grep -Fqx 'OK: AWG endpoint stays DIRECT: 203.0.113.7 via 192.168.88.1 on eth0' <<<"$out"
grep -Fqx 'ROUTER_MAC=02:11:22:33:44:55' <<<"$out"
grep -Fqx 'TRANSIT_PREFLIGHT=OK' <<<"$out"
grep -Fqx -- '-4 route replace default dev awg0 table 101' "$tmp/ip.log"
grep -Fqx -- '-4 rule add priority 90 fwmark 0x101 lookup 101' "$tmp/ip.log"

echo "=== transit preflight rejects recursive endpoint route ==="
if MOCK_ENDPOINT_ROUTE=awg0 run_preflight >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: endpoint routed through awg0 was accepted' >&2
  exit 1
fi
grep -Fq 'AWG endpoint 203.0.113.7 is not DIRECT' "$tmp/err"

echo "transit preflight: OK"

echo "=== transit preflight rejects unhealthy tunnel ==="
if MOCK_TUNNEL_HEALTH=down run_preflight >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: unhealthy AWG tunnel was accepted' >&2
  exit 1
fi
grep -Fq 'AWG tunnel transport test failed' "$tmp/err"
