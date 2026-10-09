#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'sudo rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/etc" "$tmp/state/providers" "$tmp/old"
printf '%s\n' awg >"$tmp/transport"
printf '%s\n' selective >"$tmp/mode"

cat >"$tmp/input.env" <<'ENV'
MIHOMO_PROVIDER_URL='https://subscription.example/profile'
MIHOMO_NODE_FILTER='^Finland$'
MIHOMO_ENDPOINT_IP='45.86.66.170'
MIHOMO_EXPECTED_EGRESS_IP='198.51.100.77'
MIHOMO_FETCH_MODE='auto'
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
  start|restart)
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
if [[ " $* " == *" --stage-only "* ]]; then
  if [[ "${MOCK_UPDATE_UNCHANGED:-0}" == 1 ]]; then
    rm -f "${MIHOMO_CANDIDATE_FILE:?}" "${MIHOMO_CANDIDATE_FETCH_FILE:?}" "${MIHOMO_CANDIDATE_FORMAT_FILE:?}"
    printf 'MIHOMO_PROVIDER=UNCHANGED\n'
    exit 0
  fi
  mkdir -p "$(dirname "${MIHOMO_CANDIDATE_FILE:?}")"
  cat >"$MIHOMO_CANDIDATE_FILE" <<'YAML'
proxies:
  - name: Current Node
    type: vless
    server: 198.51.100.10
    port: 443
    uuid: 11111111-1111-1111-1111-111111111111
  - name: Best Node
    type: vless
    server: 198.51.100.20
    port: 443
    uuid: 22222222-2222-2222-2222-222222222222
YAML
  printf 'file\n' >"${MIHOMO_CANDIDATE_FETCH_FILE:?}"
  printf 'mihomo\n' >"${MIHOMO_CANDIDATE_FORMAT_FILE:?}"
  printf 'MIHOMO_PROVIDER=STAGED\n'
  exit 0
fi
mkdir -p "$(dirname "${MIHOMO_PROVIDER_FILE:?}")"
printf 'new-provider\n' >"$MIHOMO_PROVIDER_FILE"
printf 'new-config\n' >"${MOCK_CONFIG_FILE:?}"
MOCK

cat >"$tmp/bin/prepare" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'prepared-config\n' >"${MOCK_CONFIG_FILE:?}"
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

