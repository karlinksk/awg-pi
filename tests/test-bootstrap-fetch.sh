#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"

cat >"$TMP/env" <<'EOF'
LAN_IF=eth0
VPN_IF=awg0
EOF

cat >"$TMP/bin/transport" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$1" == check && $# -eq 2 ]] || exit 2
case "$2" in
  awg) [[ " ${MOCK_HEALTHY:-} " == *" awg "* ]] ;;
  mihomo) [[ " ${MOCK_HEALTHY:-} " == *" mihomo "* ]] ;;
  *) exit 1 ;;
esac
EOF

cat >"$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
: "${MOCK_CURL_LOG:?}"
path=direct
out=""
while (($#)); do
  case "$1" in
    --interface)
      case "$2" in
        eth0) path=direct ;;
        awg0) path=awg ;;
        *) path="interface:$2" ;;
      esac
      shift 2
      ;;
    -x)
      path=mihomo
      shift 2
      ;;
    -o)
      out="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf '%s\n' "$path" >>"$MOCK_CURL_LOG"
case " ${MOCK_FAIL_PATHS:-} " in
  *" $path "*) exit 35 ;;
esac
printf 'payload-%s\n' "$path" >"$out"
EOF
chmod +x "$TMP/bin/"*

run_fetch(){
  AWG_ENV_FILE="$TMP/env"   AWG_COMMON_FILE="$ROOT/src/awg-common"   AWG_TRANSPORT_FILE="$TMP/transport"   AWG_TRANSPORT_CLI="$TMP/bin/transport"   CURL_BIN="$TMP/bin/curl"   MOCK_CURL_LOG="$TMP/curl.log"   MOCK_HEALTHY="${MOCK_HEALTHY:-}"   MOCK_FAIL_PATHS="${MOCK_FAIL_PATHS:-}"   bash "$ROOT/src/awg-fetch" --url https://example.invalid/resource --output "$TMP/out" "$@"
}

echo "=== AUTO uses DIRECT first even without configured transport ==="
rm -f "$TMP/transport"
: >"$TMP/curl.log"
out="$(run_fetch --mode auto -- -4 -fsSL)"
grep -Fqx 'AWG_FETCH_PATH=direct' <<<"$out"
grep -Fqx direct "$TMP/curl.log"
grep -Fqx payload-direct "$TMP/out"

echo "=== AUTO falls back to selected healthy AWG ==="
echo awg >"$TMP/transport"
: >"$TMP/curl.log"
out="$(MOCK_HEALTHY='awg mihomo' MOCK_FAIL_PATHS=direct run_fetch --mode auto)"
mapfile -t paths <"$TMP/curl.log"
[[ "${paths[0]}" == direct ]]
[[ "${paths[1]}" == awg ]]
grep -Fqx 'AWG_FETCH_PATH=awg' <<<"$out"

echo "=== AUTO promotes selected healthy Mihomo ==="
echo mihomo >"$TMP/transport"
: >"$TMP/curl.log"
out="$(MOCK_HEALTHY='awg mihomo' MOCK_FAIL_PATHS=direct run_fetch --mode auto)"
mapfile -t paths <"$TMP/curl.log"
[[ "${paths[0]}" == direct ]]
[[ "${paths[1]}" == mihomo ]]
grep -Fqx 'AWG_FETCH_PATH=mihomo' <<<"$out"

echo "=== AUTO tries another healthy backend after selected backend fails ==="
: >"$TMP/curl.log"
out="$(MOCK_HEALTHY='awg mihomo' MOCK_FAIL_PATHS='direct mihomo' run_fetch --mode auto)"
mapfile -t paths <"$TMP/curl.log"
[[ "${paths[0]}" == direct ]]
[[ "${paths[1]}" == mihomo ]]
[[ "${paths[2]}" == awg ]]
grep -Fqx 'AWG_FETCH_PATH=awg' <<<"$out"

echo "=== unhealthy backends are skipped ==="
echo awg >"$TMP/transport"
: >"$TMP/curl.log"
if MOCK_HEALTHY='' MOCK_FAIL_PATHS=direct run_fetch --mode auto >"$TMP/stdout" 2>"$TMP/stderr"; then
  echo 'FAIL: AUTO succeeded with DIRECT failed and no healthy backend' >&2
  exit 1
fi
[[ "$(wc -l <"$TMP/curl.log" | tr -d ' ')" == 1 ]]
grep -Fqx direct "$TMP/curl.log"

echo "=== explicit channel never silently falls back ==="
: >"$TMP/curl.log"
if MOCK_FAIL_PATHS=direct run_fetch --mode direct >"$TMP/stdout" 2>"$TMP/stderr"; then
  echo 'FAIL: explicit DIRECT failure unexpectedly succeeded' >&2
  exit 1
fi
grep -Fqx direct "$TMP/curl.log"
[[ "$(wc -l <"$TMP/curl.log" | tr -d ' ')" == 1 ]]

echo "=== legacy router mode maps to DIRECT ==="
: >"$TMP/curl.log"
out="$(run_fetch --mode router 2>"$TMP/router.err")"
grep -Fqx 'AWG_FETCH_PATH=direct' <<<"$out"
grep -Fq "Deprecated fetch mode 'router' mapped to DIRECT." "$TMP/router.err"

echo "bootstrap fetch manager: OK"
