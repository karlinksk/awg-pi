#!/usr/bin/env bash
# One privileged action: install tested shadow observer, run a benchmark,
# then schedule bounded 72h observation with automatic stop.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Run with sudo" >&2; exit 2; }
D="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
bash "$D/install-shadow.sh" --run-once
bash "$D/start-bounded-observation.sh" 72
echo "AUTO_SMART_OBSERVATION_DEPLOYED=YES"
echo "AUTO_SMART_AUTOSWITCH=DISABLED"
