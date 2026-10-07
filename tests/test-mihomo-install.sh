#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"

cat >"$TMP/mock-mihomo" <<'MOCK'
#!/usr/bin/env bash
if [[ "${1:-}" == "-v" ]]; then
  echo "Mihomo Meta v1.19.32"
  exit 0
fi
exit 0
MOCK
chmod +x "$TMP/mock-mihomo"
gzip -c "$TMP/mock-mihomo" >"$TMP/mihomo.gz"
SHA="$(sha256sum "$TMP/mihomo.gz" | awk '{print $1}')"

cat >"$TMP/bin/ip" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK
chmod +x "$TMP/bin/ip"

cat >"$TMP/bin/curl" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
: "${MOCK_CURL_LOG:?}"
: "${MOCK_ARCHIVE:?}"
out=""
path=router
while (($#)); do
  case "$1" in
    --interface)
      path=awg
      printf 'interface=%s\n' "$2" >>"$MOCK_CURL_LOG"
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
printf 'path=%s\n' "$path" >>"$MOCK_CURL_LOG"
case " ${MOCK_FAIL_PATHS:-} " in
  *" $path "*) exit 35 ;;
esac
[[ -n "$out" ]]
cp "$MOCK_ARCHIVE" "$out"
MOCK
chmod +x "$TMP/bin/curl"

run_install(){
  local target="$1"; shift
  sudo env \
    CURL_BIN="$TMP/bin/curl" \
    IP_BIN="$TMP/bin/ip" \
    MIHOMO_TARGET="$target" \
    MIHOMO_INSTALL_ASSET_URL="https://example.invalid/mihomo.gz" \
    MIHOMO_INSTALL_ASSET_SHA256="$SHA" \
    MIHOMO_AWG_INTERFACE="awg0" \
    MOCK_ARCHIVE="$TMP/mihomo.gz" \
    MOCK_CURL_LOG="$TMP/curl.log" \
    MOCK_FAIL_PATHS="${MOCK_FAIL_PATHS:-}" \
    bash "$ROOT/src/awg-mihomo-install" "$@"
}

echo "=== installer AUTO uses AWG first ==="
: >"$TMP/curl.log"
out="$(run_install "$TMP/target-awg")"
grep -Fqx 'path=awg' "$TMP/curl.log"
grep -Fqx 'MIHOMO_BINARY_FETCH_PATH=awg' <<<"$out"
"$TMP/target-awg" -v | grep -Fqx 'Mihomo Meta v1.19.32'

echo "=== installer AUTO falls back to router/default ==="
: >"$TMP/curl.log"
out="$(MOCK_FAIL_PATHS=awg run_install "$TMP/target-router")"
mapfile -t paths < <(grep '^path=' "$TMP/curl.log")
[[ "${paths[0]}" == "path=awg" ]]
[[ "${paths[1]}" == "path=router" ]]
grep -Fqx 'MIHOMO_BINARY_FETCH_PATH=router' <<<"$out"
"$TMP/target-router" -v | grep -Fqx 'Mihomo Meta v1.19.32'

echo "=== explicit AWG failure does not silently switch paths ==="
: >"$TMP/curl.log"
if MOCK_FAIL_PATHS=awg run_install "$TMP/target-fail" --mode awg >"$TMP/out" 2>"$TMP/err"; then
  echo 'FAIL: explicit AWG mode unexpectedly succeeded' >&2
  exit 1
fi
grep -Fqx 'path=awg' "$TMP/curl.log"
if grep -Fq 'path=router' "$TMP/curl.log"; then
  echo 'FAIL: explicit AWG mode silently used router fallback' >&2
  exit 1
fi
[[ ! -e "$TMP/target-fail" ]]
grep -Fq 'Unable to download Mihomo binary through awg' "$TMP/err"

echo "mihomo installer bootstrap: OK"
