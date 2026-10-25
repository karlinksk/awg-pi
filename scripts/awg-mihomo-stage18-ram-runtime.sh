#!/usr/bin/env bash
# Pinned Stage18 media toolchain. Prefetch on clean installation, restore in RAM
# on each boot; the shadow probe itself never changes routes or live services.
set -Eeuo pipefail
umask 077
(( EUID == 0 )) || { echo STAGE18_NEEDS_ROOT >&2; exit 2; }
R=/dev/shm/awg-stage18-service-runtime
CACHE=/var/lib/awg-pbr/stage18-runtime
NODE_SHA=fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5
TAR_SHA=eab80cb88f8fda1e65f5e8d0420c9809bdb320b03fd34976ab7161b6e703b910
YT_SHA=1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6
MODE="${1:-boot}"
[[ $# -le 1 && "$MODE" == @(boot|prefetch) ]] || { echo STAGE18_BAD_MODE >&2; exit 2; }

secure_dir() {
  local dir="$1" create="${2:-0}"
  [[ ! -L "$dir" ]] || return 1
  if [[ ! -e "$dir" && "$create" == 1 ]]; then
    install -d -o root -g root -m 0700 "$dir"
  fi
  [[ -d "$dir" && "$(stat -c %u:%a "$dir")" == 0:700 ]]
}
verify_at() {
  local file="$1" digest="$2"
  [[ -f "$file" && ! -L "$file" ]] || return 1
  [[ "$(stat -c %u:%a "$file")" == 0:700 ]] || return 1
  printf '%s  %s\n' "$digest" "$file" | sha256sum -c --status
}
verify() { verify_at "$R/$1" "$2"; }

fetch_node() {
  local dir="$1" tmp extracted
  tmp="$(mktemp "$dir/.node-tar-XXXXXXXX")"
  extracted="$(mktemp "$dir/.node-extracted-XXXXXXXX")"
  curl -qfsSL --retry 2 --connect-timeout 8 --max-time 75 \
    https://nodejs.org/dist/v22.16.0/node-v22.16.0-linux-arm64.tar.xz -o "$tmp" || { rm -f "$tmp" "$extracted"; return 1; }
  printf '%s  %s\n' "$TAR_SHA" "$tmp" | sha256sum -c --status || { rm -f "$tmp" "$extracted"; return 1; }
  tar -xJOf "$tmp" node-v22.16.0-linux-arm64/bin/node >"$extracted" || { rm -f "$tmp" "$extracted"; return 1; }
  chmod 700 "$extracted"
  verify_at "$extracted" "$NODE_SHA" || { rm -f "$tmp" "$extracted"; return 1; }
  [[ ! -L "$dir/node" ]] || { rm -f "$tmp" "$extracted"; return 1; }
  mv -fT -- "$extracted" "$dir/node"
  rm -f "$tmp"
}
fetch_ytdlp() {
  local dir="$1" tmp
  tmp="$(mktemp "$dir/.yt-new-XXXXXXXX")"
  curl -qfsSL --retry 2 --connect-timeout 8 --max-time 75 \
    https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp -o "$tmp" || { rm -f "$tmp"; return 1; }
  chmod 700 "$tmp"
  verify_at "$tmp" "$YT_SHA" || { rm -f "$tmp"; return 1; }
  [[ ! -L "$dir/yt-dlp" ]] || { rm -f "$tmp"; return 1; }
  mv -fT -- "$tmp" "$dir/yt-dlp"
}
copy_verified() {
  local source="$1" dest="$2" digest="$3" tmp
  verify_at "$source" "$digest" || return 1
  [[ ! -L "$dest" ]] || return 1
  tmp="$(mktemp "$R/.cache-copy-XXXXXXXX")"
  cp -- "$source" "$tmp" || { rm -f "$tmp"; return 1; }
  chmod 700 "$tmp"
  verify_at "$tmp" "$digest" || { rm -f "$tmp"; return 1; }
  mv -fT -- "$tmp" "$dest"
}

if [[ "$MODE" == prefetch ]]; then
  secure_dir "$CACHE" 1 || { echo STAGE18_CACHE_UNSAFE >&2; exit 2; }
  verify_at "$CACHE/node" "$NODE_SHA" || fetch_node "$CACHE"
  verify_at "$CACHE/yt-dlp" "$YT_SHA" || fetch_ytdlp "$CACHE"
  verify_at "$CACHE/node" "$NODE_SHA" && verify_at "$CACHE/yt-dlp" "$YT_SHA"
  [[ "$("$CACHE/node" --version)" == v22.16.0 ]]
  [[ "$("$CACHE/yt-dlp" --version)" == 2026.08.19 ]]
  echo STAGE18_CACHE_VERIFIED=YES
  echo PRODUCTION_UNCHANGED=YES
  exit 0
fi

secure_dir "$R" 1 || { echo STAGE18_RAM_UNSAFE >&2; exit 2; }
if ! verify node "$NODE_SHA"; then
  if secure_dir "$CACHE" && verify_at "$CACHE/node" "$NODE_SHA"; then
    copy_verified "$CACHE/node" "$R/node" "$NODE_SHA"
  else
    fetch_node "$R"
  fi
fi
if ! verify yt-dlp "$YT_SHA"; then
  if secure_dir "$CACHE" && verify_at "$CACHE/yt-dlp" "$YT_SHA"; then
    copy_verified "$CACHE/yt-dlp" "$R/yt-dlp" "$YT_SHA"
  else
    fetch_ytdlp "$R"
  fi
fi
verify node "$NODE_SHA" && verify yt-dlp "$YT_SHA"
[[ "$("$R/node" --version)" == v22.16.0 ]]
[[ "$("$R/yt-dlp" --version)" == 2026.08.19 ]]
echo STAGE18_RAM_RUNTIME_VERIFIED=YES
echo PRODUCTION_UNCHANGED=YES
