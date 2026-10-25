#!/usr/bin/env bash
# Passive, minimal test-Pi deployment. DOES NOT run full installer.
# Does not touch transports, selection monitors, routes, DNS, SSH or MikroTik.
set -Eeuo pipefail
umask 077

[[ ${EUID:-$(id -u)} -eq 0 ]] || {
  echo 'ERROR: run with sudo on the TEST Pi only.' >&2
  exit 2
}
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
files=(
  src/awg-notify.py
  units/awg-notify-flush.service
  units/awg-notify-flush.timer
  units/awg-notify-daily.service
  units/awg-notify-daily.timer
  units/awg-notify-watch.service
  units/awg-notify-watch.timer
  units/awg-notify-boot.service
)
for file in "${files[@]}"; do
  [[ -f "$root/$file" && ! -L "$root/$file" ]] || {
    echo "Missing or symbolic-link input: $file" >&2
    exit 3
  }
done

# Never overwrite live notification state/units during this first isolated test.
targets=(
  /usr/local/sbin/awg-notify
  /etc/systemd/system/awg-notify-flush.service
  /etc/systemd/system/awg-notify-flush.timer
  /etc/systemd/system/awg-notify-daily.service
  /etc/systemd/system/awg-notify-daily.timer
  /etc/systemd/system/awg-notify-watch.service
  /etc/systemd/system/awg-notify-watch.timer
  /etc/systemd/system/awg-notify-boot.service
)
for target in "${targets[@]}"; do
  [[ ! -e "$target" && ! -L "$target" ]] || {
    echo "REFUSE: $target already exists; do not overwrite." >&2
    exit 4
  }
done

# Unit tests are run UNPRIVILEGED before this script. Never run writable
# test code as root. Verify the exact reviewed binaries before installing.
declare -A reviewed_sha=(
  [src/awg-notify.py]=e475f8af8ba4cec8886fe70e2ad9c84a0c2b7f444594bb2966c21f9fe52b3d94
  [units/awg-notify-flush.service]=27a3e37b87f1d97f210346142a7b012a9502abb1de34242853c5f8ea8781d1eb
  [units/awg-notify-flush.timer]=34f6da2b554dbd560dad8ee1170a3d5b8e5dabc13474aff12f9738514d1c51df
  [units/awg-notify-daily.service]=4047d4c1d8d0a72b4422192f04ae221b265767c557109059dd0f6eba6fc84a0a
  [units/awg-notify-daily.timer]=2466cb70bd124e5110c418c7d1abdee82e971629a3581477b9117189dc36124b
  [units/awg-notify-watch.service]=5d74dbe512344795e55f2caf11300ebd7b9516750ce30ca708deec71cc2bc2df
  [units/awg-notify-watch.timer]=032845943eebd221f83b48d807c7a290fb29b9ef7c0c785bbbb9fb44b8144794
  [units/awg-notify-boot.service]=bf991978805100c61c03f3c0a56739a90cb09e8921761900a646e618147a8fd8
)
for file in "${!reviewed_sha[@]}"; do
  actual="$(sha256sum "$root/$file")"
  [[ "${actual%% *}" == "${reviewed_sha[$file]}" ]] || {
    echo "REFUSE: source checksum mismatch: $file" >&2
    exit 5
  }
done
bash -n "$root/scripts/awg-notify-test-install.sh"
echo 'PINNED_SOURCE_PRECHECK=PASS'

installed=()
cleanup_on_error(){
  local rc=$?
  trap - ERR
  for target in "${installed[@]}"; do rm -f -- "$target"; done
  systemctl daemon-reload >/dev/null 2>&1 || true
  echo "NOTIFY_PASSIVE_INSTALL=ROLLED_BACK rc=$rc" >&2
  exit "$rc"
}
trap cleanup_on_error ERR

install -d -o root -g root -m 0700 \
  /etc/awg-pbr/notify /var/lib/awg-pbr/notify
install -o root -g root -m 0755 "$root/src/awg-notify.py" "${targets[0]}"
installed+=("${targets[0]}")
for ((i=1; i<${#files[@]}; i++)); do
  install -o root -g root -m 0644 "$root/${files[i]}" "${targets[i]}"
  installed+=("${targets[i]}")
done

systemctl daemon-reload
systemd-analyze verify "${targets[@]:1}"
for timer in awg-notify-flush.timer awg-notify-daily.timer awg-notify-watch.timer awg-notify-boot.service; do
  if systemctl is-enabled --quiet "$timer" ||
     systemctl is-active --quiet "$timer"; then
    echo "ERROR: timer unexpectedly active/enabled: $timer" >&2
    false
  fi
done
/usr/local/sbin/awg-notify status
trap - ERR
echo 'NOTIFY_PASSIVE_INSTALL=PASS'
echo 'NOTIFY_TIMERS=DISABLED'
echo 'GATEWAY_SERVICE_CHANGES=NONE'
