#!/usr/bin/env bash
# Install pinned, checksum-verified Node.js for the entire OS PATH.
# Reuses Stage18's previously verified cache; preserves Debian's /usr/bin/node.
set -Eeuo pipefail
umask 077

PIN_VERSION=v22.16.0
PIN_SHA=fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5
SOURCE=/var/lib/awg-pbr/stage18-runtime/node
RUNTIME_DIR=/usr/local/lib/awg-pi/node
VERSION_DIR="$RUNTIME_DIR/$PIN_VERSION"
BIN="$VERSION_DIR/node"
LINK=/usr/local/bin/node
MODE="${1:-status}"

fail(){ printf 'SYSTEM_NODE_ERROR=%s\n' "$1" >&2; exit 2; }
version_ok(){
  [[ -x "$1" && ! -L "$1" ]] || return 1
  [[ "$("$1" --version 2>/dev/null)" == "$PIN_VERSION" ]] || return 1
  "$1" -e 'if (typeof WebSocket !== "function") process.exit(1)' >/dev/null 2>&1
}
hash_ok(){
  [[ -f "$1" && ! -L "$1" ]] || return 1
  printf '%s  %s\n' "$PIN_SHA" "$1" | sha256sum -c --status
}
path_ok(){
  [[ -L "$LINK" && "$(readlink -- "$LINK")" == "$BIN" ]] || return 1
  hash_ok "$BIN" && version_ok "$BIN"
}
case "$MODE" in
  status)
    if path_ok; then
      echo "SYSTEM_NODE_VERSION=$PIN_VERSION"
      echo 'SYSTEM_NODE_WEBSOCKET=AVAILABLE'
      echo 'SYSTEM_NODE_ORIGIN=STAGE18_PINNED'
      echo 'SYSTEM_NODE_MANAGED=YES'
      exit 0
    fi
    if command -v node >/dev/null 2>&1; then
      printf 'SYSTEM_NODE_CURRENT=%s\n' "$(node --version 2>/dev/null || echo unknown)"
    else
      echo 'SYSTEM_NODE_CURRENT=absent'
    fi
    echo 'SYSTEM_NODE_MANAGED=NO'
    exit 1
    ;;
  apply)
    (( EUID == 0 )) || fail ROOT_REQUIRED
    [[ "${#}" == 1 ]] || fail BAD_ARGUMENTS
    [[ "$(uname -m)" == aarch64 ]] || fail UNSUPPORTED_ARCH
    [[ -r /etc/os-release ]] || fail OS_UNKNOWN
    . /etc/os-release
    [[ "${ID:-}" == debian ]] || fail UNSUPPORTED_OS
    hash_ok "$SOURCE" || fail STAGE18_PINNED_NODE_CACHE_INVALID
    version_ok "$SOURCE" || fail STAGE18_PINNED_NODE_RUNTIME_INVALID
    if path_ok; then
      echo 'SYSTEM_NODE_INSTALL=ALREADY_VERIFIED'
      exit 0
    fi
    # Respect anything not previously managed by this helper.
    if [[ -e "$LINK" || -L "$LINK" ]]; then
      [[ -L "$LINK" ]] || fail UNMANAGED_SYSTEM_NODE_LINK
      current="$(readlink -- "$LINK")"
      [[ "$current" == "$RUNTIME_DIR/"*"/node" ]] || fail UNMANAGED_SYSTEM_NODE_LINK
    fi
    for path in /usr/local/lib/awg-pi "$RUNTIME_DIR" "$VERSION_DIR"; do
      [[ ! -L "$path" ]] || fail UNTRUSTED_RUNTIME_DIRECTORY
      if [[ -e "$path" ]]; then
        [[ -d "$path" && "$(stat -c %u "$path")" == 0 ]] || fail UNTRUSTED_RUNTIME_DIRECTORY
      else
        install -d -o root -g root -m 0755 "$path"
      fi
    done
    if [[ -e "$BIN" || -L "$BIN" ]]; then
      [[ ! -L "$BIN" && -f "$BIN" && "$(stat -c %u "$BIN")" == 0 ]] || fail UNTRUSTED_RUNTIME_BINARY
    fi
    tmp="$(mktemp "$VERSION_DIR/.node-XXXXXXXX")"
    trap 'rm -f -- "${tmp:-}" "${newlink:-}"' EXIT
    install -o root -g root -m 0755 "$SOURCE" "$tmp"
    hash_ok "$tmp" && version_ok "$tmp" || fail STAGED_BINARY_FAILED_VALIDATION
    mv -fT -- "$tmp" "$BIN"
    newlink="$(mktemp -u /usr/local/bin/.awg-node-link-XXXXXXXX)"
    [[ ! -e "$newlink" && ! -L "$newlink" ]] || fail LINK_STAGING_CONFLICT
    ln -s -- "$BIN" "$newlink" || fail LINK_STAGING_FAILED
    mv -fT -- "$newlink" "$LINK"
    path_ok || fail POSTINSTALL_VERIFICATION_FAILED
    # Explicit PATH means interactive shell and systemd have the same contract.
    env PATH=/usr/local/bin:/usr/bin:/bin node -e \
      'if (process.version !== "v22.16.0" || typeof WebSocket !== "function") process.exit(1)' \
      || fail GLOBAL_PATH_VERIFICATION_FAILED
    echo 'SYSTEM_NODE_INSTALL=VERIFIED'
    echo "SYSTEM_NODE_VERSION=$PIN_VERSION"
    echo 'SYSTEM_NODE_WEBSOCKET=AVAILABLE'
    echo 'DEBIAN_APT_NODE_PRESERVED=YES'
    ;;
  *)
    echo 'Usage: awg-system-node status|apply' >&2
    exit 2
    ;;
esac