cat >"$tmp/bin/pool" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
case "${1:-}" in
  scan|ensure|clear)
    [[ "${MOCK_POOL_SCAN_RC:-0}" == 0 ]] || exit "${MOCK_POOL_SCAN_RC}"
    exit 0
    ;;
  promote)
    exit 0
    ;;
  list)
    target="${2:-}"
    if [[ " $* " == *" --format json "* ]]; then
      if [[ "${MOCK_POOL_CURRENT_HEALTHY:-1}" == 1 ]]; then
        printf '%s\n' '[{"name":"Current Node","healthy":true,"delay_ms":50},{"name":"Best Node","healthy":true,"delay_ms":20}]'
      else
        printf '%s\n' '[{"name":"Best Node","healthy":true,"delay_ms":20}]'
      fi
      exit 0
    fi
    case "$target" in
      candidate) file="${MIHOMO_CANDIDATE_FILE:?}" ;;
      live) file="${MIHOMO_PROVIDER_FILE:?}" ;;
      *) exit 2 ;;
    esac
    python3 "${MOCK_PROVIDER_HELPER:?}" list "$file" --format tsv
    ;;
  best)
    printf '%s\n' 'Best Node'
    ;;
  policy)
    case "${2:-}" in
      get) printf 'all\n' ;;
      status) printf 'MIHOMO_POOL_REGION=all\nEurope only: no\n' ;;
      *) exit 0 ;;
    esac
    ;;
  status)
    printf 'Pool state: ready\n'
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
    AWG_MODE_FILE="$tmp/mode" \
    AWG_LOCK_FILE="$tmp/lock" \
    AWG_FAILOPEN="$tmp/bin/failopen" \
    AWG_TRANSIT_ROUTING="$tmp/bin/transit-routing" \
    AWG_HEALTH_SERVICE="awg-pbr-health.service" \
    MIHOMO_ENV_FILE="$tmp/etc/provider.env" \
    MIHOMO_ENDPOINT_IP_FILE="$tmp/etc/endpoint-ip" \
    MIHOMO_EXPECTED_EGRESS_IP_FILE="$tmp/etc/expected-egress-ip" \
    MIHOMO_NODE_NAME_FILE="$tmp/etc/node-name" \
    MIHOMO_NODE_POLICY_MODE_FILE="$tmp/etc/node-policy.mode" \
    MIHOMO_REMNAWAVE_HWID_FILE="$tmp/etc/remnawave.hwid" \
    MIHOMO_LAST_FETCH_FILE="$tmp/state/last-fetch-path" \
    MIHOMO_LAST_FORMAT_FILE="$tmp/state/last-provider-format" \
    MIHOMO_PROVIDER_FILE="$tmp/state/providers/subscription.yaml" \
    MIHOMO_CANDIDATE_FILE="$tmp/state/providers/candidate.yaml" \
    MIHOMO_CANDIDATE_ENV_FILE="$tmp/state/providers/candidate.env" \
    MIHOMO_CANDIDATE_FETCH_FILE="$tmp/state/candidate-fetch-path" \
    MIHOMO_CANDIDATE_FORMAT_FILE="$tmp/state/candidate-provider-format" \
    MIHOMO_CONFIG_FILE="$tmp/etc/config.yaml" \
    MIHOMO_INSTALLER="$tmp/bin/installer" \
    MIHOMO_UPDATER="$tmp/bin/updater" \
    MIHOMO_PREPARE="$tmp/bin/prepare" \
    MIHOMO_PROVIDER_HELPER="$repo_root/src/awg-mihomo-provider.py" \
    MIHOMO_POOL_CLI="$tmp/bin/pool" \
    PYTHON_BIN=python3 \
    AWG_TRANSPORT_CLI="$tmp/bin/transport" \
    SYSTEMCTL_BIN="$tmp/bin/systemctl" \
    MIHOMO_BIN="$tmp/bin/mihomo" \
    SLEEP_BIN=/bin/true \
    MIHOMO_HEALTH_ATTEMPTS=3 \
    MIHOMO_HEALTH_SLEEP=0 \
    MOCK_UNIT_STATE="$tmp/unit-state" \
    MOCK_SYSTEMCTL_LOG="$tmp/systemctl.log" \
    MOCK_DATAPLANE_LOG="$tmp/dataplane.log" \
    MOCK_INSTALL_LOG="$tmp/install.log" \
    MOCK_UPDATE_LOG="$tmp/update.log" \
    MOCK_UPDATE_FAIL="${MOCK_UPDATE_FAIL:-0}" \
    MOCK_UPDATE_UNCHANGED="${MOCK_UPDATE_UNCHANGED:-0}" \
    MOCK_POOL_CURRENT_HEALTHY="${MOCK_POOL_CURRENT_HEALTHY:-1}" \
    MOCK_POOL_SCAN_RC="${MOCK_POOL_SCAN_RC:-0}" \
    MIHOMO_PERIODIC_REFRESH="${MIHOMO_PERIODIC_REFRESH:-0}" \
    MOCK_CONFIG_FILE="$tmp/etc/config.yaml" \
    MOCK_PROVIDER_HELPER="$repo_root/src/awg-mihomo-provider.py" \
    MOCK_HEALTH="${MOCK_HEALTH:-up}" \
    bash "$repo_root/src/awg-mihomo-configure" "$@"
}

run_configure(){
  run_cli apply "$tmp/input.env"
}

mkdir -p "$tmp/unit-state"
: >"$tmp/systemctl.log"; : >"$tmp/install.log"; : >"$tmp/update.log"; : >"$tmp/dataplane.log"

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
grep -Eq '^update( |$)' "$tmp/update.log"
sudo test -e "$tmp/unit-state/awg-mihomo.service.enabled"
sudo test -e "$tmp/unit-state/awg-mihomo.service.active"
sudo test -e "$tmp/unit-state/awg-mihomo-update.timer.enabled"
sudo test -e "$tmp/unit-state/awg-mihomo-update.timer.active"
grep -Fqx awg "$tmp/transport"
grep -Fqx 'MIHOMO_CONFIGURED=1' <<<"$out"
grep -Fqx 'MIHOMO_HEALTH=healthy' <<<"$out"
grep -Fqx 'ACTIVE_TRANSPORT=awg' <<<"$out"
grep -Fqx 'NEXT=awg-transport select mihomo' <<<"$out"

