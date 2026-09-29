#!/usr/bin/env bash
set -Eeuo pipefail

# Execute actual installer functions under nounset, not copies of their logic.
eval "$(sed -n '/^valid_ipv4(){/,/^in_cidr(){/p' install.sh | sed '$d')"
valid_cidr4 192.168.112.0/24
valid_cidr4 0.0.0.0/0
valid_cidr4 192.168.112.33/32
for bad in 192.168.1.1 192.168.1.1/33 999.1.1.1/24 1.2.3.4/no; do
  if valid_cidr4 "$bad"; then echo "Accepted invalid CIDR: $bad" >&2; exit 1; fi
done

# Debian os-release must not change the project's version or download ref.
eval "$(sed -n '/^AWG_PI_VERSION=/p; /^PROJECT_REF=/p' install.sh)"
VERSION='13 (trixie)'
[[ "$AWG_PI_VERSION" == 1.1.0 && "$PROJECT_REF" == v1.1.0 ]]

# Clean installs must offer the hardware-validated DNS pair by default.
grep -Fq 'ask "Upstream DNS для Raspberry Pi через запятую" "9.9.9.9,149.112.112.112"' install.sh

# Exercise the installed mode-aware health monitor function with a ping mock that rejects hex.
ping(){
  local previous='' arg
  for arg in "$@"; do
    if [[ "$previous" == -m ]]; then [[ "$arg" == 257 ]] || return 1; fi
    previous="$arg"
  done
}
HEALTH_MARK=0x101
transport_body="$(sed -n '/^transport_ok(){/,/^}/p' src/awg-pbr-health)"
first_transport_ping="$(grep -m1 '\$PING_BIN.*-4 -n -m' <<<"$transport_body")"
[[ "$first_transport_ping" == *'9.9.9.9'* ]]
PING_BIN=ping
eval "$transport_body"
transport_ok
# Every diagnostics ping uses the same decimal conversion.
while IFS= read -r line; do
  [[ "$line" == *'-m "$((HEALTH_MARK))"'* ]]
done < <(grep -E 'ping .* -m |PING_BIN.* -m ' src/awg-route src/awg-pbr-health)
echo 'RC2 installer/health regressions: OK'
