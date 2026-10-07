#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/state/providers" "$tmp/etc"

cat >"$tmp/fixture.yaml" <<'YAML'
mixed-port: 7890
proxies:
  - name: Test Node
    type: socks5
    server: 192.0.2.10
    port: 1080
proxy-groups: []
rules: []
YAML
cp "$tmp/fixture.yaml" "$tmp/state/providers/subscription.yaml"

echo "=== Mihomo config renderer ==="
MIHOMO_ENV_FILE="$tmp/missing.env" \
MIHOMO_PROVIDER_FILE="$tmp/state/providers/subscription.yaml" \
MIHOMO_NODE_FILTER='^Test Node$' \
MIHOMO_ENDPOINT_IP='192.0.2.10' \
  bash "$repo_root/src/awg-mihomo-config" >"$tmp/rendered.yaml"
grep -Fqx 'allow-lan: false' "$tmp/rendered.yaml"
grep -Fqx 'bind-address: 127.0.0.1' "$tmp/rendered.yaml"
grep -Fqx '  device: mihomo0' "$tmp/rendered.yaml"
grep -Fqx '  auto-route: false' "$tmp/rendered.yaml"
grep -Fqx '  auto-redirect: false' "$tmp/rendered.yaml"
grep -Fqx "    path: '$tmp/state/providers/subscription.yaml'" "$tmp/rendered.yaml"
grep -Fqx "    filter: '^Test Node$'" "$tmp/rendered.yaml"
grep -Fqx "        - '.server = \"192.0.2.10\"'" "$tmp/rendered.yaml"

cat >"$tmp/bin/curl" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
out=""
path=router
: "${MOCK_CURL_LOG:?}"
: "${MOCK_PROVIDER_SOURCE:?}"
while (($#)); do
  case "$1" in
    -o)
      out="$2"; shift 2 ;;
    --interface)
      path=awg
      printf 'interface=%s\n' "$2" >>"$MOCK_CURL_LOG"; shift 2 ;;
    -x)
      path=mihomo
      printf 'proxy=%s\n' "$2" >>"$MOCK_CURL_LOG"; shift 2 ;;
    -H)
      printf 'header=%s\n' "$2" >>"$MOCK_CURL_LOG"; shift 2 ;;
    *)
      shift ;;
  esac
done
printf 'path=%s\n' "$path" >>"$MOCK_CURL_LOG"
[[ -n "$out" ]]
case " ${MOCK_FAIL_PATHS:-} " in
  *" $path "*) exit 7 ;;
esac
cp "$MOCK_PROVIDER_SOURCE" "$out"
MOCK

cat >"$tmp/bin/mihomo" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$*" == *"-t"* ]]
exit 0
MOCK

cat >"$tmp/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"${MOCK_SYSTEMCTL_LOG:?}"
if [[ "$1" == is-active ]]; then
  [[ "${MOCK_SERVICE_ACTIVE:-0}" == 1 ]]
  exit
fi
exit 0
MOCK

cat >"$tmp/bin/prepare" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
echo prepare >>"${MOCK_PREPARE_LOG:?}"
[[ "${MOCK_PREPARE_FAIL:-0}" != 1 ]]
MOCK

chmod +x "$tmp/bin/"*

cat >"$tmp/provider.env" <<'ENV'
MIHOMO_PROVIDER_URL='https://subscription.example/token'
MIHOMO_PROVIDER_HWID='test-hwid'
MIHOMO_UPDATE_INTERFACE='awg0'
ENV