echo "=== active Mihomo reconfiguration is independent of AWG ==="
sudo sh -c "printf '%s\n' mihomo >'$tmp/transport'; printf '%s\n' selective >'$tmp/mode'"
sudo touch "$tmp/unit-state/awg-mihomo.service.active" "$tmp/unit-state/awg-pbr-health.service.active"
: >"$tmp/systemctl.log"; : >"$tmp/dataplane.log"
out="$(run_configure)"
grep -Fqx 'ACTIVE_TRANSPORT=mihomo' <<<"$out"
grep -Fqx failopen "$tmp/dataplane.log"
grep -Fq 'restart awg-pbr-health.service' "$tmp/systemctl.log"
if grep -Fq 'awg-quick@' "$tmp/systemctl.log"; then
  echo 'FAIL: active Mihomo reconfiguration touched AWG' >&2
  exit 1
fi
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

echo "=== legacy provider URL command stages without changing live ==="
sudo mkdir -p "$tmp/etc"
printf "%s\n" \
  "MIHOMO_PROVIDER_URL='https://old.example/profile'" \
  "MIHOMO_NODE_FILTER='Finland'" \
  "MIHOMO_ENDPOINT_IP='45.86.66.170'" | sudo tee "$tmp/etc/provider.env" >/dev/null
sudo chmod 600 "$tmp/etc/provider.env"
: >"$tmp/update.log"
out="$(run_cli provider-url set "https://new.example/profile")"
sudo grep -Fqx "MIHOMO_PROVIDER_URL='https://old.example/profile'" "$tmp/etc/provider.env"
sudo grep -Fqx "MIHOMO_PROVIDER_URL=https://new.example/profile" "$tmp/state/providers/candidate.env"
grep -Fq "update --stage-only --mode auto" "$tmp/update.log"
grep -Fqx "MIHOMO_PROVIDER_URL=STAGED" <<<"$out"

echo "=== legacy provider URL file stages and keeps secret out of command arguments ==="
printf "%s\n" "MIHOMO_PROVIDER_URL='https://file.example/private-token'" | sudo tee "$tmp/etc/url-input.env" >/dev/null
sudo chmod 600 "$tmp/etc/url-input.env"
: >"$tmp/update.log"
out="$(run_cli provider-url set-file "$tmp/etc/url-input.env")"
sudo grep -Fqx "MIHOMO_PROVIDER_URL='https://old.example/profile'" "$tmp/etc/provider.env"
sudo grep -Fqx "MIHOMO_PROVIDER_URL=https://file.example/private-token" "$tmp/state/providers/candidate.env"
grep -Fq "update --stage-only --mode auto" "$tmp/update.log"
grep -Fqx "MIHOMO_PROVIDER_URL=STAGED" <<<"$out"

echo "=== provider URL file must be trusted root 0600 ==="
sudo chmod 644 "$tmp/etc/url-input.env"
if run_cli provider-url set-file "$tmp/etc/url-input.env" >"$tmp/out" 2>"$tmp/err"; then
  echo "FAIL: insecure provider URL file was accepted" >&2
  exit 1
fi
grep -Fq "root-owned mode 0600" "$tmp/err"
sudo chmod 600 "$tmp/etc/url-input.env"

echo "=== failed URL staging preserves live and previous candidate ==="
sudo cp "$tmp/state/providers/candidate.env" "$tmp/candidate-env.before"
sudo cp "$tmp/state/providers/candidate.yaml" "$tmp/candidate-provider.before"
if MOCK_UPDATE_FAIL=1 run_cli provider-url set "https://broken.example/profile" >"$tmp/out" 2>"$tmp/err"; then
  echo "FAIL: failed provider URL staging was accepted" >&2
  exit 1
