#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat >"$TMP/env" <<ENV
VPN_IF=awg0
HANDSHAKE_MAX_AGE=180
ENV
cat >"$TMP/bin/ip" <<'MOCK'
#!/usr/bin/env bash
[[ "$*" == "link show awg0" ]]
MOCK
cat >"$TMP/bin/awg" <<'MOCK'
#!/usr/bin/env bash
[[ "$*" == "show awg0 latest-handshakes" ]] || exit 1
echo 'peer 1000'
MOCK
cat >"$TMP/bin/date" <<'MOCK'
#!/usr/bin/env bash
echo 1100
MOCK
cat >"$TMP/bin/curl" <<'MOCK'
#!/usr/bin/env bash
case "$*" in
  *127.0.0.1:9090/version*) echo '{}' ;;
  *api.ipify.org*) echo '45.86.66.170' ;;
  *) exit 1 ;;
esac
MOCK
chmod +x "$TMP/bin/"*
echo '45.86.66.170' >"$TMP/expected"
export AWG_ENV_FILE="$TMP/env"
export AWG_COMMON_FILE="$ROOT/src/awg-common"
export AWG_TRANSPORT_FILE="$TMP/transport"
export IP_BIN="$TMP/bin/ip"
export AWG_BIN="$TMP/bin/awg"
export DATE_BIN="$TMP/bin/date"
export CURL_BIN="$TMP/bin/curl"
export MIHOMO_EXPECTED_IP_FILE="$TMP/expected"
CLI="$ROOT/src/awg-transport"
[[ "$($CLI get)" == awg ]]
OUT="$($CLI status)"
grep -Fq 'Transport ID: awg' <<<"$OUT"
grep -Fq 'Transport health: healthy' <<<"$OUT"
OUT="$($CLI list)"
grep -Eq '^awg +AmneziaWG +healthy$' <<<"$OUT"
grep -Eq '^mihomo +Mihomo +healthy$' <<<"$OUT"
printf '%s\n' mihomo >"$TMP/transport"
OUT="$($CLI status)"
grep -Fq 'Transport ID: mihomo' <<<"$OUT"
OUT="$($CLI check mihomo)"
[[ "$OUT" == healthy ]]
printf '%s\n' broken >"$TMP/transport"
if $CLI get >/dev/null 2>&1; then
  echo 'invalid transport unexpectedly accepted' >&2
  exit 1
fi
echo 'test-transport: PASS'
