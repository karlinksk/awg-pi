#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'sudo rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/etc" "$TMP/run"
printf '%s\n' unconfigured >"$TMP/transport"
: >"$TMP/log"

cat >"$TMP/bin/transport" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
state="${MOCK_TRANSPORT_STATE:?}"
case "${1:-}" in
  get)
    cat "$state"
    ;;
  select)
    printf 'transport-select:%s\n' "$2" >>"${MOCK_LOG:?}"
    printf '%s\n' "$2" >"$state"
    printf 'Transport ID: %s\n' "$2"
    ;;
  status)
    printf 'Transport ID: %s\n' "$(cat "$state")"
    ;;
  *)
    exit 2
    ;;
esac
MOCK

cat >"$TMP/bin/route" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'route:%s\n' "$*" >>"${MOCK_LOG:?}"
case "$*" in
  "config check "*) exit 0 ;;
  "config replace "*" --yes") exit 0 ;;
  *) exit 2 ;;
esac
MOCK

cat >"$TMP/bin/mihomo-configure" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'mihomo:%s\n' "$*" >>"${MOCK_LOG:?}"
case "$*" in
  "init "*) exit 0 ;;
  "provider import "*) exit 0 ;;
  "node list")
    printf 'Finland\tvless\t45.86.66.170:443\n'
    ;;
  "node prepare Finland")
    cat <<'OUT'
Node: Finland
Type: vless
Resolved IPv4 endpoints:
  - 45.86.66.170
OUT
    ;;
  "node select Finland 45.86.66.170")
    printf 'MIHOMO_HEALTH=healthy\n'
    ;;
  *) exit 2 ;;
esac
MOCK

cat >"$TMP/bin/mihomo-install" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'mihomo-install\n' >>"${MOCK_LOG:?}"
cat >"${MIHOMO_BIN:?}" <<'BIN'
#!/usr/bin/env bash
exit 0
BIN
chmod 755 "${MIHOMO_BIN:?}"
MOCK

chmod +x "$TMP/bin/"*

run_first(){
  sudo env     AWG_ROUTE_BIN="$TMP/bin/route"     AWG_TRANSPORT_BIN="$TMP/bin/transport"     MIHOMO_CONFIGURE_BIN="$TMP/bin/mihomo-configure"     MIHOMO_INSTALLER_BIN="$TMP/bin/mihomo-install"     MIHOMO_ENV_FILE="$TMP/etc/provider.env"     MIHOMO_BIN="$TMP/bin/mihomo"     AWG_FIRST_RUN_NODE=Finland     AWG_FIRST_RUN_ENDPOINT=45.86.66.170     MOCK_TRANSPORT_STATE="$TMP/transport"     MOCK_LOG="$TMP/log"     bash "$ROOT/src/awg-first-run" "$@"
}

echo "=== AWG first transport ==="
printf '%s\n' unconfigured >"$TMP/transport"
: >"$TMP/log"
printf 'dummy-awg-profile\n' >"$TMP/awg.conf"
out="$(run_first awg-file "$TMP/awg.conf")"
grep -Fqx 'FIRST_TRANSPORT=awg' <<<"$out"
grep -Fq "route:config check $TMP/awg.conf" "$TMP/log"
grep -Fq "route:config replace $TMP/awg.conf --yes" "$TMP/log"
grep -Fqx 'transport-select:awg' "$TMP/log"
grep -Fqx awg "$TMP/transport"

echo "=== existing transport is never silently replaced ==="
if run_first mihomo-file "$TMP/awg.conf" >"$TMP/out" 2>"$TMP/err"; then
  echo 'FAIL: first-run replaced an already selected transport' >&2
  exit 1
fi
grep -Fq 'already selected' "$TMP/err"

echo "=== Mihomo URL first transport ==="
printf '%s\n' unconfigured >"$TMP/transport"
: >"$TMP/log"
out="$(run_first mihomo-url 'https://subscription.example/token' standard auto)"
grep -Fqx 'FIRST_TRANSPORT=mihomo' <<<"$out"
grep -Eq '^mihomo:init ' "$TMP/log"
grep -Fqx 'mihomo:node list' "$TMP/log"
grep -Fqx 'mihomo:node select Finland 45.86.66.170' "$TMP/log"
grep -Fqx 'transport-select:mihomo' "$TMP/log"
grep -Fqx mihomo "$TMP/transport"

echo "=== Mihomo local provider first transport ==="
printf '%s\n' unconfigured >"$TMP/transport"
rm -f "$TMP/bin/mihomo" "$TMP/etc/provider.env"
: >"$TMP/log"
printf 'vless://example\n' >"$TMP/provider.txt"
out="$(run_first mihomo-file "$TMP/provider.txt" auto)"
grep -Fqx 'FIRST_TRANSPORT=mihomo' <<<"$out"
grep -Fqx 'mihomo-install' "$TMP/log"
grep -Fq "mihomo:provider import $TMP/provider.txt" "$TMP/log"
grep -Fqx 'mihomo:node select Finland 45.86.66.170' "$TMP/log"
grep -Fqx 'transport-select:mihomo' "$TMP/log"
grep -Fqx mihomo "$TMP/transport"
grep -Fqx 'MIHOMO_PROVIDER_PROFILE=standard' "$TMP/etc/provider.env"
grep -Fqx 'MIHOMO_PROVIDER_FORMAT=auto' "$TMP/etc/provider.env"
if grep -q '^MIHOMO_PROVIDER_URL=' "$TMP/etc/provider.env"; then
  echo 'FAIL: local-only provider unexpectedly gained a network URL' >&2
  exit 1
fi

echo "=== installer orders first transport before Operating Mode ==="
first_line="$(grep -n -F '"$FIRST_RUN_CLI" wizard' "$ROOT/install.sh" | head -1 | cut -d: -f1)"
mode_line="$(grep -n -F 'log "[11b/12] Operating Mode selection"' "$ROOT/install.sh" | head -1 | cut -d: -f1)"
[[ -n "$first_line" && -n "$mode_line" ]]
(( first_line < mode_line ))

grep -Fq '1) AmneziaWG native .conf — файл' "$ROOT/src/awg-first-run"
grep -Fq '3) Mihomo / VLESS subscription URL' "$ROOT/src/awg-first-run"
grep -Fq '4) Mihomo provider/subscription — локальный файл' "$ROOT/src/awg-first-run"
grep -Fq '5) Mihomo provider/subscription — вставить текст' "$ROOT/src/awg-first-run"
grep -Fq '6) Пока ничего не настраивать' "$ROOT/src/awg-first-run"

echo "first transport wizard: OK"
