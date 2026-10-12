#!/usr/bin/env bash
# Stage19: single operator command. Bootstrap media dependencies as non-root
# IMMEDIATELY BEFORE the already-audited sudo one-shot.
# No persistent installs, no changes to production routes or transport.
set -Eeuo pipefail
umask 077
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1 GIT_OPTIONAL_LOCKS=0

[[ "$(id -u)" -ne 0 ]] || { echo "RUN_WRAPPER_WITHOUT_SUDO"; exit 11; }
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
RAM=/dev/shm/awg-stage15
BOOTSTRAP="$ROOT/scripts/awg-media-runtime-ram.sh"
RUNNER="$ROOT/scripts/awg-stage19-run-once.sh"
NODE_SHA=fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5
YTDLP_SHA=1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6

[[ -f "$BOOTSTRAP" && ! -L "$BOOTSTRAP" &&
   -f "$RUNNER" && ! -L "$RUNNER" ]] ||
    { echo "AUDITED_SOURCE_MISSING"; exit 12; }
[[ "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)" == feature/service-aware-smart-gate &&
   -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] ||
    { echo "AUDITED_SOURCE_MODIFIED"; exit 13; }
# Refuse partial or symlinked RAM state rather than deleting an unrelated
# tree or trusting unverified executable bytes.
if [[ -e "$RAM" || -L "$RAM" ]]; then
    [[ -d "$RAM" && ! -L "$RAM" && -d "$RAM/bin" && ! -L "$RAM/bin" ]] ||
        { echo "RAM_RUNTIME_PARTIAL_REFUSED"; exit 14; }
    echo "RAM_RUNTIME_RECHECK"
else
    echo "RAM_RUNTIME_BOOTSTRAP"
    bash "$BOOTSTRAP"
fi
for item in node yt-dlp; do
    [[ -f "$RAM/bin/$item" && ! -L "$RAM/bin/$item" ]] ||
        { echo "RAM_RUNTIME_FILE_INVALID"; exit 15; }
done
[[ "$("$RAM/bin/node" --version)" == v22.16.0 ]] ||
    { echo "RAM_NODE_VERSION_INVALID"; exit 16; }
[[ "$(sha256sum "$RAM/bin/node" | cut -d' ' -f1)" == "$NODE_SHA" ]] ||
    { echo "RAM_NODE_SHA256_INVALID"; exit 17; }
[[ "$(sha256sum "$RAM/bin/yt-dlp" | cut -d' ' -f1)" == "$YTDLP_SHA" ]] ||
    { echo "RAM_YTDLP_SHA256_INVALID"; exit 18; }
echo "STAGE19_MEDIA_RUNTIME_VERIFIED"
echo "STAGE19_ROOT_ONE_SHOT_STARTING"
# The existing driver still verifies both hashes and performs its ordinary
# protected-provider, routing, sandbox and postflight-cleanup checks.
exec sudo bash "$RUNNER"
