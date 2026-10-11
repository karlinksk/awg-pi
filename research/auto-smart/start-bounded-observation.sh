#!/usr/bin/env bash
# Opt-in 48/72-hour bounded AUTO SMART observation, no VPN switching.
set -Eeuo pipefail
umask 077
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
D="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
[[ "$EUID" -eq 0 ]] || { echo "Run with sudo" >&2; exit 2; }
HOURS="${1:-72}"
case "$HOURS" in 48|72) ;; *) echo "Only 48 or 72 hours supported" >&2; exit 2 ;; esac
[[ -f "$D/SHA256SUMS" ]] || { echo "Missing trusted manifest" >&2; exit 3; }
python3 - <<'PY'
import json,time
from pathlib import Path
p=Path('/run/awg-pbr/mihomo-smart/last.json')
try:
    r=json.loads(p.read_text())
    good=(r.get('version')==2 and r.get('confirmed_count',0)>=1
          and 0 <= time.time()-r.get('timestamp',0) <= 3600
          and r.get('current_at_start')==r.get('current_at_end')
          and r.get('switches_made')==0 and r.get('production_modified') is False)
except (OSError,ValueError,TypeError):
    good=False
if not good:
    raise SystemExit('Recent successful unchanged-node SMART test required before scheduling')
print('AUTO_SMART_PREFLIGHT=RECENT_CONFIRMED_SHADOW_ONLY')
PY
(cd "$D" && sha256sum -c SHA256SUMS)
EXPECTED="$(awk '$2 == "awg-mihomo-smart" {print $1}' "$D/SHA256SUMS")"
[[ -n "$EXPECTED" && "$(sha256sum /usr/local/sbin/awg-mihomo-smart | cut -d' ' -f1)" == "$EXPECTED" ]] || {
  echo "Installed AUTO SMART differs from reviewed source" >&2; exit 4;
}
for unit in awg-mihomo-smart.service awg-mihomo-smart.timer; do
  expected_unit="$(awk -v n="$unit" '$2 == n {print $1}' "$D/SHA256SUMS")"
  live_unit="/etc/systemd/system/$unit"
  [[ -n "$expected_unit" && -f "$live_unit" ]] || {
    echo "Missing reviewed systemd unit: $unit" >&2; exit 4;
  }
  [[ "$(sha256sum "$live_unit" | cut -d' ' -f1)" == "$expected_unit" ]] || {
    echo "Unit differs from reviewed shadow schedule: $unit" >&2; exit 4;
  }
done
[[ "$(systemctl is-active awg-mihomo.service)" == 'active' ]] || {
  echo "Production Mihomo unavailable; refusing schedule" >&2; exit 5;
}
if systemctl is-enabled --quiet awg-mihomo-smart.timer; then
  echo "SMART timer already enabled; refusing duplicate observation" >&2; exit 6
fi
if systemctl is-active --quiet awg-mihomo-smart.service; then
  echo "SMART scan running; wait for completion" >&2; exit 6
fi
STOP_SVC=/etc/systemd/system/awg-mihomo-smart-stop.service
STOP_TMR=/etc/systemd/system/awg-mihomo-smart-stop.timer
[[ ! -e "$STOP_SVC" && ! -e "$STOP_TMR" ]] || {
  echo "Existing stop schedule detected; refusing overwrite" >&2; exit 7;
}
DEADLINE="$(date -d "+$HOURS hours" '+%Y-%m-%d %H:%M:%S')"
systemd-analyze calendar "$DEADLINE" >/dev/null
cancel=1
cleanup() {
  rc=$?
  if [[ "$cancel" -eq 1 && "$rc" -ne 0 ]]; then
    systemctl disable --now awg-mihomo-smart.timer >/dev/null 2>&1 || true
    systemctl disable --now awg-mihomo-smart-stop.timer >/dev/null 2>&1 || true
    rm -f -- "$STOP_SVC" "$STOP_TMR"
    systemctl daemon-reload || true
    echo "SMART_OBSERVATION_START_ROLLBACK=YES" >&2
  fi
}
trap cleanup EXIT
cat > "$STOP_SVC" <<'EOF'
[Unit]
Description=Automatically stop bounded AUTO SMART shadow observation

[Service]
Type=oneshot
ExecStart=/bin/systemctl disable --now awg-mihomo-smart.timer
EOF
cat > "$STOP_TMR" <<EOF
[Unit]
Description=Stop AUTO SMART shadow observation after a bounded window

[Timer]
OnCalendar=$DEADLINE
Persistent=true
AccuracySec=1min
Unit=awg-mihomo-smart-stop.service

[Install]
WantedBy=timers.target
EOF
chmod 0644 "$STOP_SVC" "$STOP_TMR"
systemctl daemon-reload
systemctl enable --now awg-mihomo-smart-stop.timer
systemctl enable --now awg-mihomo-smart.timer
systemctl is-active --quiet awg-mihomo-smart.timer
systemctl is-active --quiet awg-mihomo-smart-stop.timer
cancel=0
echo "AUTO_SMART_OBSERVATION=ENABLED_SHADOW_ONLY"
echo "AUTO_SMART_STOP_LOCAL=$DEADLINE"
echo "AUTO_SMART_WINDOW_HOURS=$HOURS"
echo "AUTO_SMART_AUTOSWITCH=DISABLED"
systemctl list-timers --no-pager awg-mihomo-smart.timer awg-mihomo-smart-stop.timer
