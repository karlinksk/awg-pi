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
: "${MOCK_CURL_LOG:?}"
: "${MOCK_PROVIDER_SOURCE:?}"
while (($#)); do
  case "$1" in
    -o)
      out="$2"; shift 2 ;;
    --interface)
      printf 'interface=%s\n' "$2" >>"$MOCK_CURL_LOG"; shift 2 ;;
    -H)
      printf 'header=%s\n' "$2" >>"$MOCK_CURL_LOG"; shift 2 ;;
    *)
      shift ;;
  esac
done
[[ -n "$out" ]]
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
  MOCK_SERVICE_ACTIVE="${MOCK_SERVICE_ACTIVE:-0}" \
    bash "$repo_root/src/awg-mihomo-update"
}

echo "=== provider first update ==="
: >"$tmp/curl.log"; : >"$tmp/systemctl.log"; : >"$tmp/prepare.log"
out="$(run_update)"
grep -Fqx 'MIHOMO_PROVIDER=UPDATED' <<<"$out"
cmp -s "$tmp/fixture.yaml" "$tmp/state/providers/live.yaml"
grep -Fqx 'interface=awg0' "$tmp/curl.log"
grep -Fqx 'header=x-hwid: test-hwid' "$tmp/curl.log"
grep -Fqx prepare "$tmp/prepare.log"

echo "=== provider unchanged ==="
: >"$tmp/prepare.log"
out="$(run_update)"
grep -Fqx 'MIHOMO_PROVIDER=UNCHANGED' <<<"$out"
grep -Fqx prepare "$tmp/prepare.log"

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

echo "=== installer keeps Mihomo passive by default ==="
if grep -Eq 'systemctl[[:space:]]+(enable|start|restart).*awg-mihomo' "$repo_root/install.sh"; then
  echo 'FAIL: installer activates Mihomo without explicit configuration' >&2
  exit 1
fi
grep -Fq 'install_project_helper src/awg-mihomo-config' "$repo_root/install.sh"
grep -Fq 'install_project_unit units/awg-mihomo.service' "$repo_root/install.sh"

echo "mihomo runtime helpers: OK"