fi
sudo grep -Fqx "MIHOMO_PROVIDER_URL='https://old.example/profile'" "$tmp/etc/provider.env"
sudo cmp -s "$tmp/candidate-env.before" "$tmp/state/providers/candidate.env"
sudo cmp -s "$tmp/candidate-provider.before" "$tmp/state/providers/candidate.yaml"

echo "=== explicit provider update path reaches updater ==="
: >"$tmp/update.log"
run_cli provider update awg >/dev/null
grep -Fqx "update --stage-only --mode awg" "$tmp/update.log"

echo "=== legacy local provider import stages instead of replacing live ==="
: >"$tmp/update.log"
out="$(run_cli provider import "$tmp/input.env")"
grep -Fq "update --stage-only --file $tmp/input.env --format auto" "$tmp/update.log"
grep -Fqx 'MIHOMO_PROVIDER_IMPORT=STAGED' <<<"$out"

echo "=== staged URL changes candidate env only ==="
sudo sh -c "printf '%s\n' 'MIHOMO_PROVIDER_URL=https://live.example/token' 'MIHOMO_PROVIDER_FORMAT=auto' >'$tmp/etc/provider.env'"
sudo chmod 600 "$tmp/etc/provider.env"
printf "%s\n" "MIHOMO_PROVIDER_URL='https://candidate.example/private-token'" | sudo tee "$tmp/etc/stage-url.env" >/dev/null
sudo chmod 600 "$tmp/etc/stage-url.env"
: >"$tmp/update.log"
out="$(run_cli provider stage-url-file "$tmp/etc/stage-url.env")"
grep -Fqx 'MIHOMO_PROVIDER_SOURCE=URL_STAGED' <<<"$out"
sudo grep -Fqx 'MIHOMO_PROVIDER_URL=https://live.example/token' "$tmp/etc/provider.env"
sudo grep -Fqx 'MIHOMO_PROVIDER_URL=https://candidate.example/private-token' "$tmp/state/providers/candidate.env"
sudo test -e "$tmp/state/providers/candidate.yaml"
grep -Fq 'update --stage-only --mode auto' "$tmp/update.log"

echo "=== switching Remnawave URL to standard clears inherited suffix/HWID ==="
sudo sh -c "printf '%s\n' \\
  'MIHOMO_PROVIDER_URL=https://citadel.example/token' \\
  'MIHOMO_PROVIDER_PROFILE=remnawave' \\
  'MIHOMO_PROVIDER_FORMAT=auto' \\
  'MIHOMO_PROVIDER_HWID=0123456789abcdef0123456789abcdef' \\
  'MIHOMO_UPDATE_SUFFIX=mihomo' >'$tmp/etc/provider.env'"
sudo chmod 600 "$tmp/etc/provider.env"
sudo sh -c "printf '%s\n' \\
  'MIHOMO_PROVIDER_URL=https://raw.example/subscription.yaml' \\
  'MIHOMO_PROVIDER_PROFILE=standard' >'$tmp/etc/stage-url.env'"
sudo chmod 600 "$tmp/etc/stage-url.env"
: >"$tmp/update.log"
out="$(run_cli provider stage-url-file "$tmp/etc/stage-url.env")"
grep -Fqx 'MIHOMO_PROVIDER_SOURCE=URL_STAGED' <<<"$out"
sudo grep -Fqx 'MIHOMO_PROVIDER_URL=https://citadel.example/token' "$tmp/etc/provider.env"
sudo grep -Fqx 'MIHOMO_PROVIDER_URL=https://raw.example/subscription.yaml' "$tmp/state/providers/candidate.env"
sudo grep -Fqx 'MIHOMO_PROVIDER_PROFILE=standard' "$tmp/state/providers/candidate.env"
if sudo grep -q '^MIHOMO_UPDATE_SUFFIX=' "$tmp/state/providers/candidate.env"; then
  echo 'FAIL: standard candidate inherited Remnawave /mihomo suffix' >&2
  exit 1
