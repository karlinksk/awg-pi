#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/etc" "$tmp/state/providers" "$tmp/unit-state"
printf '%s\n' awg >"$tmp/transport"
printf '%s\n' selective >"$tmp/mode"

cat >"$tmp/state/providers/subscription.yaml" <<'YAML'
proxies:
  - name: "🇫🇮 Finland"
    type: vless
    server: 45.86.66.170
    port: 443
    uuid: SECRET-UUID
  - name: "DE (backup)+1"
    type: vless
    server: 203.0.113.7
    port: 443
    uuid: OTHER-SECRET
YAML

cat >"$tmp/etc/provider.env" <<'ENV'
MIHOMO_PROVIDER_URL='https://subscription.example/token'
MIHOMO_NODE_FILTER='^Old$'
MIHOMO_ENDPOINT_IP='192.0.2.99'
MIHOMO_EXPECTED_EGRESS_IP='198.51.100.99'
ENV
chmod 600 "$tmp/etc/provider.env"
printf '%s\n' 192.0.2.99 >"$tmp/etc/endpoint-ip"
printf '%s\n' 198.51.100.99 >"$tmp/etc/expected-egress-ip"
printf '%s\n' Old >"$tmp/etc/node-name"
printf '%s\n' old-config >"$tmp/etc/config.yaml"

cat >"$tmp/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
state="${MOCK_UNIT_STATE:?}"
printf '%s\n' "$*" >>"${MOCK_SYSTEMCTL_LOG:?}"
unit="awg-mihomo.service"
case "${1:-}" in
  is-enabled)
    if [[ "${2:-}" == --quiet ]]; then unit="${3:-$unit}"; else unit="${2:-$unit}"; fi
    [[ -e "$state/$unit.enabled" ]]
    ;;
  is-active)
    if [[ "${2:-}" == --quiet ]]; then unit="${3:-$unit}"; else unit="${2:-$unit}"; fi
    [[ -e "$state/$unit.active" ]]
    ;;
  stop)
    shift
    for u in "$@"; do rm -f "$state/$u.active"; done
    ;;
  start|restart)
    u="${2:-$unit}"; : >"$state/$u.active"
    ;;
  enable)
    if [[ "${2:-}" == --now ]]; then
      u="${3:-$unit}"; : >"$state/$u.enabled"; : >"$state/$u.active"
    else
      u="${2:-$unit}"; : >"$state/$u.enabled"
    fi
    ;;
  disable)
    u="${2:-$unit}"; rm -f "$state/$u.enabled"
    ;;
  daemon-reload)
    ;;
  *)
    echo "unexpected systemctl: $*" >&2
    exit 2
    ;;
esac
MOCK

cat >"$tmp/bin/transport" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
case "$*" in
  "check mihomo")
    [[ "${MOCK_HEALTH:-up}" == up ]]
    ;;
  *)
    exit 2
    ;;
esac
MOCK

cat >"$tmp/bin/prepare" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "${MOCK_PREPARE_FAIL:-0}" != 1 ]] || exit 1
printf 'generated-config\n' >"${MOCK_CONFIG_FILE:?}"
MOCK

cat >"$tmp/bin/failopen" <<'MOCK'
#!/usr/bin/env bash
printf 'failopen\n' >>"${MOCK_DATAPLANE_LOG:?}"
MOCK

cat >"$tmp/bin/transit-routing" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'transit:%s\n' "$*" >>"${MOCK_DATAPLANE_LOG:?}"
[[ "$1" == disable ]]
MOCK

cat >"$tmp/bin/mihomo" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK

cat >"$tmp/bin/pool" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
case "${1:-}" in
  ensure)
    exit 0
    ;;
  list)
    python3 "${MOCK_PROVIDER_HELPER:?}" list "${MIHOMO_PROVIDER_FILE:?}" --format tsv
    ;;
  clear|promote)
    exit 0
    ;;
  *)
    exit 2
    ;;
esac
MOCK

chmod +x "$tmp/bin/"*

