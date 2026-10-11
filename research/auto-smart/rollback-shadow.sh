#!/usr/bin/env bash
# Restore only AUTO SMART shadow files from a root-owned install backup.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Run as root via sudo" >&2; exit 2; }
[[ "$#" -eq 1 ]] || { echo "Usage: sudo bash $0 /var/backups/awg-pbr/auto-smart/observer-XXXXXXXX" >&2; exit 2; }
B="$1"
case "$B" in
  /var/backups/awg-pbr/auto-smart/observer-*) ;;
  *) echo "Refusing backup outside the allow-listed location" >&2; exit 3 ;;
esac
[[ -d "$B" && ! -L "$B" ]] || { echo "Backup not found" >&2; exit 4; }
[[ "$(stat -c '%U:%G' "$B")" == 'root:root' ]] || { echo "Backup owner mismatch" >&2; exit 4; }
if systemctl is-active --quiet awg-mihomo-smart.service; then
  echo "Wait for the current observer scan to finish" >&2; exit 5
fi
systemctl disable --now awg-mihomo-smart.timer >/dev/null 2>&1 || true
for t in /usr/local/sbin/awg-mihomo-smart /etc/systemd/system/awg-mihomo-smart.service /etc/systemd/system/awg-mihomo-smart.timer; do
  base="$(basename "$t")"
  if [[ -f "$B/.absent-$base" ]]; then
    rm -f -- "$t"
  elif [[ -f "$B/$base" && ! -L "$B/$base" ]]; then
    cp -a -- "$B/$base" "$t"
  else
    echo "Incomplete backup: $base" >&2; exit 6
  fi
done
systemctl daemon-reload
echo "AUTO_SMART_SHADOW_ROLLBACK=COMPLETE"
echo "AUTO_SMART_TIMER=DISABLED"
