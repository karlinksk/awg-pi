#!/usr/bin/env bash
# Optional AUTO SMART observer installer. No production VPN policy changes.
set -Eeuo pipefail
umask 077
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
D="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
RUN_ONCE=0
case "${1:-}" in
  "") ;;
  --run-once) RUN_ONCE=1 ;;
  *) echo "Usage: sudo bash $0 [--run-once]" >&2; exit 2 ;;
esac
[[ "$EUID" -eq 0 ]] || { echo "Run as root via sudo" >&2; exit 2; }
[[ -f "$D/SHA256SUMS" ]] || { echo "Missing integrity manifest" >&2; exit 3; }
for f in awg-mihomo-smart test_auto_smart.py test_auto_smart_calibration.py README.md awg-mihomo-smart.service awg-mihomo-smart.timer; do
  [[ -f "$D/$f" && ! -L "$D/$f" ]] || { echo "Missing or linked: $f" >&2; exit 3; }
done
(cd "$D" && sha256sum --check SHA256SUMS)
for x in /usr/bin/python3 /usr/bin/curl /usr/local/bin/mihomo /usr/local/sbin/awg-mihomo-pool; do
  [[ -x "$x" ]] || { echo "Missing dependency $x" >&2; exit 4; }
done
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != root ]]; then
  runuser -u "$SUDO_USER" -- python3 -m unittest discover -s "$D" -p 'test_auto_smart*.py' -q
else
  python3 -m unittest discover -s "$D" -p 'test_auto_smart*.py' -q
fi
if systemctl is-enabled --quiet awg-mihomo-smart.timer; then
  echo "Observer timer already enabled: refusing update" >&2; exit 5
fi
if systemctl is-active --quiet awg-mihomo-smart.service; then
  echo "Observer scan in progress: refusing update" >&2; exit 6
fi
ROOT=/var/backups/awg-pbr/auto-smart
mkdir -p "$ROOT"
chmod 0700 "$ROOT"
BACKUP="$(mktemp -d "$ROOT/observer-XXXXXXXX")"
chmod 0700 "$BACKUP"
for t in /usr/local/sbin/awg-mihomo-smart /etc/systemd/system/awg-mihomo-smart.service /etc/systemd/system/awg-mihomo-smart.timer; do
  base="$(basename "$t")"
  if [[ -e "$t" ]]; then
    [[ ! -L "$t" ]] || { echo "Refusing symlink: $t" >&2; exit 7; }
    cp -a -- "$t" "$BACKUP/$base"
  else
    : > "$BACKUP/.absent-$base"
  fi
done
rollback_needed=1
rollback() {
  rc=$?
  if [[ "$rollback_needed" -eq 1 && "$rc" -ne 0 ]]; then
    echo "SMART install failed; restoring saved observer-only files" >&2
    for t in /usr/local/sbin/awg-mihomo-smart /etc/systemd/system/awg-mihomo-smart.service /etc/systemd/system/awg-mihomo-smart.timer; do
      base="$(basename "$t")"
      if [[ -f "$BACKUP/.absent-$base" ]]; then
        rm -f -- "$t"
      else
        cp -a -- "$BACKUP/$base" "$t"
      fi
    done
    systemctl daemon-reload || true
    systemctl reset-failed awg-mihomo-smart.service || true
  fi
}
trap rollback EXIT
install -o root -g root -m 0755 "$D/awg-mihomo-smart" /usr/local/sbin/awg-mihomo-smart
install -o root -g root -m 0644 "$D/awg-mihomo-smart.service" /etc/systemd/system/awg-mihomo-smart.service
install -o root -g root -m 0644 "$D/awg-mihomo-smart.timer" /etc/systemd/system/awg-mihomo-smart.timer
systemctl daemon-reload
if [[ "$RUN_ONCE" -eq 1 ]]; then
  systemctl start awg-mihomo-smart.service
  /usr/local/sbin/awg-mihomo-smart show --count 10
fi
if systemctl is-enabled --quiet awg-mihomo-smart.timer; then
  echo "Unexpected timer enabled" >&2; exit 8
fi
rollback_needed=0
echo "AUTO_SMART_SHADOW_INSTALLED=YES"
echo "AUTO_SMART_TIMER=DISABLED"
echo "AUTO_SMART_AUTOSWITCH=DISABLED"
echo "AUTO_SMART_BACKUP=$BACKUP"
