#!/usr/bin/env bash
# Installs a SHADOW-ONLY diagnostic. Does not start services or enable timers.
set -Eeuo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run: sudo bash /home/karlinks/awg-hot-pool-shadow/install-shadow.sh' >&2; exit 2; }
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$source_dir/awg-mihomo-hot-pool.py" && -f "$source_dir/test_hot_pool.py" ]] || exit 2
/usr/bin/python3 -B "$source_dir/test_hot_pool.py" -q
/usr/bin/python3 -m py_compile "$source_dir/awg-mihomo-hot-pool.py"
for unit in awg-mihomo-hot-pool.service awg-mihomo-hot-pool.timer; do
  # "is-enabled --quiet" exits zero for static units on this system.
  # A static inactive oneshot is safe to refresh, but reject anything that
  # might be live or auto-starting. The timer must explicitly be disabled.
  state="$(/bin/systemctl is-enabled "$unit" 2>/dev/null || true)"
  case "$unit:$state" in
    awg-mihomo-hot-pool.service:static|awg-mihomo-hot-pool.service:disabled|awg-mihomo-hot-pool.timer:disabled) ;;
    *) echo "REFUSED: unsafe $unit enabled state=$state" >&2; exit 3 ;;
  esac
  if /bin/systemctl is-active --quiet "$unit"; then
    echo "REFUSED: $unit is running" >&2; exit 3
  fi
done
install -m 0755 "$source_dir/awg-mihomo-hot-pool.py" /usr/local/sbin/awg-mihomo-hot-pool
install -m 0644 "$source_dir/awg-mihomo-hot-pool.service" /etc/systemd/system/awg-mihomo-hot-pool.service
install -m 0644 "$source_dir/awg-mihomo-hot-pool.timer" /etc/systemd/system/awg-mihomo-hot-pool.timer
/bin/systemctl daemon-reload
printf 'HOT_POOL_SHADOW_INSTALL=PASS\nHOT_POOL_TIMER=NOT_ENABLED\nHOT_POOL_LIVE_SELECTOR=UNCHANGED\n'
printf 'NEXT=optional single shadow scan: sudo /usr/local/sbin/awg-mihomo-hot-pool warm\n'