fi
if sudo grep -q '^MIHOMO_PROVIDER_HWID=' "$tmp/state/providers/candidate.env"; then
  echo 'FAIL: standard candidate inherited Remnawave HWID' >&2
  exit 1
fi

sudo grep -Fqx '0123456789abcdef0123456789abcdef' "$tmp/etc/remnawave.hwid"

echo "=== switching standard URL to Remnawave creates stable staging metadata ==="
sudo sh -c "printf '%s\n' \\
  'MIHOMO_PROVIDER_URL=https://plain.example/subscription.yaml' \\
  'MIHOMO_PROVIDER_PROFILE=standard' \\
  'MIHOMO_PROVIDER_FORMAT=auto' >'$tmp/etc/provider.env'"
sudo chmod 600 "$tmp/etc/provider.env"
sudo sh -c "printf '%s\n' \\
  'MIHOMO_PROVIDER_URL=https://new-citadel.example/token' \\
  'MIHOMO_PROVIDER_PROFILE=remnawave' >'$tmp/etc/stage-url.env'"
sudo chmod 600 "$tmp/etc/stage-url.env"
: >"$tmp/update.log"
out="$(run_cli provider stage-url-file "$tmp/etc/stage-url.env")"
grep -Fqx 'MIHOMO_PROVIDER_SOURCE=URL_STAGED' <<<"$out"
sudo grep -Fqx 'MIHOMO_PROVIDER_PROFILE=remnawave' "$tmp/state/providers/candidate.env"
sudo grep -Fqx 'MIHOMO_UPDATE_SUFFIX=mihomo' "$tmp/state/providers/candidate.env"
sudo grep -Fqx 'MIHOMO_PROVIDER_HWID=0123456789abcdef0123456789abcdef' "$tmp/state/providers/candidate.env"
sudo grep -Fqx '0123456789abcdef0123456789abcdef' "$tmp/etc/remnawave.hwid"

# Restore the original live source for the existing keep-source regression below.
sudo sh -c "printf '%s\n' \\
  'MIHOMO_PROVIDER_URL=https://live.example/token' \\
  'MIHOMO_PROVIDER_PROFILE=standard' \\
  'MIHOMO_PROVIDER_FORMAT=auto' >'$tmp/etc/provider.env'"
sudo chmod 600 "$tmp/etc/provider.env"

echo "=== local staged provider can preserve live source URL ==="
printf 'offline-profile\n' >"$tmp/local-provider.txt"
: >"$tmp/update.log"
out="$(run_cli provider stage-file "$tmp/local-provider.txt" keep-source)"
grep -Fqx 'MIHOMO_PROVIDER_SOURCE=keep-source' <<<"$out"
sudo grep -Fqx 'MIHOMO_PROVIDER_URL=https://live.example/token' "$tmp/state/providers/candidate.env"
grep -Fq "update --stage-only --file $tmp/local-provider.txt" "$tmp/update.log"

echo "=== local-only staged provider removes network source ==="
: >"$tmp/update.log"
out="$(run_cli provider stage-file "$tmp/local-provider.txt" local-only)"
grep -Fqx 'MIHOMO_PROVIDER_SOURCE=local-only' <<<"$out"
if sudo grep -q '^MIHOMO_PROVIDER_URL=' "$tmp/state/providers/candidate.env"; then
  echo 'FAIL: local-only candidate retained provider URL' >&2
  exit 1
fi
if sudo grep -q '^MIHOMO_UPDATE_SUFFIX=' "$tmp/state/providers/candidate.env"; then
  echo 'FAIL: local-only candidate retained URL suffix' >&2
  exit 1
fi

echo "=== failed local staging preserves previous candidate ==="
sudo cp "$tmp/state/providers/candidate.env" "$tmp/candidate-env.before"
sudo cp "$tmp/state/providers/candidate.yaml" "$tmp/candidate-provider.before"
if MOCK_UPDATE_FAIL=1 run_cli provider stage-file "$tmp/local-provider.txt" local-only >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: failed local staging unexpectedly succeeded' >&2
  exit 1