run_update(){
  MIHOMO_ENV_FILE="$tmp/provider.env" \
  MIHOMO_BIN="$tmp/bin/mihomo" \
  MIHOMO_PROVIDER_FILE="$tmp/state/providers/live.yaml" \
  MIHOMO_PREPARE="$tmp/bin/prepare" \
  CURL_BIN="$tmp/bin/curl" \
  SYSTEMCTL_BIN="$tmp/bin/systemctl" \
  MOCK_PROVIDER_SOURCE="${MOCK_PROVIDER_SOURCE:-$tmp/fixture.yaml}" \
  MOCK_CURL_LOG="$tmp/curl.log" \
  MOCK_SYSTEMCTL_LOG="$tmp/systemctl.log" \
  MOCK_PREPARE_LOG="$tmp/prepare.log" \
  MOCK_PREPARE_FAIL="${MOCK_PREPARE_FAIL:-0}" \
  MOCK_SERVICE_ACTIVE="${MOCK_SERVICE_ACTIVE:-0}" \
  MOCK_FAIL_PATHS="${MOCK_FAIL_PATHS:-}" \
  MIHOMO_LAST_FETCH_FILE="$tmp/state/last-fetch-path" \
  MIHOMO_LAST_FORMAT_FILE="$tmp/state/last-provider-format" \
  MIHOMO_PROVIDER_HELPER="$repo_root/src/awg-mihomo-provider.py" \
  PYTHON_BIN=python3 \
    bash "$repo_root/src/awg-mihomo-update" "$@"
}

echo "=== provider first update ==="
: >"$tmp/curl.log"; : >"$tmp/systemctl.log"; : >"$tmp/prepare.log"
out="$(run_update)"
grep -Fqx 'MIHOMO_PROVIDER=UPDATED' <<<"$out"
grep -Fqx 'MIHOMO_PROVIDER_FORMAT_DETECTED=mihomo' <<<"$out"
grep -Fqx 'MIHOMO_PROVIDER_NODE_COUNT=1' <<<"$out"
grep -Fqx mihomo "$tmp/state/last-provider-format"
grep -Fq 'proxies:' "$tmp/state/providers/live.yaml"
if grep -Eq '^(mixed-port|proxy-groups|rules):' "$tmp/state/providers/live.yaml"; then
  echo 'FAIL: normalized provider retained unrelated full-config sections' >&2
  exit 1
fi
grep -Fqx 'interface=awg0' "$tmp/curl.log"
grep -Fqx 'header=x-hwid: test-hwid' "$tmp/curl.log"
grep -Fqx prepare "$tmp/prepare.log"

echo "=== provider unchanged ==="
: >"$tmp/prepare.log"
out="$(run_update)"
grep -Fqx 'MIHOMO_PROVIDER=UNCHANGED' <<<"$out"
grep -Fqx prepare "$tmp/prepare.log"

echo "=== cache-only bootstrap skips runtime prepare ==="
: >"$tmp/prepare.log"
: >"$tmp/systemctl.log"
out="$(run_update --cache-only --mode awg)"
grep -Fqx 'MIHOMO_RUNTIME=DEFERRED' <<<"$out"
if [[ -s "$tmp/prepare.log" ]]; then
  echo 'FAIL: cache-only update unexpectedly ran runtime prepare' >&2
  exit 1
fi
if grep -q 'restart awg-mihomo.service' "$tmp/systemctl.log"; then
  echo 'FAIL: cache-only update unexpectedly restarted Mihomo' >&2
  exit 1
fi

echo "=== provider direct fetch omits interface ==="
cat >"$tmp/provider.env" <<'ENV'
MIHOMO_PROVIDER_URL='https://subscription.example/token'
MIHOMO_PROVIDER_HWID='test-hwid'
MIHOMO_UPDATE_INTERFACE='direct'
ENV
: >"$tmp/curl.log"
run_update >/dev/null
if grep -q '^interface=' "$tmp/curl.log"; then
  echo 'FAIL: direct update unexpectedly used --interface' >&2
  exit 1
fi

echo "=== generic provider works without HWID ==="
cat >"$tmp/provider.env" <<'ENV'
MIHOMO_PROVIDER_URL='https://subscription.example/profile.yaml'
MIHOMO_UPDATE_INTERFACE='direct'
ENV
: >"$tmp/curl.log"
run_update >/dev/null
if grep -q '^header=x-hwid:' "$tmp/curl.log"; then
  echo 'FAIL: generic provider unexpectedly sent x-hwid' >&2
  exit 1