run_cli(){
  sudo env     AWG_COMMON_FILE="$repo_root/src/awg-common"     AWG_MODE_FILE="$tmp/mode"     AWG_TRANSPORT_FILE="$tmp/transport"     AWG_LOCK_FILE="$tmp/lock"     AWG_FAILOPEN="$tmp/bin/failopen"     AWG_TRANSIT_ROUTING="$tmp/bin/transit-routing"     AWG_HEALTH_SERVICE="awg-pbr-health.service"     MIHOMO_ENV_FILE="$tmp/etc/provider.env"     MIHOMO_ENDPOINT_IP_FILE="$tmp/etc/endpoint-ip"     MIHOMO_EXPECTED_EGRESS_IP_FILE="$tmp/etc/expected-egress-ip"     MIHOMO_NODE_NAME_FILE="$tmp/etc/node-name"     MIHOMO_PROVIDER_FILE="$tmp/state/providers/subscription.yaml"     MIHOMO_CONFIG_FILE="$tmp/etc/config.yaml"     MIHOMO_PROVIDER_HELPER="$repo_root/src/awg-mihomo-provider.py"     MIHOMO_POOL_CLI="$tmp/bin/pool"     MOCK_PROVIDER_HELPER="$repo_root/src/awg-mihomo-provider.py"     MIHOMO_PREPARE="$tmp/bin/prepare"     AWG_TRANSPORT_CLI="$tmp/bin/transport"     SYSTEMCTL_BIN="$tmp/bin/systemctl"     MIHOMO_BIN="$tmp/bin/mihomo"     PYTHON_BIN=python3     SLEEP_BIN=/bin/true     MOCK_UNIT_STATE="$tmp/unit-state"     MOCK_SYSTEMCTL_LOG="$tmp/systemctl.log"     MOCK_DATAPLANE_LOG="$tmp/dataplane.log"     MOCK_CONFIG_FILE="$tmp/etc/config.yaml"     MOCK_HEALTH="${MOCK_HEALTH:-up}"     MOCK_PREPARE_FAIL="${MOCK_PREPARE_FAIL:-0}"     bash "$repo_root/src/awg-mihomo-configure" "$@"
}

echo "=== safe node list ==="
out="$(run_cli node list)"
grep -Fq $'🇫🇮 Finland\tvless\t45.86.66.170:443' <<<"$out"
if grep -Fq 'SECRET-UUID' <<<"$out"; then
  echo 'FAIL: node list leaked proxy credential' >&2
  exit 1
fi

echo "=== node prepare uses gateway-wide DIRECT invariant ==="
out="$(run_cli node prepare '🇫🇮 Finland')"
grep -Fq 'Resolved IPv4 endpoints:' <<<"$out"
grep -Fq '  - 45.86.66.170' <<<"$out"
grep -Fq 'Gateway DIRECT policy required: yes' <<<"$out"
grep -Fq 'does not require a per-endpoint MikroTik rule' <<<"$out"
if grep -Fq -- '--direct-confirmed' <<<"$out"; then
  echo 'FAIL: node prepare still asks for per-endpoint confirmation' >&2
  exit 1
fi

echo "=== endpoint must match current node metadata ==="
if run_cli node select '🇫🇮 Finland' 203.0.113.55 >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: unrelated endpoint was accepted' >&2
  exit 1
fi
grep -Fq 'not one of the current IPv4 addresses' "$tmp/err"

echo "=== successful node selection while AWG is active ==="
: >"$tmp/systemctl.log"; : >"$tmp/dataplane.log"
out="$(run_cli node select '🇫🇮 Finland' 45.86.66.170)"
sudo grep -Fqx 45.86.66.170 "$tmp/etc/endpoint-ip"
sudo grep -Fqx '🇫🇮 Finland' "$tmp/etc/node-name"
sudo test ! -e "$tmp/etc/expected-egress-ip"
safe_env="$(sudo bash -c 'source "$1"; printf "%s\n%s\n" "$MIHOMO_NODE_FILTER" "$MIHOMO_ENDPOINT_IP"' _ "$tmp/etc/provider.env")"
grep -Fqx '^🇫🇮 Finland$' <<<"$safe_env"
grep -Fqx '45.86.66.170' <<<"$safe_env"
grep -Fqx 'DIRECT_POLICY=gateway-wide' <<<"$out"
grep -Fqx 'MIHOMO_HEALTH=healthy' <<<"$out"
grep -Fqx 'ACTIVE_TRANSPORT=awg' <<<"$out"
grep -Fqx 'NEXT=awg-transport select mihomo' <<<"$out"
[[ ! -s "$tmp/dataplane.log" ]]