fi
sudo cmp -s "$tmp/candidate-env.before" "$tmp/state/providers/candidate.env"
sudo cmp -s "$tmp/candidate-provider.before" "$tmp/state/providers/candidate.yaml"

echo "=== provider format change is staged, not live ==="
sudo sh -c "printf '%s\n' 'MIHOMO_PROVIDER_URL=https://file.example/private-token' 'MIHOMO_PROVIDER_FORMAT=auto' >'$tmp/etc/provider.env'"
sudo chmod 600 "$tmp/etc/provider.env"
: >"$tmp/update.log"
out="$(run_cli provider format set vless)"
sudo grep -Fqx 'MIHOMO_PROVIDER_FORMAT=auto' "$tmp/etc/provider.env"
sudo grep -Fqx 'MIHOMO_PROVIDER_FORMAT=vless' "$tmp/state/providers/candidate.env"
grep -Fq 'update --stage-only --mode auto' "$tmp/update.log"
grep -Fqx 'MIHOMO_PROVIDER_FORMAT=vless-STAGED' <<<"$out"

echo "=== failed provider format staging preserves live and prior candidate ==="
sudo cp "$tmp/state/providers/candidate.env" "$tmp/candidate-env.before"
sudo cp "$tmp/state/providers/candidate.yaml" "$tmp/candidate-provider.before"
if MOCK_UPDATE_FAIL=1 run_cli provider format set base64 >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: failed provider format staging was accepted' >&2
  exit 1
fi
sudo grep -Fqx 'MIHOMO_PROVIDER_FORMAT=auto' "$tmp/etc/provider.env"
sudo cmp -s "$tmp/candidate-env.before" "$tmp/state/providers/candidate.env"
sudo cmp -s "$tmp/candidate-provider.before" "$tmp/state/providers/candidate.yaml"

echo "=== staged candidate list/prepare/commit is atomic ==="
sudo sh -c "cat >'$tmp/state/providers/candidate.yaml' <<'YAML'
proxies:
  - name: Candidate Finland
    type: vless
    server: 45.86.66.171
    port: 443
    uuid: 11111111-1111-1111-1111-111111111111
YAML"
sudo sh -c "printf '%s\n' 'MIHOMO_PROVIDER_URL=https://candidate.example/token' 'MIHOMO_PROVIDER_FORMAT=auto' >'$tmp/state/providers/candidate.env'"
sudo sh -c "printf '%s\n' file >'$tmp/state/candidate-fetch-path'; printf '%s\n' mihomo >'$tmp/state/candidate-provider-format'"
sudo chmod 600 "$tmp/state/providers/candidate.yaml" "$tmp/state/providers/candidate.env" "$tmp/state/candidate-fetch-path" "$tmp/state/candidate-provider-format"
out="$(run_cli provider candidate list)"
grep -Fq $'Candidate Finland\tvless\t45.86.66.171:443' <<<"$out"
out="$(run_cli provider candidate prepare 'Candidate Finland')"
grep -Fq '45.86.66.171' <<<"$out"
sudo sh -c "printf '%s\n' awg >'$tmp/transport'"
out="$(run_cli provider candidate commit-auto 'Candidate Finland')"
grep -Fqx 'MIHOMO_PROVIDER=COMMITTED' <<<"$out"
grep -Fqx 'MIHOMO_HEALTH=healthy' <<<"$out"
grep -Fqx 'ACTIVE_TRANSPORT=awg' <<<"$out"
sudo grep -Fq 'name: Candidate Finland' "$tmp/state/providers/subscription.yaml"
sudo grep -Fqx '45.86.66.171' "$tmp/etc/endpoint-ip"
sudo grep -Fqx 'Candidate Finland' "$tmp/etc/node-name"
sudo grep -Fq 'MIHOMO_PROVIDER_URL=https://candidate.example/token' "$tmp/etc/provider.env"
sudo test ! -e "$tmp/state/providers/candidate.yaml"
sudo test ! -e "$tmp/state/providers/candidate.env"