fi

echo "=== AUTO bootstrap falls back from Mihomo to AWG ==="
cat >"$tmp/provider.env" <<'ENV'
MIHOMO_PROVIDER_URL='https://subscription.example/profile.yaml'
MIHOMO_FETCH_MODE='auto'
MIHOMO_FETCH_ORDER='mihomo awg router'
ENV
: >"$tmp/curl.log"
out="$(MOCK_FAIL_PATHS='mihomo' run_update)"
grep -Fqx 'MIHOMO_FETCH_PATH=awg' <<<"$out"
grep -Fqx awg "$tmp/state/last-fetch-path"
grep -Fq 'proxy=http://127.0.0.1:7890' "$tmp/curl.log"
grep -Fq 'interface=awg0' "$tmp/curl.log"

echo "=== AUTO bootstrap falls back to router/default ==="
: >"$tmp/curl.log"
out="$(MOCK_FAIL_PATHS='mihomo awg' run_update)"
grep -Fqx 'MIHOMO_FETCH_PATH=router' <<<"$out"
grep -Fqx router "$tmp/state/last-fetch-path"
grep -Fq 'path=router' "$tmp/curl.log"

echo "=== local provider import bypasses network ==="
: >"$tmp/curl.log"
out="$(run_update --file "$tmp/fixture.yaml")"
grep -Fqx 'MIHOMO_FETCH_PATH=file' <<<"$out"
grep -Fqx file "$tmp/state/last-fetch-path"
if [[ -s "$tmp/curl.log" ]]; then
  echo 'FAIL: local import unexpectedly used curl' >&2
  exit 1
fi

echo "=== updater normalizes plain VLESS subscription ==="
cat >"$tmp/plain-vless.txt" <<'VLESS'
vless://11111111-1111-1111-1111-111111111111@192.0.2.77:443?encryption=none&security=none&type=tcp#Plain%20VLESS
VLESS
out="$(MOCK_PROVIDER_SOURCE="$tmp/plain-vless.txt" run_update --format auto)"
grep -Fqx 'MIHOMO_PROVIDER_FORMAT_DETECTED=vless' <<<"$out"
grep -Fqx 'MIHOMO_PROVIDER_NODE_COUNT=1' <<<"$out"
grep -Fqx vless "$tmp/state/last-provider-format"
grep -Fq 'name: Plain VLESS' "$tmp/state/providers/live.yaml"
grep -Fq 'server: 192.0.2.77' "$tmp/state/providers/live.yaml"
grep -Fq 'uuid: 11111111-1111-1111-1111-111111111111' "$tmp/state/providers/live.yaml"

echo "=== invalid provider never replaces cache ==="
cp "$tmp/state/providers/live.yaml" "$tmp/before.yaml"
cat >"$tmp/invalid.yaml" <<'YAML'
mode: rule
rules:
  - MATCH,DIRECT
YAML
if MOCK_PROVIDER_SOURCE="$tmp/invalid.yaml" run_update >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: invalid provider was accepted' >&2
  exit 1
fi
cmp -s "$tmp/before.yaml" "$tmp/state/providers/live.yaml"

echo "=== runtime validation failure restores previous provider cache ==="
cp "$tmp/state/providers/live.yaml" "$tmp/before-runtime-fail.yaml"
cp "$tmp/state/last-fetch-path" "$tmp/before-last-fetch"
cp "$tmp/state/last-provider-format" "$tmp/before-last-format"
cat >"$tmp/new-valid.yaml" <<'YAML'
mixed-port: 7890
proxies:
  - name: Different Node
    type: socks5
    server: 192.0.2.20
    port: 1080
