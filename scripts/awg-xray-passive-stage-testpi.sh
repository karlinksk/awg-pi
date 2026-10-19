#!/usr/bin/env bash
# Stage (but NEVER activate) the guarded Xray executor on the authorized test Pi.
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIVE=/usr/local/sbin
BACKUP_ROOT=/var/backups/awg-gateway
MODE="${1:---check}"

fail(){ printf 'XRAY_STAGE_ERROR=%s\n' "$1" >&2; exit 1; }
[[ "$MODE" == --check || "$MODE" == --stage ]] || fail USAGE_CHECK_OR_STAGE
[[ "${EUID:-$(id -u)}" == 0 ]] || fail ROOT_REQUIRED
[[ "$(hostname)" == awg-upgrade ]] || fail NOT_TEST_PI
[[ " $(hostname -I) " == *" 192.168.112.34 "* ]] || fail WRONG_TEST_ADDRESS
[[ "$(cat /etc/awg-pbr/mode 2>/dev/null)" == transit ]] || fail TRANSIT_ONLY
systemctl is-active --quiet awg-mihomo.service || fail MIHOMO_NOT_ACTIVE
if systemctl is-active --quiet awg-xray-vless.service; then fail XRAY_ALREADY_ACTIVE; fi
[[ ! -e /var/lib/awg-pbr/xray-vless/selected.json ]] || fail XRAY_SELECTION_PREEXISTS
[[ -r /var/lib/awg-pbr/mihomo/providers/subscription.yaml ]] || fail NO_PROVIDER
[[ -x "$LIVE/awg-mihomo-config" && -x "$LIVE/awg-xray-vless" ]] || fail BASE_HELPERS_MISSING
[[ -x /usr/local/bin/awg-xray-vless-core ]] || fail XRAY_CORE_MISSING
[[ -f "$ROOT/src/awg-mihomo-config" && -f "$ROOT/src/awg-xray-live-backend.py" ]] || fail SOURCE_MISSING
[[ "$(git -C "$ROOT" branch --show-current)" == feature/unified-mihomo-xray-nodes-20261019 ]] || fail WRONG_BRANCH
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || fail DIRTY_SOURCE
# Never create any service env overrides or start/restart units here.
systemctl is-enabled --quiet awg-xray-vless.service && fail XRAY_AUTOSTART_UNEXPECTED
# Existing renderer must remain semantically identical with the bridge OFF.
TEMP="$(mktemp -d /tmp/awg-xray-stage-check.XXXXXX)"
chmod 700 "$TEMP"
trap 'rm -rf -- "$TEMP"' EXIT
MIHOMO_XRAY_VLESS_BRIDGE=0 "$LIVE/awg-mihomo-config" > "$TEMP/old.yaml" || fail OLD_RENDER_FAILED
MIHOMO_XRAY_VLESS_BRIDGE=0 bash "$ROOT/src/awg-mihomo-config" > "$TEMP/new.yaml" || fail NEW_RENDER_FAILED
render_equivalent(){
  python3 - "$1" "$2" <<'PY'
import sys
import yaml
try:
    with open(sys.argv[1],encoding="utf-8") as old:
        before=yaml.safe_load(old)
    with open(sys.argv[2],encoding="utf-8") as new:
        after=yaml.safe_load(new)
except Exception:
    raise SystemExit(2)
if not isinstance(before,dict) or before!=after:
    raise SystemExit(1)
PY
}
render_equivalent "$TEMP/old.yaml" "$TEMP/new.yaml" || fail RENDERER_DEFAULT_CHANGED
for file in src/awg-mihomo-config src/awg-mihomo-unified-nodes.py src/awg-xray-activation-transaction.py src/awg-xray-live-backend.py; do
  [[ -s "$ROOT/$file" ]] || fail SOURCE_INCOMPLETE
done
echo XRAY_STAGE_RENDERER_DEFAULT=EQUIVALENT
echo XRAY_STAGE_ACTIVE_MIHOMO=UNCHANGED
if [[ "$MODE" == --check ]]; then
  echo XRAY_STAGE_PREFLIGHT=PASS
  echo XRAY_STAGE_INSTALLED=NO
  exit 0
fi
mkdir -p "$BACKUP_ROOT"
STAMP="$(date +%Y%m%d-%H%M%S)"
SNAP="$(mktemp -d "$BACKUP_ROOT/xray-passive-stage-${STAMP}-XXXXXX")"
chmod 700 "$SNAP"
declare -a TARGETS=(
  awg-mihomo-config
  awg-mihomo-unified-nodes
  awg-xray-activation-transaction
  awg-xray-live-backend
)
declare -a SOURCES=(
  src/awg-mihomo-config
  src/awg-mihomo-unified-nodes.py
  src/awg-xray-activation-transaction.py
  src/awg-xray-live-backend.py
)
# Back up ALL old targets before replacing ANY.
for target in "${TARGETS[@]}"; do
  if [[ -e "$LIVE/$target" ]]; then
    [[ ! -L "$LIVE/$target" && -f "$LIVE/$target" ]] || fail UNSAFE_EXISTING_FILE
    install -m 0700 -o root -g root "$LIVE/$target" "$SNAP/$target"
  else
    : >"$SNAP/$target.absent"
  fi
done
rollback(){
  local n target
  for n in "${!TARGETS[@]}"; do
    target="${TARGETS[$n]}"
    if [[ -f "$SNAP/$target.absent" ]]; then
      rm -f -- "$LIVE/$target"
    elif [[ -f "$SNAP/$target" ]]; then
      install -m 0755 -o root -g root "$SNAP/$target" "$LIVE/$target"
    fi
  done
}
STAGING=1
finish(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && STAGING == 1 )); then
    rollback || true
    echo XRAY_STAGE_ROLLBACK=ATTEMPTED >&2
  fi
  rm -rf -- "$TEMP"
  exit "$rc"
}
trap finish EXIT
for n in "${!TARGETS[@]}"; do
  install -m 0755 -o root -g root "$ROOT/${SOURCES[$n]}" "$LIVE/${TARGETS[$n]}"
done
MIHOMO_XRAY_VLESS_BRIDGE=0 "$LIVE/awg-mihomo-config" > "$TEMP/staged.yaml"
render_equivalent "$TEMP/old.yaml" "$TEMP/staged.yaml" || fail INSTALLED_RENDER_CHANGED
[[ "$(systemctl is-active awg-mihomo.service)" == active ]] || fail MIHOMO_CHANGED
[[ "$(systemctl is-active awg-xray-vless.service)" != active ]] || fail XRAY_CHANGED
STAGING=0
echo XRAY_STAGE_INSTALLED=PASSIVE
echo XRAY_STAGE_SNAPSHOT="$SNAP"
echo XRAY_STAGE_SERVICES_RESTARTED=NO
echo XRAY_STAGE_AUTO_FAILOVER_ENABLED=NO
