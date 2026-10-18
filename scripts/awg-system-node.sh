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
PIN_TAR_SHA=eab80cb88f8fda1e65f5e8d0420c9809bdb320b03fd34976ab7161b6e703b910
PIN_TARBALL="node-v22.16.0-linux-arm64.tar.xz"
NPM_DIR="$VERSION_DIR/npm"
NPM_LINK=/usr/local/bin/npm
NPX_LINK=/usr/local/bin/npx
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
npm_ok(){
  path_ok || return 1
  [[ -f "$NPM_DIR/bin/npm-cli.js" && -f "$NPM_DIR/bin/npx-cli.js" ]] || return 1
  [[ ! -L "$NPM_DIR/bin/npm-cli.js" && ! -L "$NPM_DIR/bin/npx-cli.js" ]] || return 1
  [[ -L "$NPM_LINK" && "$(readlink -- "$NPM_LINK")" == "$NPM_DIR/bin/npm-cli.js" ]] || return 1
  [[ -L "$NPX_LINK" && "$(readlink -- "$NPX_LINK")" == "$NPM_DIR/bin/npx-cli.js" ]] || return 1
  env PATH=/usr/local/bin:/usr/bin:/bin npm --version >/dev/null 2>&1 &&
    env PATH=/usr/local/bin:/usr/bin:/bin npx --version >/dev/null 2>&1
}
install_pinned_npm(){
  (( EUID == 0 )) || fail ROOT_REQUIRED
  [[ "$(uname -m)" == aarch64 ]] || fail UNSUPPORTED_ARCH
  path_ok || fail PINNED_SYSTEM_NODE_REQUIRED
  if npm_ok; then echo 'SYSTEM_NPM_INSTALL=ALREADY_VERIFIED'; return 0; fi
  for pair in "$NPM_LINK:$NPM_DIR/bin/npm-cli.js" "$NPX_LINK:$NPM_DIR/bin/npx-cli.js"; do
    local_dest="${pair%%:*}"; local_target="${pair#*:}"
    if [[ -e "$local_dest" || -L "$local_dest" ]]; then
      [[ -L "$local_dest" && "$(readlink -- "$local_dest")" == "$local_target" ]] ||
        fail UNMANAGED_NPM_OR_NPX_REFUSED
    fi
  done
  [[ ! -L "$VERSION_DIR" && -d "$VERSION_DIR" && "$(stat -c %u "$VERSION_DIR")" == 0 ]] ||
    fail UNTRUSTED_RUNTIME_DIRECTORY
  [[ ! -e "$NPM_DIR" && ! -L "$NPM_DIR" ]] || fail NPM_DIRECTORY_EXISTS_NOT_VERIFIED
  # Same SHA256-pinned official Node.js v22.16.0 ARM64 bundle as Stage18.
  # Only npm/npx is extracted; the existing Node binary is not touched.
  local extracted npm_archive npm_stage
  npm_archive="$(mktemp "$VERSION_DIR/.node-npm-tar-XXXXXXXX")"
  npm_stage="$(mktemp -d "$VERSION_DIR/.npm-stage-XXXXXXXX")"
  # Capture paths at trap creation: Bash locals disappear on return.
  trap "rm -f -- '$npm_archive'; rm -rf -- '$npm_stage'" EXIT
  curl -qfsSL --retry 2 --connect-timeout 8 --max-time 90 \
    "https://nodejs.org/dist/v22.16.0/$PIN_TARBALL" -o "$npm_archive" ||
    fail PINNED_NPM_DOWNLOAD_FAILED
  printf '%s  %s\n' "$PIN_TAR_SHA" "$npm_archive" | sha256sum -c --status ||
    fail PINNED_NPM_ARCHIVE_CHECKSUM_FAILED
  tar --no-same-owner -xJf "$npm_archive" -C "$npm_stage" \
    "node-v22.16.0-linux-arm64/lib/node_modules/npm" ||
    fail PINNED_NPM_EXTRACT_FAILED
  extracted="$stage/node-v22.16.0-linux-arm64/lib/node_modules/npm"
  [[ -f "$extracted/bin/npm-cli.js" && -f "$extracted/bin/npx-cli.js" ]] ||
    fail PINNED_NPM_INCOMPLETE
  "$BIN" "$extracted/bin/npm-cli.js" --version >/dev/null ||
    fail PINNED_NPM_RUNTIME_FAILED
  "$BIN" "$extracted/bin/npx-cli.js" --version >/dev/null ||
    fail PINNED_NPX_RUNTIME_FAILED
  mv -T -- "$extracted" "$NPM_DIR"
  ln -s -- "$NPM_DIR/bin/npm-cli.js" "$NPM_LINK" 2>/dev/null ||
    [[ -L "$NPM_LINK" && "$(readlink -- "$NPM_LINK")" == "$NPM_DIR/bin/npm-cli.js" ]] ||
    fail NPM_LINK_CREATE_FAILED
  ln -s -- "$NPM_DIR/bin/npx-cli.js" "$NPX_LINK" 2>/dev/null ||
    [[ -L "$NPX_LINK" && "$(readlink -- "$NPX_LINK")" == "$NPM_DIR/bin/npx-cli.js" ]] ||
    fail NPX_LINK_CREATE_FAILED
  npm_ok || fail NPM_NPX_POSTINSTALL_VERIFICATION_FAILED
  echo SYSTEM_NPM_INSTALL=VERIFIED
  echo PINNED_NODE_VERSION="$PIN_VERSION"
  echo DEBIAN_APT_NODE_PRESERVED=YES
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
  npm)
    [[ $# == 1 ]] || fail BAD_ARGUMENTS
    install_pinned_npm
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
    # Directory from mktemp is root-owned 0700; no predictable link staging.
    staging="$(mktemp -d "$RUNTIME_DIR/.node-link-XXXXXXXX")"
    trap 'rm -f -- "${tmp:-}"; if [[ -n "${staging:-}" ]]; then rm -rf -- "$staging"; fi' EXIT
    install -o root -g root -m 0755 "$SOURCE" "$tmp"
    hash_ok "$tmp" && version_ok "$tmp" || fail STAGED_BINARY_FAILED_VALIDATION
    mv -fT -- "$tmp" "$BIN"
    ln -s -- "$BIN" "$staging/node" || fail LINK_STAGING_FAILED
    mv -fT -- "$staging/node" "$LINK"
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
    echo 'Usage: awg-system-node status|apply|npm' >&2
    exit 2
    ;;
esac
