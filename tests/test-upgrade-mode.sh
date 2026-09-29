#!/usr/bin/env bash
set -Eeuo pipefail

grep -Fq 'AWG_PI_VERSION="1.2.0"' install.sh
grep -Fq 'UPGRADE_TO_TRANSIT=0' install.sh
grep -Fq '[[ "$EXISTING_VERSION" == 1.1.0 && "$MODE_PREEXISTED" == 0 ]]' install.sh
grep -Fq 'UPGRADE_TO_TRANSIT=1' install.sh
grep -Fq '"$ROUTE_CLI" mode transit' install.sh
grep -Fq '"$ROUTE_CLI" mode selective' install.sh

# Fresh installs and legacy systems without a mode file are initialized safely.
grep -Fq "printf '%s\\n' selective >\"\$MODE_FILE\"" install.sh

# Existing v1.2+ mode state is preserved instead of being reset during upgrade.
grep -Fq '[[ -f "$MODE_FILE" ]] || printf' install.sh

echo "v1.2 upgrade mode policy: OK"
