#!/usr/bin/env bash
set -Eeuo pipefail

grep -Fq 'AWG_PI_VERSION="1.2.0"' install.sh
grep -Fq 'UPGRADE_TO_TRANSIT=0' install.sh
grep -Fq '[[ "$EXISTING_VERSION" == 1.1.0 && "$MODE_PREEXISTED" == 0 ]]' install.sh
grep -Fq 'UPGRADE_TO_TRANSIT=1' install.sh
grep -Fq 'AUTO_TRANSIT="${AWG_PI_UPGRADE_TRANSIT:-}"' install.sh
grep -Fq 'AWG_PI_UPGRADE_TRANSIT=0|1' install.sh
grep -Fq 'AWG_PI_UPGRADE_TRANSIT="$transit_choice"' src/awg-update
grep -Fq '"$ROUTE_CLI" mode transit' install.sh
grep -Fq '"$ROUTE_CLI" mode selective' install.sh
grep -Fq 'RESTORE_VPN_OFF=0' install.sh
grep -Fq 'echo 1 >"$VPN_ENABLED_FILE"' install.sh
grep -Fq 'if (( RESTORE_VPN_OFF == 1 )); then' install.sh
grep -Fq 'echo 0 >"$VPN_ENABLED_FILE"' install.sh

# Fresh installs and legacy systems without a mode file are initialized safely.
grep -Fq "printf '%s\\n' selective >\"\$MODE_FILE\"" install.sh

# Existing v1.2+ mode state is preserved instead of being reset during upgrade.
grep -Fq '[[ -f "$MODE_FILE" ]] || printf' install.sh

echo "v1.2 upgrade mode policy: OK"