proxy-groups: []
rules: []
YAML
: >"$tmp/prepare.log"
if MOCK_PROVIDER_SOURCE="$tmp/new-valid.yaml" MOCK_PREPARE_FAIL=1 run_update >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: provider with failing runtime prepare was accepted' >&2
  exit 1
fi
cmp -s "$tmp/before-runtime-fail.yaml" "$tmp/state/providers/live.yaml"
cmp -s "$tmp/before-last-fetch" "$tmp/state/last-fetch-path"
cmp -s "$tmp/before-last-format" "$tmp/state/last-provider-format"
grep -Fq 'provider cache rolled back' "$tmp/err"
[[ "$(grep -c '^prepare$' "$tmp/prepare.log")" -ge 2 ]]
if find "$tmp/state/providers" -maxdepth 1 -type f -name '.subscription.backup.*' | grep -q .; then
  echo 'FAIL: failed provider update left a backup temp file behind' >&2
  exit 1
fi

echo "=== prepare validates and installs config atomically ==="
cat >"$tmp/bin/render" <<'MOCK'
#!/usr/bin/env bash
cat <<'YAML'
mixed-port: 7890
allow-lan: false
rules:
  - MATCH,DIRECT
YAML
MOCK
chmod +x "$tmp/bin/render"
sudo env \
  MIHOMO_BIN="$tmp/bin/mihomo" \
  MIHOMO_RENDERER="$tmp/bin/render" \
  MIHOMO_CONFIG_FILE="$tmp/etc/config.yaml" \
  MIHOMO_STATE_DIR="$tmp/state" \
  bash "$repo_root/src/awg-mihomo-prepare" >"$tmp/prepare.out"
sudo grep -Fqx 'allow-lan: false' "$tmp/etc/config.yaml"
grep -Fqx 'MIHOMO_CONFIG=UPDATED' "$tmp/prepare.out"

echo "=== installer keeps Mihomo passive unless transport state explicitly selects it ==="
if grep -Eq 'systemctl[[:space:]]+(enable|restart).*awg-mihomo' "$repo_root/install.sh"; then
  echo 'FAIL: installer enables/restarts Mihomo as an implicit default' >&2
  exit 1
fi
grep -Fq 'ACTIVE_TRANSPORT="$(cat "$TRANSPORT_FILE" 2>/dev/null || echo unconfigured)"' "$repo_root/install.sh"
grep -Fq 'systemctl start awg-mihomo.service' "$repo_root/install.sh"
grep -Fq 'install_project_helper src/awg-mihomo-config' "$repo_root/install.sh"
grep -Fq 'install_project_unit units/awg-mihomo.service' "$repo_root/install.sh"
grep -Fqx 'install_project_helper src/awg-mihomo-prepare "$MIHOMO_PREPARE_SCRIPT"' "$repo_root/install.sh"
grep -Fqx 'install_project_helper src/awg-mihomo-configure "$MIHOMO_CONFIGURE_SCRIPT"' "$repo_root/install.sh"
grep -Fqx 'MIHOMO_PREPARE_SCRIPT="/usr/local/sbin/awg-mihomo-prepare"' "$repo_root/install.sh"
grep -Fqx 'MIHOMO_CONFIGURE_SCRIPT="/usr/local/sbin/awg-mihomo-configure"' "$repo_root/install.sh"
if grep -Fq 'MIHOMO_PREPARE_SCRIPT="/usr/local/sbin/awg-mihomo-prepare"\nMIHOMO_CONFIGURE_SCRIPT=' "$repo_root/install.sh"; then
  echo 'FAIL: installer contains a literal \n between Mihomo path variables' >&2
  exit 1
fi
if grep -Fq '\\ninstall_project_helper src/awg-mihomo-configure' "$repo_root/install.sh"; then
  echo 'FAIL: installer contains a literal \\n between Mihomo helpers' >&2
  exit 1
fi

echo "mihomo runtime helpers: OK"