echo "=== failed new node restores previous selected node ==="
sudo cp "$tmp/etc/provider.env" "$tmp/etc/provider.before"
sudo cp "$tmp/etc/endpoint-ip" "$tmp/etc/endpoint.before"
sudo cp "$tmp/etc/node-name" "$tmp/etc/node.before"
sudo cp "$tmp/etc/config.yaml" "$tmp/etc/config.before"
if MOCK_HEALTH=down run_cli node select 'DE (backup)+1' 203.0.113.7 >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: unhealthy node selection succeeded' >&2
  exit 1
fi
sudo cmp -s "$tmp/etc/provider.before" "$tmp/etc/provider.env"
sudo cmp -s "$tmp/etc/endpoint.before" "$tmp/etc/endpoint-ip"
sudo cmp -s "$tmp/etc/node.before" "$tmp/etc/node-name"
sudo cmp -s "$tmp/etc/config.before" "$tmp/etc/config.yaml"
grep -Fq 'previous node configuration restored' "$tmp/err"

echo "=== active Mihomo node switch in Selective does not require AWG ==="
sudo sh -c "printf '%s\n' mihomo >'$tmp/transport'; printf '%s\n' selective >'$tmp/mode'"
sudo touch "$tmp/unit-state/awg-mihomo.service.active" "$tmp/unit-state/awg-pbr-health.service.active"
: >"$tmp/systemctl.log"; : >"$tmp/dataplane.log"
out="$(run_cli node select 'DE (backup)+1' 203.0.113.7)"
grep -Fqx 'ACTIVE_TRANSPORT=mihomo' <<<"$out"
grep -Fqx 'DATAPLANE=restored' <<<"$out"
grep -Fqx failopen "$tmp/dataplane.log"
grep -Fq 'restart awg-pbr-health.service' "$tmp/systemctl.log"
if grep -Fq 'awg-quick@' "$tmp/systemctl.log"; then
  echo 'FAIL: active Mihomo node switch touched AWG' >&2
  exit 1
fi

echo "=== active Mihomo node switch in Transit uses fail-closed quiesce ==="
sudo sh -c "printf '%s\n' transit >'$tmp/mode'"
: >"$tmp/systemctl.log"; : >"$tmp/dataplane.log"
out="$(run_cli node select '🇫🇮 Finland' 45.86.66.170)"
grep -Fqx 'ACTIVE_TRANSPORT=mihomo' <<<"$out"
grep -Fqx 'DATAPLANE=restored' <<<"$out"
grep -Fqx 'transit:disable' "$tmp/dataplane.log"
grep -Fq 'restart awg-pbr-health.service' "$tmp/systemctl.log"
if grep -Fq 'awg-quick@' "$tmp/systemctl.log"; then
  echo 'FAIL: Transit Mihomo node switch touched AWG' >&2
  exit 1
fi

echo "=== local-only provider does not enable network update timer ==="
sudo sed -i '/^MIHOMO_PROVIDER_URL=/d' "$tmp/etc/provider.env"
: >"$tmp/systemctl.log"
out="$(run_cli node select 'DE (backup)+1' 203.0.113.7)"
grep -Fqx 'DATAPLANE=restored' <<<"$out"
grep -Fq 'disable awg-mihomo-update.timer' "$tmp/systemctl.log"
if grep -Fq 'enable --now awg-mihomo-update.timer' "$tmp/systemctl.log"; then
  echo 'FAIL: local-only provider enabled a network update timer' >&2
  exit 1
fi

echo "mihomo node selection: OK"
