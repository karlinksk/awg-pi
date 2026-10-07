#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat >"$tmp/bin/installer" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'installer\n' >>"${MOCK_INSTALL_LOG:?}"
cat >"${MIHOMO_BIN:?}" <<'BIN'
#!/usr/bin/env bash
exit 0
BIN
chmod 755 "$MIHOMO_BIN"
MOCK

cat >"$tmp/bin/updater" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'args=%s\n' "$*" >>"${MOCK_UPDATE_LOG:?}"
[[ "${MOCK_UPDATE_FAIL:-0}" != 1 ]] || exit 1
# shellcheck disable=SC1090
source "${MIHOMO_ENV_FILE:?}"
{
  printf 'profile=%s\n' "${MIHOMO_PROVIDER_PROFILE:-}"
  printf 'suffix=%s\n' "${MIHOMO_UPDATE_SUFFIX:-}"
  printf 'has_hwid=%s\n' "$([[ -n "${MIHOMO_PROVIDER_HWID:-}" ]] && echo yes || echo no)"
} >>"${MOCK_UPDATE_LOG:?}"
mkdir -p "$(dirname "${MIHOMO_PROVIDER_FILE:?}")"
cat >"$MIHOMO_PROVIDER_FILE" <<'YAML'
proxies:
  - name: Finland
    type: vless
    server: 45.86.66.170
    port: 443
  - name: Germany
    type: vless
    server: 203.0.113.7
    port: 443
YAML
printf 'awg\n' >"${MIHOMO_LAST_FETCH_FILE:?}"
MOCK

cat >"$tmp/bin/openssl" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$*" == "rand -hex 16" ]] || exit 2
printf '%s\n' 0123456789abcdef0123456789abcdef
MOCK
chmod +x "$tmp/bin/"*

prepare_case(){
  local name="$1"
  CASE="$tmp/$name"
  sudo rm -rf "$CASE"
  mkdir -p "$CASE/etc" "$CASE/state/providers"
  printf '%s\n' awg >"$CASE/transport"
  : >"$CASE/install.log"
  : >"$CASE/update.log"
}

write_init(){
  local profile="$1" url="$2" hwid="${3:-}"
  {
    printf 'MIHOMO_PROVIDER_URL=%q\n' "$url"
    printf 'MIHOMO_PROVIDER_PROFILE=%q\n' "$profile"
    [[ -z "$hwid" ]] || printf 'MIHOMO_PROVIDER_HWID=%q\n' "$hwid"
  } | sudo tee "$CASE/init.env" >/dev/null
  sudo chmod 600 "$CASE/init.env"
}

run_init(){
  sudo env \
    AWG_COMMON_FILE="$repo_root/src/awg-common" \
    AWG_TRANSPORT_FILE="$CASE/transport" \
    AWG_LOCK_FILE="$CASE/lock" \
    MIHOMO_ENV_FILE="$CASE/etc/provider.env" \
    MIHOMO_PROVIDER_FILE="$CASE/state/providers/subscription.yaml" \
    MIHOMO_LAST_FETCH_FILE="$CASE/state/last-fetch-path" \
    MIHOMO_PROVIDER_HELPER="$repo_root/src/awg-mihomo-provider.py" \
    MIHOMO_INSTALLER="$tmp/bin/installer" \
    MIHOMO_UPDATER="$tmp/bin/updater" \
    MIHOMO_BIN="$CASE/mihomo" \
    OPENSSL_BIN="$tmp/bin/openssl" \
    PYTHON_BIN=python3 \
    MOCK_INSTALL_LOG="$CASE/install.log" \
    MOCK_UPDATE_LOG="$CASE/update.log" \
    MOCK_UPDATE_FAIL="${MOCK_UPDATE_FAIL:-0}" \
    bash "$repo_root/src/awg-mihomo-configure" init "$CASE/init.env"
}

echo "=== standard provider init ==="
prepare_case standard
write_init standard 'https://subscription.example/profile.yaml'
out="$(run_init)"
grep -Fqx 'MIHOMO_INITIALIZED=1' <<<"$out"
grep -Fqx 'MIHOMO_PROVIDER_PROFILE=standard' <<<"$out"
grep -Fqx 'MIHOMO_HWID_GENERATED=0' <<<"$out"
grep -Fqx 'MIHOMO_NODE_COUNT=2' <<<"$out"
grep -Fqx 'args=--cache-only --mode auto' "$CASE/update.log"
grep -Fqx 'profile=standard' "$CASE/update.log"
grep -Fqx 'suffix=' "$CASE/update.log"
grep -Fqx 'has_hwid=no' "$CASE/update.log"
if grep -Fq '0123456789abcdef' <<<"$out"; then
  echo 'FAIL: HWID leaked in init output' >&2
  exit 1
fi

echo "=== existing initialization is protected ==="
if run_init >"$CASE/out" 2>"$CASE/err"; then
  echo 'FAIL: second init unexpectedly succeeded' >&2
  exit 1
fi
grep -Fq 'already initialized' "$CASE/err"

echo "=== Remnawave/Citadel generates one stable HWID ==="
prepare_case remnawave
write_init remnawave 'https://subscription.example/token'
out="$(run_init)"
grep -Fqx 'MIHOMO_PROVIDER_PROFILE=remnawave' <<<"$out"
grep -Fqx 'MIHOMO_HWID_GENERATED=1' <<<"$out"
grep -Fqx 'profile=remnawave' "$CASE/update.log"
grep -Fqx 'suffix=mihomo' "$CASE/update.log"
grep -Fqx 'has_hwid=yes' "$CASE/update.log"
sudo grep -Fqx 'MIHOMO_PROVIDER_HWID=0123456789abcdef0123456789abcdef' "$CASE/etc/provider.env"
if grep -Fq '0123456789abcdef' <<<"$out"; then
  echo 'FAIL: generated HWID leaked in init output' >&2
  exit 1
fi

echo "=== existing HWID is preserved instead of regenerated ==="
prepare_case existing-hwid
write_init remnawave 'https://subscription.example/token' 'existing-hwid-12345678'
out="$(run_init)"
grep -Fqx 'MIHOMO_HWID_GENERATED=0' <<<"$out"
sudo grep -Fqx 'MIHOMO_PROVIDER_HWID=existing-hwid-12345678' "$CASE/etc/provider.env"

echo "=== URL already ending in /mihomo is not doubled ==="
prepare_case suffix
write_init remnawave 'https://subscription.example/token/mihomo'
run_init >/dev/null
grep -Fqx 'suffix=' "$CASE/update.log"

echo "=== failed bootstrap rolls back provider state ==="
prepare_case failure
write_init standard 'https://broken.example/profile'
if MOCK_UPDATE_FAIL=1 run_init >"$CASE/out" 2>"$CASE/err"; then
  echo 'FAIL: failed bootstrap init unexpectedly succeeded' >&2
  exit 1
fi
sudo test ! -e "$CASE/etc/provider.env"
sudo test ! -e "$CASE/state/providers/subscription.yaml"
grep -Fq 'previous provider state restored' "$CASE/err"

echo "=== init refuses active Mihomo datapath ==="
prepare_case active
write_init standard 'https://subscription.example/profile'
printf '%s\n' mihomo >"$CASE/transport"
if run_init >"$CASE/out" 2>"$CASE/err"; then
  echo 'FAIL: init while Mihomo active unexpectedly succeeded' >&2
  exit 1
fi
grep -Fq 'active transport' "$CASE/err"

echo "mihomo onboarding: OK"
