#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/etc" "$tmp/state/providers" "$tmp/old"
printf '%s\n' awg >"$tmp/transport"

cat >"$tmp/input.env" <<'ENV'
MIHOMO_PROVIDER_URL='https://subscription.example/profile'
MIHOMO_NODE_FILTER='^Finland$'
MIHOMO_ENDPOINT_IP='45.86.66.170'
MIHOMO_EXPECTED_EGRESS_IP='198.51.100.77'
MIHOMO_UPDATE_INTERFACE='awg0'
ENV

cat >"$tmp/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
state="${MOCK_UNIT_STATE:?}"
log="${MOCK_SYSTEMCTL_LOG:?}"
printf '%s\n' "$*" >>"$log"
unit="${*: -1}"
enabled_file="$state/${unit}.enabled"
active_file="$state/${unit}.active"
case "${1:-}" in
  is-enabled)
    [[ -e "$enabled_file" ]]
    ;;
  is-active)
    if [[ "${2:-}" == --quiet ]]; then
      unit="${3:-}"
    else
      unit="${2:-}"
    fi
    [[ -e "$state/${unit}.active" ]]
    ;;
  enable)
    if [[ "${2:-}" == --now ]]; then
      unit="${3:-}"
      : >"$state/${unit}.enabled"
      : >"$state/${unit}.active"
    else
      unit="${2:-}"
      : >"$state/${unit}.enabled"
    fi
    ;;
  disable)
    rm -f "$enabled_file"
    ;;
  start)
    unit="${2:-}"
    : >"$state/${unit}.active"
    ;;
  stop)
    shift
    for unit in "$@"; do
      rm -f "$state/${unit}.active"
    done
    ;;
  daemon-reload)
    ;;
  *)
    echo "unexpected systemctl: $*" >&2
    exit 2
    ;;
esac
MOCK

cat >"$tmp/bin/installer" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' install >>"${MOCK_INSTALL_LOG:?}"
cat >"${MIHOMO_BIN:?}" <<'BIN'
#!/usr/bin/env bash
echo 'Mihomo Meta v-test'
BIN
chmod 755 "${MIHOMO_BIN}"
MOCK

cat >"$tmp/bin/updater" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'update %s\n' "$*" >>"${MOCK_UPDATE_LOG:?}"
[[ "${MOCK_UPDATE_FAIL:-0}" != 1 ]] || exit 1
mkdir -p "$(dirname "${MIHOMO_PROVIDER_FILE:?}")"
printf 'new-provider\n' >"$MIHOMO_PROVIDER_FILE"
printf 'new-config\n' >"${MOCK_CONFIG_FILE:?}"
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

chmod +x "$tmp/bin/"*

run_cli(){
  sudo env \
    AWG_COMMON_FILE="$repo_root/src/awg-common" \
    AWG_TRANSPORT_FILE="$tmp/transport" \
    AWG_LOCK_FILE="$tmp/lock" \
    MIHOMO_ENV_FILE="$tmp/etc/provider.env" \
    MIHOMO_ENDPOINT_IP_FILE="$tmp/etc/endpoint-ip" \
    MIHOMO_EXPECTED_EGRESS_IP_FILE="$tmp/etc/expected-egress-ip" \
    MIHOMO_LAST_FETCH_FILE="$tmp/state/last-fetch-path" \
    MIHOMO_PROVIDER_FILE="$tmp/state/providers/subscription.yaml" \
    MIHOMO_CONFIG_FILE="$tmp/etc/config.yaml" \
    MIHOMO_INSTALLER="$tmp/bin/installer" \
    MIHOMO_UPDATER="$tmp/bin/updater" \
    AWG_TRANSPORT_CLI="$tmp/bin/transport" \
    SYSTEMCTL_BIN="$tmp/bin/systemctl" \
    MIHOMO_BIN="$tmp/bin/mihomo" \
    SLEEP_BIN=/bin/true \
    MOCK_UNIT_STATE="$tmp/unit-state" \
    MOCK_SYSTEMCTL_LOG="$tmp/systemctl.log" \
    MOCK_INSTALL_LOG="$tmp/install.log" \
    MOCK_UPDATE_LOG="$tmp/update.log" \
    MOCK_UPDATE_FAIL="${MOCK_UPDATE_FAIL:-0}" \
    MOCK_CONFIG_FILE="$tmp/etc/config.yaml" \
    MOCK_HEALTH="${MOCK_HEALTH:-up}" \
    bash "$repo_root/src/awg-mihomo-configure" "$@"
}

run_configure(){
  run_cli apply "$tmp/input.env"
}

mkdir -p "$tmp/unit-state"
: >"$tmp/systemctl.log"; : >"$tmp/install.log"; : >"$tmp/update.log"

echo "=== user-owned configure input is rejected ==="
if run_configure >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: user-owned configure input was accepted' >&2
  exit 1
fi
grep -Fq 'root-owned regular file with mode 0600' "$tmp/err"

sudo chown root:root "$tmp/input.env"
sudo chmod 600 "$tmp/input.env"

