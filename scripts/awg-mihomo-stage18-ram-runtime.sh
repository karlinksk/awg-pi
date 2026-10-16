#!/usr/bin/env bash
# Operator-only pinned Stage18 runtime; RAM only, no service/routing changes.
set -Eeuo pipefail
umask 077
(( EUID == 0 )) || { echo STAGE18_NEEDS_ROOT; exit 2; }
R=/dev/shm/awg-stage18-service-runtime
NODE_SHA=fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5
TAR_SHA=eab80cb88f8fda1e65f5e8d0420c9809bdb320b03fd34976ab7161b6e703b910
YT_SHA=1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6
[[ ! -L "$R" ]] || exit 2
if [[ -e "$R" ]]; then
  [[ -d "$R" && "$(stat -c %u:%a "$R")" == 0:700 ]] || exit 2
else
  mkdir -m 700 "$R"
fi
verify() {
  local name="$1" digest="$2"
  local path="$R/$name"
  [[ -f "$path" && ! -L "$path" ]] || return 1
  [[ "$(stat -c %u:%a "$path")" == 0:700 ]] || return 1
  echo "$digest  $path" | sha256sum -c --status
}
if ! verify node "$NODE_SHA"; then
  [[ ! -L "$R/node" ]] || exit 2
  tmp=$(mktemp "$R/.node-tar-XXXXXXXX")
  trap 'rm -f -- "$tmp" "$R/.node-extracted"' EXIT
  curl -qfsSL --retry 2 --connect-timeout 8 --max-time 75 \
    https://nodejs.org/dist/v22.16.0/node-v22.16.0-linux-arm64.tar.xz -o "$tmp"
  echo "$TAR_SHA  $tmp" | sha256sum -c >&2
  tar -xJOf "$tmp" node-v22.16.0-linux-arm64/bin/node > "$R/.node-extracted"
  chmod 700 "$R/.node-extracted"
  echo "$NODE_SHA  $R/.node-extracted" | sha256sum -c >&2
  mv -fT -- "$R/.node-extracted" "$R/node"
  rm -f "$tmp"
  trap - EXIT
fi
if ! verify yt-dlp "$YT_SHA"; then
  [[ ! -L "$R/yt-dlp" ]] || exit 2
  tmp=$(mktemp "$R/.yt-new-XXXXXXXX")
  trap 'rm -f -- "$tmp"' EXIT
  curl -qfsSL --retry 2 --connect-timeout 8 --max-time 75 \
    https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp -o "$tmp"
  chmod 700 "$tmp"
  echo "$YT_SHA  $tmp" | sha256sum -c >&2
  mv -fT -- "$tmp" "$R/yt-dlp"
  trap - EXIT
fi
verify node "$NODE_SHA" && verify yt-dlp "$YT_SHA"
[[ "$("$R/node" --version)" == v22.16.0 ]]
[[ "$("$R/yt-dlp" --version)" == 2026.08.19 ]]
echo STAGE18_RAM_RUNTIME_VERIFIED=YES
echo PRODUCTION_UNCHANGED=YES