echo "=== failed candidate commit restores live and preserves candidate ==="
sudo cp "$tmp/state/providers/subscription.yaml" "$tmp/live-provider.before"
sudo cp "$tmp/etc/provider.env" "$tmp/live-env.before"
sudo cp "$tmp/etc/endpoint-ip" "$tmp/live-endpoint.before"
sudo sh -c "cat >'$tmp/state/providers/candidate.yaml' <<'YAML'
proxies:
  - name: Broken Candidate
    type: vless
    server: 203.0.113.88
    port: 443
    uuid: 22222222-2222-2222-2222-222222222222
YAML"
sudo sh -c "printf '%s\n' 'MIHOMO_PROVIDER_URL=https://broken-candidate.example/token' >'$tmp/state/providers/candidate.env'"
sudo chmod 600 "$tmp/state/providers/candidate.yaml" "$tmp/state/providers/candidate.env"
if MOCK_HEALTH=down run_cli provider candidate commit 'Broken Candidate' 203.0.113.88 >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: unhealthy candidate commit succeeded' >&2
  exit 1
fi
sudo cmp -s "$tmp/live-provider.before" "$tmp/state/providers/subscription.yaml"
sudo cmp -s "$tmp/live-env.before" "$tmp/etc/provider.env"
sudo cmp -s "$tmp/live-endpoint.before" "$tmp/etc/endpoint-ip"
sudo test -e "$tmp/state/providers/candidate.yaml"
grep -Fq 'candidate preserved' "$tmp/err"
grep -Fq 'Mihomo health-check failed after 3 attempts.' "$tmp/err"

echo "=== periodic auto-refresh keeps the current healthy node and promotes safely ==="
sudo sh -c "cat >'$tmp/state/providers/subscription.yaml' <<'YAML'
proxies:
  - name: Current Node
    type: vless
    server: 198.51.100.9
    port: 443
    uuid: 99999999-9999-9999-9999-999999999999
YAML"
sudo sh -c "printf '%s\n' 'MIHOMO_PROVIDER_URL=https://live.example/subscription.yaml' 'MIHOMO_PROVIDER_FORMAT=auto' >'$tmp/etc/provider.env'"
sudo sh -c "printf '%s\n' 'Current Node' >'$tmp/etc/node-name'; printf '%s\n' '198.51.100.9' >'$tmp/etc/endpoint-ip'; printf '%s\n' manual >'$tmp/etc/node-policy.mode'; printf '%s\n' old-config >'$tmp/etc/config.yaml'"
sudo chmod 600 "$tmp/state/providers/subscription.yaml" "$tmp/etc/provider.env" "$tmp/etc/node-name" "$tmp/etc/endpoint-ip" "$tmp/etc/node-policy.mode" "$tmp/etc/config.yaml"
sudo rm -f "$tmp/state/providers/candidate.env"
sudo touch "$tmp/unit-state/awg-mihomo-update.timer.enabled" "$tmp/unit-state/awg-mihomo-update.timer.active"
: >"$tmp/systemctl.log"
out="$(MIHOMO_PERIODIC_REFRESH=1 MOCK_POOL_CURRENT_HEALTHY=1 run_cli provider auto-refresh)"
grep -Fqx 'MIHOMO_PROVIDER_AUTO_REASON=keep-current' <<<"$out"
grep -Fqx 'MIHOMO_PROVIDER_AUTO_REFRESH=APPLIED' <<<"$out"
sudo grep -Fqx 'Current Node' "$tmp/etc/node-name"
sudo grep -Fq 'name: Current Node' "$tmp/state/providers/subscription.yaml"
sudo test ! -e "$tmp/state/providers/candidate.yaml"
if grep -Fq 'stop awg-mihomo-update.timer awg-mihomo-update.service' "$tmp/systemctl.log"; then
  echo 'FAIL: periodic refresh tried to stop its own systemd service' >&2
  exit 1
fi

