#!/usr/bin/env bash
set -Eeuo pipefail

grep -Fq 'AWG_PI_VERSION="1.3.0"' install.sh
grep -Fq 'ACTIVATE_TRANSIT_AFTER_INSTALL=1' install.sh
grep -Fq '[[ "$EXISTING_VERSION" == 1.1.0 && "$MODE_PREEXISTED" == 0 ]]' install.sh
grep -Fq 'ACTIVATE_TRANSIT_AFTER_INSTALL=1' install.sh
grep -Fq 'AUTO_TRANSIT="${AWG_PI_UPGRADE_TRANSIT:-}"' install.sh
grep -Fq 'AWG_PI_UPGRADE_TRANSIT=0|1' install.sh
grep -Fq 'AWG_PI_UPGRADE_TRANSIT="$transit_choice"' src/awg-update
grep -Fq '"$ROUTE_CLI" mode transit' install.sh
grep -Fq '"$ROUTE_CLI" mode selective' install.sh
grep -Fq 'RESTORE_VPN_OFF=0' install.sh
grep -Fq 'echo 1 >"$VPN_ENABLED_FILE"' install.sh
grep -Fq 'if (( RESTORE_VPN_OFF == 1 )); then' install.sh
grep -Fq 'echo 0 >"$VPN_ENABLED_FILE"' install.sh

# Fresh installs stage in Selective while AWG is validated, then the default
# post-install transaction activates Transit. Legacy systems without a mode file
# still stage as Selective for v1.1.x compatibility.
grep -Fq "printf '%s\\n' selective >\"\$MODE_FILE\"" install.sh
grep -Fq 'ACTIVATE_TRANSIT_AFTER_INSTALL=1' install.sh
grep -Fq 'if (( ACTIVATE_TRANSIT_AFTER_INSTALL == 1 )); then' install.sh

# Existing v1.2+ mode state is preserved instead of being reset during upgrade.
grep -Fq '[[ -f "$MODE_FILE" ]] || printf' install.sh

# The updater must support direct legacy v1.1 -> newer releases, while
# preserving existing v1.2+ mode state through the installer.
grep -Fq '[[ "$cur" == 1.1.0 ]] && version_gt "$latest" "1.1.0"' src/awg-update
grep -Fq 'v1.1.0 -> $latest: --yes подтверждает post-upgrade Transit preflight/switch.' src/awg-update

# v1.3 rollback must include the complete Mihomo transport state, not only the
# v1.2 AWG files.
for needle in \
  'var/lib/awg-pbr/mihomo' \
  'usr/local/bin/mihomo' \
  'usr/local/sbin/awg-transport' \
  'usr/local/sbin/awg-mihomo-config' \
  'usr/local/sbin/awg-mihomo-update' \
  'usr/local/sbin/awg-mihomo-install' \
  'usr/local/sbin/awg-mihomo-prepare' \
  'usr/local/sbin/awg-mihomo-configure' \
  'etc/systemd/system/awg-mihomo.service' \
  'etc/systemd/system/awg-mihomo-update.service' \
  'etc/systemd/system/awg-mihomo-update.timer'
do
  grep -Fq "$needle" src/awg-update
done

grep -Fq 'rm -rf /etc/awg-pbr /var/lib/awg-pbr/mihomo /usr/local/lib/awg-pi' src/awg-update
grep -Fq 'systemctl stop \' src/awg-update
grep -Fq 'awg-mihomo-update.timer \' src/awg-update
grep -Fq 'awg-mihomo.service \' src/awg-update

echo "v1.3 upgrade/rollback policy: OK"
