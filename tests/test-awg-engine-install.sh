#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/bundle" "$TMP/go-parent/go/bin" "$TMP/src" "$TMP/etc/profile.d"
: >"$TMP/log"

for name in   go1.27.1.linux-arm64.tar.gz   amneziawg-go-v3.1.20260828.tar.gz   amneziawg-tools-v3.1.20260812.tar.gz
do
  printf 'fixture-%s\n' "$name" >"$TMP/bundle/$name"
done

cat >"$TMP/bin/sha256sum" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == -c ]]; then
  cat >/dev/null
  echo 'checksum: OK'
  exit 0
fi
exec /usr/bin/sha256sum "$@"
MOCK

cat >"$TMP/bin/go" <<'MOCK'
#!/usr/bin/env bash
echo 'go version go1.27.1 linux/arm64'
MOCK

cat >"$TMP/bin/awg" <<'MOCK'
#!/usr/bin/env bash
echo 'amneziawg-tools v3.1.20260812 - https://amnezia.org'
MOCK

cat >"$TMP/bin/awg-quick" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK

cat >"$TMP/bin/amneziawg-go" <<'MOCK'
#!/usr/bin/env bash
echo 'amneziawg-go v3.1.20260828'
MOCK

cat >"$TMP/bin/make" <<'MOCK'
#!/usr/bin/env bash
printf 'make:%s\n' "$*" >>"${MOCK_LOG:?}"
printf 'proxy:%s\n' "${HTTPS_PROXY:-none}" >>"${MOCK_LOG:?}"
exit 0
MOCK

cat >"$TMP/bin/tar" <<'MOCK'
#!/usr/bin/env bash
printf 'tar:%s\n' "$*" >>"${MOCK_LOG:?}"
exit 0
MOCK

cat >"$TMP/bin/gzip" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK

cat >"$TMP/bin/gcc" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK

cat >"$TMP/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
printf 'systemctl:%s\n' "$*" >>"${MOCK_LOG:?}"
exit 0
MOCK

cat >"$TMP/bin/fetch" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
: "${MOCK_FETCH_LOG:?}"
mode=auto
url=""
out=""
while (($#)); do
  case "$1" in
    --mode) mode="$2"; shift 2 ;;
    --url) url="$2"; shift 2 ;;
    --output) out="$2"; shift 2 ;;
    --) break ;;
    *) shift ;;
  esac
done
printf 'mode=%s url=%s\n' "$mode" "$url" >>"$MOCK_FETCH_LOG"
printf 'downloaded\n' >"$out"
printf 'AWG_FETCH_PATH=%s\n' "${MOCK_FETCH_PATH:-direct}"
MOCK

chmod +x "$TMP/bin/"*

run_engine(){
  sudo env     PATH="$TMP/bin:$PATH"     AWG_ENGINE_ARCH=arm64     AWG_FETCH_BIN="$TMP/bin/fetch"     AWG_ENV_FILE="$TMP/env"     AWG_SRC_ROOT="$TMP/src"     AWG_GO_ROOT="$TMP/go-parent/go"     AWG_GO_PROFILE="$TMP/etc/profile.d/go.sh"     SYSTEMCTL_BIN="$TMP/bin/systemctl"     MOCK_LOG="$TMP/log"     MOCK_FETCH_LOG="$TMP/fetch.log"     MOCK_FETCH_PATH="${MOCK_FETCH_PATH:-}"     bash "$ROOT/src/awg-engine-install" "$@"
}

echo "=== offline pinned bundle ==="
: >"$TMP/log"; : >"$TMP/fetch.log"
out="$(run_engine --bundle "$TMP/bundle")"
grep -Fqx 'AWG_ENGINE=INSTALLED' <<<"$out"
grep -Fqx 'AWG_GO_TAG=v3.1.20260828' <<<"$out"
grep -Fqx 'AWG_TOOLS_TAG=v3.1.20260812' <<<"$out"
grep -Fqx 'AWG_ENGINE_SOURCE=local-bundle' <<<"$out"
[[ ! -s "$TMP/fetch.log" ]]
grep -Fq 'make:-C '"$TMP/src/amneziawg-go" "$TMP/log"
grep -Fq 'make:-C '"$TMP/src/amneziawg-tools/src" "$TMP/log"
grep -Fq 'systemctl:daemon-reload' "$TMP/log"

echo "=== bootstrap-manager network acquisition ==="
rm -rf "$TMP/src"; mkdir -p "$TMP/src"
: >"$TMP/log"; : >"$TMP/fetch.log"
out="$(run_engine --mode auto)"
grep -Fqx 'AWG_ENGINE=INSTALLED' <<<"$out"
grep -Fqx 'AWG_ENGINE_SOURCE=auto' <<<"$out"
[[ "$(wc -l <"$TMP/fetch.log" | tr -d ' ')" == 3 ]]
grep -Fq 'mode=auto url=https://go.dev/dl/go1.27.1.linux-arm64.tar.gz' "$TMP/fetch.log"
grep -Fq 'amneziawg-go/archive/refs/tags/v3.1.20260828.tar.gz' "$TMP/fetch.log"
grep -Fq 'amneziawg-tools/archive/refs/tags/v3.1.20260812.tar.gz' "$TMP/fetch.log"

echo "=== Mihomo bootstrap path is inherited by Go module build ==="
rm -rf "$TMP/src"; mkdir -p "$TMP/src"
: >"$TMP/log"; : >"$TMP/fetch.log"
out="$(MOCK_FETCH_PATH=mihomo run_engine --mode auto)"
printf '%s\n' "$out"
grep '^proxy:' "$TMP/log" || true
grep '^mode=' "$TMP/fetch.log" || true
grep -Fqx 'AWG_ENGINE_FETCH_PATHS=mihomo mihomo mihomo' <<<"$out"
grep -Fq 'proxy=http://127.0.0.1:7890' "$TMP/log"

echo "=== offline bundle must contain all pinned archives ==="
rm -f "$TMP/bundle/amneziawg-tools-v3.1.20260812.tar.gz"
if run_engine --bundle "$TMP/bundle" >"$TMP/out" 2>"$TMP/err"; then
  echo 'FAIL: incomplete offline AWG bundle unexpectedly succeeded' >&2
  exit 1
fi
grep -Fq 'Offline AWG bundle is missing: amneziawg-tools-v3.1.20260812.tar.gz' "$TMP/err"

echo "awg engine bootstrap: OK"
