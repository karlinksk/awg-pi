#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
printf '%s\n' awg >"$tmp/transport"
printf '%s\n' transit >"$tmp/mode"
printf '%s\n' '45.86.66.170' >"$tmp/expected-egress"
: >"$tmp/preflight.log"
: >"$tmp/awg.active"

cat >"$tmp/env" <<'EOF'
VPN_IF=awg0
HANDSHAKE_MAX_AGE=180
EOF

cat >"$tmp/bin/ip" <<'MOCK'
#!/usr/bin/env bash
case "$*" in
  "link show awg0"|"link show mihomo0") exit 0 ;;
  *) exit 1 ;;
esac
MOCK

cat >"$tmp/bin/awg" <<'MOCK'
#!/usr/bin/env bash
[[ "$*" == "show awg0 latest-handshakes" ]] || exit 1
[[ -e "${MOCK_AWG_ACTIVE_FILE:?}" ]] || exit 1
echo 'peer 1000'
MOCK

cat >"$tmp/bin/date" <<'MOCK'
#!/usr/bin/env bash
echo 1100
MOCK

cat >"$tmp/bin/curl" <<'MOCK'
#!/usr/bin/env bash
case "$*" in
  *127.0.0.1:9090/version*)
    [[ "${MOCK_MIHOMO_HEALTH:-up}" == up ]] || exit 1
    echo '{}'
    ;;
  *api.ipify.org*)
    [[ "${MOCK_MIHOMO_HEALTH:-up}" == up ]] || exit 1
    echo '45.86.66.170'
    ;;
  *)
    exit 1
    ;;
esac
MOCK

cat >"$tmp/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"${MOCK_SYSTEMCTL_LOG:?}"
case "$*" in
  "is-active --quiet awg-mihomo.service")
    [[ -e "${MOCK_MIHOMO_ACTIVE_FILE:?}" ]]
    ;;
  "is-active --quiet awg-pbr-health.service")
    exit 0
    ;;
  "start awg-mihomo.service")
    : >"${MOCK_MIHOMO_ACTIVE_FILE:?}"
    ;;
  "stop awg-mihomo.service")
    rm -f "${MOCK_MIHOMO_ACTIVE_FILE:?}"
    ;;
  "start awg-quick@awg0.service")
    : >"${MOCK_AWG_ACTIVE_FILE:?}"
    ;;
  "enable awg-quick@awg0.service"|"enable awg-mihomo.service"|"stop awg-pbr-health.service"|"restart awg-pbr-health.service")
    exit 0
    ;;
  *)
    echo "unexpected systemctl: $*" >&2
    exit 1
    ;;
esac
MOCK

cat >"$tmp/bin/awg-route" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"${MOCK_ROUTE_LOG:?}"
[[ "$*" == reload ]] || exit 2
if [[ "${MOCK_RELOAD_FAIL_ONCE:-0}" == 1 && ! -e "${MOCK_RELOAD_FAIL_MARK:?}" ]]; then
  : >"${MOCK_RELOAD_FAIL_MARK}"
  exit 1
fi
exit 0
MOCK

cat >"$tmp/bin/preflight" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
target="$(cat "${AWG_TRANSPORT_FILE:?}")"
printf '%s\n' "$target" >>"${MOCK_PREFLIGHT_LOG:?}"
[[ "${MOCK_PREFLIGHT_FAIL:-0}" != 1 ]]
MOCK

chmod +x "$tmp/bin/"*

run_select(){
  local target="$1"
  sudo env \
    AWG_ENV_FILE="$tmp/env" \
    AWG_COMMON_FILE="$repo_root/src/awg-common" \
    AWG_MODE_FILE="$tmp/mode" \
    AWG_TRANSPORT_FILE="$tmp/transport" \
    AWG_TRANSIT_PREFLIGHT="$tmp/bin/preflight" \
    MIHOMO_EXPECTED_EGRESS_IP_FILE="$tmp/expected-egress" \
    IP_BIN="$tmp/bin/ip" AWG_BIN="$tmp/bin/awg" DATE_BIN="$tmp/bin/date" CURL_BIN="$tmp/bin/curl" \
    SYSTEMCTL_BIN="$tmp/bin/systemctl" AWG_ROUTE_BIN="$tmp/bin/awg-route" SLEEP_BIN=/bin/true \
    AWG_LOCK_FILE="$tmp/maintenance.lock" \
    MOCK_SYSTEMCTL_LOG="$tmp/systemctl.log" MOCK_ROUTE_LOG="$tmp/route.log" \
    MOCK_MIHOMO_ACTIVE_FILE="$tmp/mihomo.active" \
    MOCK_AWG_ACTIVE_FILE="$tmp/awg.active" \
    MOCK_MIHOMO_HEALTH="${MOCK_MIHOMO_HEALTH:-up}" \
    MOCK_PREFLIGHT_LOG="$tmp/preflight.log" \
    MOCK_PREFLIGHT_FAIL="${MOCK_PREFLIGHT_FAIL:-0}" \
    MOCK_RELOAD_FAIL_ONCE="${MOCK_RELOAD_FAIL_ONCE:-0}" \
    MOCK_RELOAD_FAIL_MARK="$tmp/reload-failed-once" \
    bash "$repo_root/src/awg-transport" select "$target"
}

