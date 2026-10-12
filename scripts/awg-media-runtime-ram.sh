#!/usr/bin/env bash
# Download PINNED, checksum-verified Node 22 and yt-dlp into tmpfs only.
# No sudo, no modifications to production programs, services or routing.
set -Eeuo pipefail
umask 022
BASE=/dev/shm/awg-stage15
BINDIR=$BASE/bin
PROXY=http://127.0.0.1:7890
NODE_VERSION=v22.16.0
YT_VERSION=2026.08.19
cleanup_fail() {
  rm -rf -- "$BASE"
}
trap cleanup_fail ERR
[[ "$(id -u)" -ne 0 ]] || { echo "MUST_NOT_RUN_AS_ROOT"; exit 11; }
[[ ! -e "$BASE" ]] || { echo "RAM_RUNTIME_ALREADY_PRESENT"; exit 12; }
install -d -m 0755 "$BINDIR"
curl_safe() {
  curl -q -fLsS --proxy "$PROXY" --connect-timeout 5 --retry 1 --max-time 190 "$@"
}
cd "$BASE"
curl_safe "https://nodejs.org/dist/$NODE_VERSION/SHASUMS256.txt" -o node-shasums.txt
curl_safe "https://nodejs.org/dist/$NODE_VERSION/node-$NODE_VERSION-linux-arm64.tar.xz" -o node.tar.xz
grep -F "  node-$NODE_VERSION-linux-arm64.tar.xz" node-shasums.txt |
  grep -E '^[0-9a-f]{64}  node-' > node-check.txt
[[ "$(wc -l < node-check.txt)" == 1 ]] || { echo "NODE_SHA_MANIFEST_UNVERIFIED"; exit 13; }
mv node.tar.xz "node-$NODE_VERSION-linux-arm64.tar.xz"
sha256sum -c node-check.txt >/dev/null
tar -xJf "node-$NODE_VERSION-linux-arm64.tar.xz"   --no-same-owner --no-same-permissions   --wildcards --strip-components=2 -C "$BINDIR"   "node-$NODE_VERSION-linux-arm64/bin/node"
[[ "$("$BINDIR/node" --version)" == "$NODE_VERSION" ]] ||
  { echo "NODE_VERSION_UNVERIFIED"; exit 14; }
curl_safe "https://github.com/yt-dlp/yt-dlp/releases/download/$YT_VERSION/SHA2-256SUMS" -o yt-shasums.txt
curl_safe "https://github.com/yt-dlp/yt-dlp/releases/download/$YT_VERSION/yt-dlp" -o "$BINDIR/yt-dlp"
grep -F '  yt-dlp' yt-shasums.txt | grep -E '^[0-9a-f]{64}  yt-dlp$' > yt-check.txt
[[ "$(wc -l < yt-check.txt)" == 1 ]] || { echo "YTDLP_SHA_MANIFEST_UNVERIFIED"; exit 15; }
cp "$BINDIR/yt-dlp" yt-dlp
sha256sum -c yt-check.txt >/dev/null
chmod 0555 "$BINDIR/node" "$BINDIR/yt-dlp"
rm -f node*.txt yt*.txt yt-dlp "node-$NODE_VERSION-linux-arm64.tar.xz"
chmod 0755 "$BASE" "$BINDIR"
echo "STAGE15_RAM_RUNTIME_VERIFIED"
echo "NODE_VERSION=$NODE_VERSION"
echo "YTDLP_VERSION=$YT_VERSION"
echo "RAM_RUNTIME_BYTES=$(du -sb "$BINDIR" | cut -f1)"
echo "PRODUCTION_UNCHANGED=true"
