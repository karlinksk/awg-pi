#!/usr/bin/env bash
set -Eeuo pipefail

grep -Fq 'AWG_PI_VERSION="1.3.0"' install.sh
grep -Fq 'ACTIVATE_TRANSIT_AFTER_INSTALL=0' install.sh
grep -Fq '[[ "$EXISTING_VERSION" == 1.1.0 && "$MODE_PREEXISTED" == 0 ]]' install.sh
grep -Fq 'ACTIVATE_TRANSIT_AFTER_INSTALL=1' install.sh
grep -Fq 'AUTO_TRANSIT="${AWG_PI_UPGRADE_TRANSIT:-}"' install.sh
grep -Fq 'AWG_PI_UPGRADE_TRANSIT=0|1' install.sh
grep -Fq 'AWG_PI_UPGRADE_TRANSIT="$transit_choice"' src/awg-update
grep -Fq 'MIHOMO_INSTALLER=/usr/local/sbin/awg-mihomo-install' src/awg-update
grep -Fq '"$MIHOMO_INSTALLER" status || true' src/awg-update
grep -Fq '"$MIHOMO_INSTALLER" ensure' src/awg-update
grep -Fq 'mihomo)' src/awg-update
grep -Fq 'Использование: awg-update [--yes] {status|gateway|core|mihomo|all}' src/awg-update
grep -Fq '"$ROUTE_CLI" mode transit' install.sh
grep -Fq '"$ROUTE_CLI" mode selective' install.sh
grep -Fq 'TRANSPORT_FILE="$PBR_DIR/transport"' install.sh
grep -Fq "printf '%s\\n' unconfigured >\"\$TRANSPORT_FILE\"" install.sh
grep -Fq 'FIRST_RUN_CLI="/usr/local/sbin/awg-first-run"' install.sh
grep -Fq '"$FIRST_RUN_CLI" wizard' install.sh
grep -Fq 'Active transport не настроен. Это допустимое recovery-состояние' install.sh

# Installed version is public metadata and must be readable without sudo.
grep -Fq 'chmod 644 /etc/awg-pbr/version' install.sh
if grep -Fq 'chmod 600 /etc/awg-pbr/version' install.sh; then
  echo 'FAIL: version file is not world-readable' >&2
  exit 1
fi

# Interactive confirmations must tolerate CR/whitespace from SSH terminals and
# accept common English/Russian affirmative forms.
confirm_parser="$(awk '/^confirm_yes\(\)\{/{capture=1} capture{print} capture && /^}$/{exit}' install.sh)"
eval "$confirm_parser"
cr="$(printf '\r')"
for answer in y Y yes Yes YES д Д да Да ДА "y${cr}" ' y ' "да${cr}"; do
  confirm_yes "$answer" || { echo "FAIL: affirmative confirmation rejected: [$answer]" >&2; exit 1; }
done
for answer in n N no No NO нет Нет '' '   '; do
  if confirm_yes "$answer"; then
    echo "FAIL: negative/empty confirmation accepted: [$answer]" >&2
    exit 1
  fi
done

# Fresh installs stage in Selective + unconfigured, configure/recover the
# first transport, then choose Operating Mode explicitly.
grep -Fq "printf '%s\\n' selective >\"\$MODE_FILE\"" install.sh
grep -Fq 'log "[11a/12] First transport wizard"' install.sh
grep -Fq 'log "[11b/12] Operating Mode selection"' install.sh
grep -Fq '2) MikroTik Transit / Backup VPN — transport DOWN/not-ready => FAIL-CLOSED/LOCKDOWN' install.sh
grep -Fq 'elif (( ACTIVATE_TRANSIT_AFTER_INSTALL == 1 )); then' install.sh

# Existing v1.2+ mode and v1.3 transport state are preserved during upgrade.
grep -Fq '[[ -f "$MODE_FILE" ]] || printf' install.sh
grep -Fq 'if [[ ! -f "$TRANSPORT_FILE" ]]; then' install.sh
grep -Fq 'Миграция legacy state: существующий AWG backend принят как active transport.' install.sh

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
  'usr/local/sbin/awg-first-run' \
  'usr/local/sbin/awg-selection' \
  'usr/local/sbin/awg-selection-monitor' \
  'usr/local/sbin/awg-mihomo-node-policy' \
  'usr/local/sbin/awg-traffic' \
  'usr/local/sbin/awg-mihomo-config' \
  'usr/local/sbin/awg-mihomo-update' \
  'usr/local/sbin/awg-mihomo-install' \
  'usr/local/sbin/awg-mihomo-prepare' \
  'usr/local/sbin/awg-mihomo-configure' \
  'etc/systemd/system/awg-mihomo.service' \
  'etc/systemd/system/awg-mihomo-update.service' \
  'etc/systemd/system/awg-mihomo-update.timer' \
  'etc/systemd/system/awg-selection-monitor.service' \
  'etc/systemd/system/awg-traffic.service' \
  'var/lib/awg-pbr/traffic'
do
  grep -Fq "$needle" src/awg-update
done

grep -Fq 'rm -rf /etc/awg-pbr /var/lib/awg-pbr/mihomo /var/lib/awg-pbr/traffic /usr/local/lib/awg-pi' src/awg-update
grep -Fq 'systemctl stop \' src/awg-update
grep -Fq 'awg-mihomo-update.timer \' src/awg-update
grep -Fq 'awg-mihomo.service \' src/awg-update

echo "v1.3 upgrade/rollback policy: OK"

grep -Fq 'install_project_helper src/awg-mihomo-node-policy "$MIHOMO_NODE_POLICY_CLI"' install.sh
grep -Fq 'install_project_helper src/awg-traffic "$TRAFFIC_CLI"' install.sh
grep -Fq 'install_project_unit units/awg-traffic.service /etc/systemd/system/awg-traffic.service' install.sh
grep -Fq 'systemctl restart awg-traffic.service' install.sh