echo "=== AWG -> Mihomo ==="
: >"$tmp/systemctl.log"; : >"$tmp/route.log"; rm -f "$tmp/mihomo.active" "$tmp/reload-failed-once"
out="$(run_select mihomo)"
grep -Fqx mihomo "$tmp/preflight.log"
sudo grep -Fqx mihomo "$tmp/transport"
grep -Fqx 'start awg-mihomo.service' "$tmp/systemctl.log"
grep -Fqx 'enable awg-mihomo.service' "$tmp/systemctl.log"
grep -Fqx reload "$tmp/route.log"
grep -Fqx 'Transport ID: mihomo' <<<"$out"
[[ "$(sudo stat -c '%a' "$tmp/transport")" == 600 ]]

echo "=== Mihomo -> AWG ==="
: >"$tmp/systemctl.log"; : >"$tmp/route.log"
out="$(run_select awg)"
grep -Fqx awg "$tmp/preflight.log"
sudo grep -Fqx awg "$tmp/transport"
grep -Fqx 'start awg-quick@awg0.service' "$tmp/systemctl.log"
grep -Fqx 'enable awg-quick@awg0.service' "$tmp/systemctl.log"
grep -Fqx 'stop awg-mihomo.service' "$tmp/systemctl.log"
grep -Fqx reload "$tmp/route.log"
grep -Fqx 'Transport ID: awg' <<<"$out"

echo "=== selected AWG self-heals after reboot and enables backend ==="
: >"$tmp/systemctl.log"; : >"$tmp/route.log"; : >"$tmp/preflight.log"
printf '%s\n' awg | sudo tee "$tmp/transport" >/dev/null
sudo chmod 600 "$tmp/transport"
rm -f "$tmp/awg.active"
out="$(run_select awg)"
grep -Fqx 'start awg-quick@awg0.service' "$tmp/systemctl.log"
grep -Fqx 'enable awg-quick@awg0.service' "$tmp/systemctl.log"
grep -Fqx awg "$tmp/preflight.log"
grep -Fqx reload "$tmp/route.log"
grep -Fqx 'Transport ID: awg' <<<"$out"
grep -Fq 'Transport recovered and enabled for boot: AmneziaWG' <<<"$out"
[[ -e "$tmp/awg.active" ]]

echo "=== unhealthy Mihomo leaves state unchanged ==="
: >"$tmp/systemctl.log"; : >"$tmp/route.log"; rm -f "$tmp/mihomo.active"
if MOCK_MIHOMO_HEALTH=down run_select mihomo >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: unhealthy Mihomo transport was selected' >&2
  exit 1
fi
sudo grep -Fqx awg "$tmp/transport"
[[ ! -s "$tmp/route.log" ]]
[[ ! -e "$tmp/mihomo.active" ]]
grep -Fq 'Target transport is unhealthy; state unchanged: mihomo' "$tmp/err"

echo "=== Transit preflight failure leaves state unchanged ==="
: >"$tmp/systemctl.log"; : >"$tmp/route.log"; : >"$tmp/preflight.log"; rm -f "$tmp/mihomo.active"
if MOCK_PREFLIGHT_FAIL=1 run_select mihomo >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: transport was selected despite failed Transit preflight' >&2
  exit 1
fi
sudo grep -Fqx awg "$tmp/transport"
grep -Fqx mihomo "$tmp/preflight.log"
[[ ! -s "$tmp/route.log" ]]
[[ ! -e "$tmp/mihomo.active" ]]
grep -Fqx 'restart awg-pbr-health.service' "$tmp/systemctl.log"
grep -Fq 'Target transport preflight failed; state unchanged: mihomo' "$tmp/err"

echo "=== reload failure rolls back transport ==="
: >"$tmp/systemctl.log"; : >"$tmp/route.log"; rm -f "$tmp/mihomo.active" "$tmp/reload-failed-once"
if MOCK_RELOAD_FAIL_ONCE=1 run_select mihomo >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: switch unexpectedly succeeded after reload failure' >&2
  exit 1
fi
sudo grep -Fqx awg "$tmp/transport"
[[ ! -e "$tmp/mihomo.active" ]]
[[ "$(grep -c '^reload$' "$tmp/route.log")" -eq 2 ]]
grep -Fq 'rollback restored awg' "$tmp/err"

echo "transport switching: OK"
