#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC1091
source src/awg-common

fail(){ echo "FAIL: $*" >&2; exit 1; }
eq(){ [[ "$1" == "$2" ]] || fail "expected '$2', got '$1'"; }

eq "$(awg_normalize_domain ' HTTPS://*.YouTube.COM/path?q=1 ')" "youtube.com"
eq "$(awg_normalize_domain '.Example.COM.')" "example.com"
eq "$(awg_normalize_domain 'https://sub.example.com:443/abc')" "sub.example.com"

awg_valid_domain youtube.com || fail "youtube.com should be valid"
awg_valid_domain sub.example.co.uk || fail "sub.example.co.uk should be valid"
awg_valid_domain xn--e1afmkfd.xn--p1ai || fail "punycode should be valid"

! awg_valid_domain localhost || fail "single-label name should be invalid"
! awg_valid_domain '-bad.example' || fail "leading hyphen should be invalid"
! awg_valid_domain 'bad-.example' || fail "trailing hyphen should be invalid"
! awg_valid_domain 'bad..example' || fail "empty label should be invalid"
! awg_valid_domain 'bad_example.com' || fail "underscore should be invalid"

awg_valid_ipv4 192.168.0.2 || fail "IPv4 should be valid"
! awg_valid_ipv4 999.1.1.1 || fail "IPv4 range should be validated"
! awg_valid_ipv4 1.2.3 || fail "short IPv4 should be invalid"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/ip4" <<'EOF'
1.1.1.1
8.8.8.8
EOF
awg_validate_ipv4_list_file "$tmp/ip4" ip4 || fail "valid IPv4 list rejected"

cat >"$tmp/cidr4" <<'EOF'
1.1.1.0/24
8.8.0.0/16
EOF
awg_validate_ipv4_list_file "$tmp/cidr4" cidr4 || fail "valid CIDR list rejected"

echo '300.1.1.1' >"$tmp/bad"
! awg_validate_ipv4_list_file "$tmp/bad" ip4 || fail "invalid IPv4 list accepted"

echo "common helpers: OK"
