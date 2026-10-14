#!/usr/bin/env bash
# Update ONLY the non-mutating Mihomo Hot Pool shadow probe, preserving timer state.
# Never starts a probe or changes live Mihomo/AWG/MikroTik, routes, or subscriptions.
set -Eeuo pipefail

BASE=/home/karlinks/awg-hot-pool-shadow
SERVICE=awg-mihomo-hot-pool.service
TIMER=awg-mihomo-hot-pool.timer
BACKUP=""
TOUCHED=0
WAS_ENABLED=0
TIMER_STOPPED=0

[[ "$(id -u)" -eq 0 ]] || { echo "HOT_POOL_APPLY=REQUIRES_SUDO"; exit 2; }
[[ -f "$BASE/awg-mihomo-hot-pool.py" && -f "$BASE/test_hot_pool.py" ]] || exit 2
[[ "$(systemctl is-enabled "$SERVICE" 2>/dev/null || true)" == "static" ]] || {
  echo "HOT_POOL_APPLY=SERVICE_STATE_UNEXPECTED"; exit 3;
}
case "$(systemctl is-enabled "$TIMER" 2>/dev/null || true)" in
  enabled) WAS_ENABLED=1 ;;
  disabled) WAS_ENABLED=0 ;;
  *) echo "HOT_POOL_APPLY=TIMER_STATE_UNEXPECTED"; exit 3 ;;
esac

/usr/bin/python3 -B "$BASE/test_hot_pool.py" -q
/usr/bin/python3 -B "$BASE/test_network_gate_contract.py" -q
/usr/bin/python3 -B -c "import ast,pathlib;ast.parse(pathlib.Path('$BASE/awg-mihomo-hot-pool.py').read_text())"
/usr/bin/systemd-analyze verify "$BASE/$SERVICE" "$BASE/$TIMER"

rollback() {
  local rc="$1"
  trap - EXIT INT TERM
  if [[ "$rc" -ne 0 && "$TOUCHED" -eq 1 && -n "$BACKUP" ]]; then
    /usr/bin/install -m 0755 "$BACKUP/executable" /usr/local/sbin/awg-mihomo-hot-pool || true
    /usr/bin/install -m 0644 "$BACKUP/service" "/etc/systemd/system/$SERVICE" || true
    /usr/bin/install -m 0644 "$BACKUP/timer" "/etc/systemd/system/$TIMER" || true
    /usr/bin/systemctl daemon-reload || true
    echo "HOT_POOL_APPLY=ROLLED_BACK"
  fi
  if [[ "$TIMER_STOPPED" -eq 1 && "$WAS_ENABLED" -eq 1 ]]; then
    /usr/bin/systemctl enable --now "$TIMER" || true
  fi
  exit "$rc"
}
trap 'rollback $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

BACKUP="/run/awg-pbr/hot-pool-backup/four-ready-$(date +%Y%m%d-%H%M%S)"
/usr/bin/install -d -m 0700 "$BACKUP"
/usr/bin/cp -p /usr/local/sbin/awg-mihomo-hot-pool "$BACKUP/executable"
/usr/bin/cp -p "/etc/systemd/system/$SERVICE" "$BACKUP/service"
/usr/bin/cp -p "/etc/systemd/system/$TIMER" "$BACKUP/timer"

# First suppress future automatic triggers; do NOT kill a running probe.
if [[ "$WAS_ENABLED" -eq 1 ]]; then
  /usr/bin/systemctl disable --now "$TIMER"
  TIMER_STOPPED=1
fi
if [[ "$(systemctl is-active "$SERVICE" 2>/dev/null || true)" != "inactive" ]]; then
  echo "HOT_POOL_APPLY=REFUSED_PROBE_RUNNING"
  exit 3
fi

TOUCHED=1
/usr/bin/bash "$BASE/install-shadow.sh"
/usr/bin/cmp -s "$BASE/awg-mihomo-hot-pool.py" /usr/local/sbin/awg-mihomo-hot-pool
[[ "$(systemctl is-enabled "$TIMER" 2>/dev/null || true)" == "disabled" ]]
[[ "$(systemctl is-active "$SERVICE" 2>/dev/null || true)" == "inactive" ]]

# Restore original enabled/disabled state; no one-shot scan is started here.
if [[ "$WAS_ENABLED" -eq 1 ]]; then
  /usr/bin/systemctl enable --now "$TIMER"
  TIMER_STOPPED=0
  [[ "$(systemctl is-active "$TIMER")" == "active" ]]
fi
TOUCHED=0
echo "HOT_POOL_RETENTION_APPLY=PASS"\necho "HOT_POOL_4READY_APPLY=PASS"
echo "HOT_POOL_LIVE_SELECTOR=UNCHANGED"
echo "HOT_POOL_TIMER=$([[ "$WAS_ENABLED" -eq 1 ]] && echo ENABLED || echo DISABLED)"
echo "HOT_POOL_BACKUP=$BACKUP"
/usr/local/sbin/awg-mihomo-hot-pool status