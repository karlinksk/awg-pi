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

cat >"$TMP/bin/fetch" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
: "${MOCK_FETCH_LOG:?}"
: "${MOCK_ARCHIVE:?}"
mode=auto
out=""
while (($#)); do
  case "$1" in
    --mode)
      mode="$2"; shift 2 ;;
    --output)
      out="$2"; shift 2 ;;
    --url)
      printf 'url=%s\n' "$2" >>"$MOCK_FETCH_LOG"; shift 2 ;;
    --)
      break ;;
    *)
      shift ;;
  esac
done
printf 'mode=%s\n' "$mode" >>"$MOCK_FETCH_LOG"
[[ "${MOCK_FETCH_FAIL:-0}" != 1 ]] || exit 1
path="${MOCK_FETCH_PATH:-}"
if [[ -z "$path" ]]; then
  case "$mode" in
    direct|awg|mihomo) path="$mode" ;;
    auto) path=direct ;;
    *) exit 2 ;;
  esac
fi
cp "$MOCK_ARCHIVE" "$out"
printf 'AWG_FETCH_PATH=%s\n' "$path"
MOCK
chmod +x "$TMP/bin/fetch"

run_install(){
  local target="$1"; shift
  sudo env \
    AWG_FETCH_BIN="$TMP/bin/fetch" \
    MIHOMO_TARGET="$target" \
    MIHOMO_INSTALL_ASSET_URL="https://example.invalid/mihomo.gz" \
    MIHOMO_INSTALL_ASSET_SHA256="$SHA" \
    MOCK_ARCHIVE="$TMP/mihomo.gz" \
    MOCK_FETCH_LOG="$TMP/fetch.log" \
    MOCK_FETCH_PATH="${MOCK_FETCH_PATH:-}" \
    MOCK_FETCH_FAIL="${MOCK_FETCH_FAIL:-0}" \
    bash "$ROOT/src/awg-mihomo-install" "$@"
}

echo "=== installer AUTO delegates to shared manager ==="
: >"$TMP/fetch.log"
out="$(MOCK_FETCH_PATH=direct run_install "$TMP/target-direct")"
grep -Fqx 'mode=auto' "$TMP/fetch.log"
grep -Fqx 'MIHOMO_BINARY_FETCH_PATH=direct' <<<"$out"
"$TMP/target-direct" -v | grep -Fqx 'Mihomo Meta v1.19.32'

echo "=== explicit AWG channel is preserved ==="
: >"$TMP/fetch.log"
out="$(MOCK_FETCH_PATH=awg run_install "$TMP/target-awg" --mode awg)"
grep -Fqx 'mode=awg' "$TMP/fetch.log"
grep -Fqx 'MIHOMO_BINARY_FETCH_PATH=awg' <<<"$out"
"$TMP/target-awg" -v | grep -Fqx 'Mihomo Meta v1.19.32'

echo "=== explicit channel failure does not install partial binary ==="
: >"$TMP/fetch.log"
if MOCK_FETCH_FAIL=1 run_install "$TMP/target-fail" --mode direct >"$TMP/out" 2>"$TMP/err"; then
  echo 'FAIL: explicit DIRECT failure unexpectedly succeeded' >&2
  exit 1
fi
grep -Fqx 'mode=direct' "$TMP/fetch.log"
[[ ! -e "$TMP/target-fail" ]]
grep -Fq 'Unable to download Mihomo binary through bootstrap manager' "$TMP/err"

echo "=== legacy router mode maps to DIRECT ==="
: >"$TMP/fetch.log"
out="$(MOCK_FETCH_PATH=direct run_install "$TMP/target-legacy" --mode router)"
grep -Fqx 'mode=direct' "$TMP/fetch.log"
grep -Fqx 'MIHOMO_BINARY_FETCH_PATH=direct' <<<"$out"

echo "=== offline pinned archive bypasses bootstrap manager ==="
: >"$TMP/fetch.log"
out="$(run_install "$TMP/target-local" --file "$TMP/mihomo.gz")"
grep -Fqx 'MIHOMO_BINARY_FETCH_PATH=file' <<<"$out"
[[ ! -s "$TMP/fetch.log" ]]
"$TMP/target-local" -v | grep -Fqx 'Mihomo Meta v1.19.32'

echo "=== bad offline archive never replaces target ==="
cp "$TMP/target-local" "$TMP/target-keep"
printf 'corrupted-archive\n' >"$TMP/bad.gz"
if run_install "$TMP/target-keep" --file "$TMP/bad.gz" >"$TMP/out" 2>"$TMP/err"; then
  echo 'FAIL: corrupted local Mihomo archive unexpectedly succeeded' >&2
  exit 1
fi
"$TMP/target-keep" -v | grep -Fqx 'Mihomo Meta v1.19.32'
grep -Fq 'FAILED' "$TMP/out"

echo "mihomo installer bootstrap: OK"
