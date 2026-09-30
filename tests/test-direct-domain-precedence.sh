#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fail(){
  echo "FAIL: $*" >&2
  exit 1
}

extract_func(){
  local name="$1"
  sed -n "/^${name}(){/,/^}/p" "$repo_root/src/awg-route"
}

eval "$(extract_func domain_matches_file)"
eval "$(extract_func append_dns_rules_from_file)"

DD="$tmp/direct-domains.txt"
DC="$tmp/99-awg-pbr-domains.conf"
vpn="$tmp/vpn-domains.txt"
opencck="$tmp/opencck.domains"

cat >"$DD" <<'EOF'
youtube.com
EOF

cat >"$vpn" <<'EOF'
wikipedia.org
youtube.com
accounts.youtube.com
foo.accounts.youtube.com
other.example
EOF

cat >"$opencck" <<'EOF'
accounts.youtube.com
googlevideo.com
www.youtube.com
EOF

: >"$DC"
append_dns_rules_from_file "$vpn" vpn4
append_dns_rules_from_file "$DD" direct4
append_dns_rules_from_file "$opencck" vpn4

grep -Fqx 'nftset=/youtube.com/4#inet#awg_pbr#direct4' "$DC" ||
  fail "DIRECT parent rule missing"
grep -Fqx 'nftset=/wikipedia.org/4#inet#awg_pbr#vpn4' "$DC" ||
  fail "unrelated manual VPN rule missing"
grep -Fqx 'nftset=/other.example/4#inet#awg_pbr#vpn4' "$DC" ||
  fail "second unrelated manual VPN rule missing"
grep -Fqx 'nftset=/googlevideo.com/4#inet#awg_pbr#vpn4' "$DC" ||
  fail "unrelated OpenCCK VPN rule missing"

for blocked in youtube.com accounts.youtube.com foo.accounts.youtube.com www.youtube.com; do
  if grep -Fqx "nftset=/$blocked/4#inet#awg_pbr#vpn4" "$DC"; then
    fail "DIRECT-covered VPN rule leaked into dnsmasq config: $blocked"
  fi
done

cat >"$DD" <<'EOF'
accounts.youtube.com
EOF
cat >"$vpn" <<'EOF'
youtube.com
accounts.youtube.com
EOF

: >"$DC"
append_dns_rules_from_file "$vpn" vpn4
append_dns_rules_from_file "$DD" direct4

grep -Fqx 'nftset=/youtube.com/4#inet#awg_pbr#vpn4' "$DC" ||
  fail "broader VPN parent should remain when only child is DIRECT"
if grep -Fqx 'nftset=/accounts.youtube.com/4#inet#awg_pbr#vpn4' "$DC"; then
  fail "exact DIRECT child also emitted as VPN"
fi
grep -Fqx 'nftset=/accounts.youtube.com/4#inet#awg_pbr#direct4' "$DC" ||
  fail "DIRECT child rule missing"

echo "DIRECT domain precedence: OK"
