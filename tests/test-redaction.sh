#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC1091
source src/awg-common
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
awg(){
  [[ "$WG_COLOR_MODE" == never && "$WG_HIDE_KEYS" == always ]]
  cat <<'EOF'
interface: awg0
  public key: PUBLIC_VISIBLE
  private key: PRIVATE_SENTINEL
  header protection key: HEADER_SENTINEL
peer: PEER_VISIBLE
  preshared key: PSK_SENTINEL
  latest handshake: 6 seconds ago
  transfer: 1 MiB received
EOF
}
# Even an inherited request to show keys must be overridden.
export WG_HIDE_KEYS=never WG_COLOR_MODE=always
awg_safe_show awg0 | tee "$tmp/report" >"$tmp/terminal"
for output in "$tmp/report" "$tmp/terminal"; do
  if grep -Eq 'PRIVATE_SENTINEL|HEADER_SENTINEL|PSK_SENTINEL' "$output"; then
    echo 'Secret leaked' >&2; exit 1
  fi
  grep -Fq 'header protection key: (hidden)' "$output"
  grep -Fq 'PUBLIC_VISIBLE' "$output"
  grep -Fq 'latest handshake: 6 seconds ago' "$output"
done
# Human-readable AWG output must never bypass the helper at a call site.
if grep -E 'awg show "\$VPN_IF"( *\|\|| *2>| *$)' src/awg-route install.sh; then
  echo 'Unsafe AWG output call site' >&2; exit 1
fi
echo 'AWG secret redaction: OK'