echo "=== MANUAL keeps a changed provider staged when the current node disappeared ==="
sudo cp "$tmp/state/providers/subscription.yaml" "$tmp/live.before-auto-manual"
sudo sh -c "printf '%s\n' 'Missing Node' >'$tmp/etc/node-name'; printf '%s\n' manual >'$tmp/etc/node-policy.mode'"
sudo rm -f "$tmp/state/providers/candidate.env"
out="$(MIHOMO_PERIODIC_REFRESH=1 MOCK_POOL_CURRENT_HEALTHY=0 run_cli provider auto-refresh)"
grep -Fqx 'MIHOMO_PROVIDER_AUTO_REFRESH=STAGED_CURRENT_UNAVAILABLE' <<<"$out"
grep -Fqx 'LIVE_PROVIDER=UNCHANGED' <<<"$out"
sudo cmp -s "$tmp/live.before-auto-manual" "$tmp/state/providers/subscription.yaml"
sudo test -e "$tmp/state/providers/candidate.yaml"

echo "=== FIXED never promotes a provider update unattended ==="
sudo sh -c "printf '%s\n' 'Current Node' >'$tmp/etc/node-name'; printf '%s\n' fixed >'$tmp/etc/node-policy.mode'"
sudo cp "$tmp/state/providers/subscription.yaml" "$tmp/live.before-auto-fixed"
sudo rm -f "$tmp/state/providers/candidate.env"
out="$(MIHOMO_PERIODIC_REFRESH=1 MOCK_POOL_CURRENT_HEALTHY=1 run_cli provider auto-refresh)"
grep -Fqx 'MIHOMO_PROVIDER_AUTO_REFRESH=STAGED_FIXED_REVIEW' <<<"$out"
grep -Fqx 'LIVE_PROVIDER=UNCHANGED' <<<"$out"
sudo cmp -s "$tmp/live.before-auto-fixed" "$tmp/state/providers/subscription.yaml"

echo "=== AUTO chooses the best allowed candidate when the current node disappeared ==="
sudo sh -c "printf '%s\n' 'Missing Node' >'$tmp/etc/node-name'; printf '%s\n' auto >'$tmp/etc/node-policy.mode'"
sudo rm -f "$tmp/state/providers/candidate.env"
out="$(MIHOMO_PERIODIC_REFRESH=1 MOCK_POOL_CURRENT_HEALTHY=0 run_cli provider auto-refresh)"
grep -Fqx 'MIHOMO_PROVIDER_AUTO_REASON=auto-best' <<<"$out"
grep -Fqx 'MIHOMO_PROVIDER_AUTO_TARGET=Best Node' <<<"$out"
grep -Fqx 'MIHOMO_PROVIDER_AUTO_REFRESH=APPLIED' <<<"$out"
sudo grep -Fqx 'Best Node' "$tmp/etc/node-name"
sudo grep -Fq 'name: Best Node' "$tmp/state/providers/subscription.yaml"

echo "=== no healthy candidate never replaces live ==="
sudo cp "$tmp/state/providers/subscription.yaml" "$tmp/live.before-no-healthy"
sudo rm -f "$tmp/state/providers/candidate.env"
out="$(MIHOMO_PERIODIC_REFRESH=1 MOCK_POOL_SCAN_RC=1 run_cli provider auto-refresh)"
grep -Fqx 'MIHOMO_PROVIDER_AUTO_REFRESH=STAGED_NO_HEALTHY_NODE' <<<"$out"
grep -Fqx 'LIVE_PROVIDER=UNCHANGED' <<<"$out"
sudo cmp -s "$tmp/live.before-no-healthy" "$tmp/state/providers/subscription.yaml"

echo "=== unchanged provider is a no-op ==="
out="$(MIHOMO_PERIODIC_REFRESH=1 MOCK_UPDATE_UNCHANGED=1 run_cli provider auto-refresh)"
grep -Fqx 'MIHOMO_PROVIDER_AUTO_REFRESH=UNCHANGED' <<<"$out"

echo "=== periodic updater unit runs the safe orchestrator with a long timeout ==="
grep -Fq 'Environment=MIHOMO_PERIODIC_REFRESH=1' "$repo_root/units/awg-mihomo-update.service"
grep -Fq 'ExecStart=/usr/local/sbin/awg-mihomo-configure provider auto-refresh' "$repo_root/units/awg-mihomo-update.service"
grep -Fq 'TimeoutStartSec=30min' "$repo_root/units/awg-mihomo-update.service"

echo "mihomo configure transaction: OK"