echo "=== first-time configuration succeeds without switching datapath ==="
out="$(run_configure)"
sudo grep -Fqx "MIHOMO_PROVIDER_URL='https://subscription.example/profile'" "$tmp/etc/provider.env"
sudo grep -Fqx '45.86.66.170' "$tmp/etc/endpoint-ip"
sudo grep -Fqx '198.51.100.77' "$tmp/etc/expected-egress-ip"
[[ "$(sudo stat -c '%a' "$tmp/etc/provider.env")" == 600 ]]
[[ "$(sudo stat -c '%a' "$tmp/etc/endpoint-ip")" == 600 ]]
grep -Fqx install "$tmp/install.log"
grep -Fqx update "$tmp/update.log"
sudo test -e "$tmp/unit-state/awg-mihomo.service.enabled"
sudo test -e "$tmp/unit-state/awg-mihomo.service.active"
sudo test -e "$tmp/unit-state/awg-mihomo-update.timer.enabled"
sudo test -e "$tmp/unit-state/awg-mihomo-update.timer.active"
grep -Fqx awg "$tmp/transport"
grep -Fqx 'MIHOMO_CONFIGURED=1' <<<"$out"
grep -Fqx 'MIHOMO_HEALTH=healthy' <<<"$out"
grep -Fqx 'ACTIVE_TRANSPORT=awg' <<<"$out"
grep -Fqx 'NEXT=awg-transport select mihomo' <<<"$out"

echo "=== active Mihomo cannot be reconfigured ==="
sudo sh -c "printf '%s\n' mihomo >'$tmp/transport'"
if run_configure >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: active Mihomo reconfiguration was accepted' >&2
  exit 1
fi
grep -Fq 'select AWG first' "$tmp/err"
sudo sh -c "printf '%s\n' awg >'$tmp/transport'"

echo "=== health failure restores previous files and unit state ==="
sudo sh -c "printf '%s\n' old-env >'$tmp/etc/provider.env'"
sudo sh -c "printf '%s\n' 203.0.113.9 >'$tmp/etc/endpoint-ip'"
sudo sh -c "printf '%s\n' 203.0.113.10 >'$tmp/etc/expected-egress-ip'"
sudo sh -c "printf '%s\n' old-provider >'$tmp/state/providers/subscription.yaml'"
sudo sh -c "printf '%s\n' old-config >'$tmp/etc/config.yaml'"
sudo chmod 600 "$tmp/etc/provider.env" "$tmp/etc/endpoint-ip" "$tmp/etc/expected-egress-ip" "$tmp/state/providers/subscription.yaml" "$tmp/etc/config.yaml"
sudo rm -rf "$tmp/unit-state"
sudo mkdir -p "$tmp/unit-state"
sudo touch "$tmp/unit-state/awg-mihomo.service.enabled" "$tmp/unit-state/awg-mihomo.service.active"
: >"$tmp/systemctl.log"; : >"$tmp/update.log"
if MOCK_HEALTH=down run_configure >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: unhealthy configured Mihomo was accepted' >&2
  exit 1
fi
sudo grep -Fqx old-env "$tmp/etc/provider.env"
sudo grep -Fqx 203.0.113.9 "$tmp/etc/endpoint-ip"
sudo grep -Fqx 203.0.113.10 "$tmp/etc/expected-egress-ip"
sudo grep -Fqx old-provider "$tmp/state/providers/subscription.yaml"
sudo grep -Fqx old-config "$tmp/etc/config.yaml"
sudo test -e "$tmp/unit-state/awg-mihomo.service.enabled"
sudo test -e "$tmp/unit-state/awg-mihomo.service.active"
sudo test ! -e "$tmp/unit-state/awg-mihomo-update.timer.enabled"
sudo test ! -e "$tmp/unit-state/awg-mihomo-update.timer.active"
grep -Fq 'previous state restored' "$tmp/err"
grep -Fqx awg "$tmp/transport"

echo "=== provider URL change is transactional ==="
sudo sh -c "cat >'$tmp/etc/provider.env' <<'ENV'
MIHOMO_PROVIDER_URL='https://old.example/profile'
MIHOMO_NODE_FILTER='^Finland
MIHOMO_ENDPOINT_IP='45.86.66.170'
ENV"
sudo chmod 600 "$tmp/etc/provider.env"
: >"$tmp/update.log"
out="$(run_cli provider-url set 'https://new.example/profile')"
sudo grep -Fqx "MIHOMO_PROVIDER_URL=https://new.example/profile" "$tmp/etc/provider.env"
grep -Fqx 'update --mode auto' "$tmp/update.log"
grep -Fqx 'MIHOMO_PROVIDER_URL=UPDATED' <<<"$out"

echo "=== failed provider URL change restores previous value ==="
if MOCK_UPDATE_FAIL=1 run_cli provider-url set 'https://broken.example/profile' >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: failed provider URL update was accepted' >&2
  exit 1
fi
sudo grep -Fq 'old.example\|new.example' "$tmp/etc/provider.env"
if sudo grep -Fq 'broken.example' "$tmp/etc/provider.env"; then
  echo 'FAIL: broken provider URL was not rolled back' >&2
  exit 1
fi
grep -Fq 'previous URL restored' "$tmp/err"

echo "=== explicit provider update path reaches updater ==="
: >"$tmp/update.log"
run_cli provider update awg >/dev/null
grep -Fqx 'update --mode awg' "$tmp/update.log"

echo "=== local provider import reaches updater ==="
: >"$tmp/update.log"
run_cli provider import "$tmp/input.env" >/dev/null
grep -Fqx "update --file $tmp/input.env" "$tmp/update.log"

echo "mihomo configure transaction: OK"
