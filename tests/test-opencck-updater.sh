#!/usr/bin/env bash
set -Eeuo pipefail

tmp="$(mktemp -d)"
cleanup(){ sudo rm -rf "$tmp"; }
trap cleanup EXIT
mkdir -p "$tmp/meta" "$tmp/data" "$tmp/bin"

cp tests/mock-curl.sh "$tmp/bin/curl"
chmod +x "$tmp/bin/curl"
cat >"$tmp/bin/awg-route" <<EOF
#!/usr/bin/env bash
echo "\$*" >>"$tmp/route.log"
exit 0
EOF
chmod +x "$tmp/bin/awg-route"

cat >"$tmp/meta/yttest.env" <<EOF
PROVIDER=opencck
SOURCE_ID=yttest
SOURCE_KIND=group
SOURCE_NAME=youtube
SOURCE_TYPE=domains
ENABLED=1
DATA_FILE=$tmp/data/youtube.domains
LAST_SUCCESS=never
ENTRY_COUNT=0
EOF

run_update(){
  local fixture="$1"
  sudo env     PATH="$tmp/bin:/usr/bin:/bin"     MOCK_FIXTURE="$PWD/$fixture"     AWG_OPENCCK_META_DIR="$tmp/meta"     AWG_ROUTE_BIN="$tmp/bin/awg-route"     AWG_COMMON_LIB="$PWD/src/awg-common"     AWG_MODE_FILE="$tmp/mode"     bash "$PWD/src/awg-opencck-update" yttest
}

echo selective >"$tmp/mode"

run_update tests/fixtures/opencck-good.txt
sudo test -s "$tmp/data/youtube.domains"
sudo grep -Fxq youtube.com "$tmp/data/youtube.domains"
sudo grep -Fxq googlevideo.com "$tmp/data/youtube.domains"
sudo grep -Fxq ytimg.com "$tmp/data/youtube.domains"
sudo grep -Fxq www.youtube.com "$tmp/data/youtube.domains"
[[ "$(sudo wc -l "$tmp/data/youtube.domains" | awk '{print $1}')" == 4 ]]
sudo grep -Eq '^ENTRY_COUNT=4$' "$tmp/meta/yttest.env"
grep -Fxq reload "$tmp/route.log"

echo transit >"$tmp/mode"
sudo truncate -s 0 "$tmp/route.log"
run_update tests/fixtures/opencck-good.txt >"$tmp/transit-update.log"
[[ ! -s "$tmp/route.log" ]] || { echo "FAIL: Transit OpenCCK update reloaded live datapath" >&2; exit 1; }
grep -Fq 'live reload отложен (Transit mode)' "$tmp/transit-update.log"
echo selective >"$tmp/mode"

before="$(sudo sha256sum "$tmp/data/youtube.domains" | awk '{print $1}')"
set +e
run_update tests/fixtures/opencck-bad.txt >/tmp/awg-opencck-test-bad.log 2>&1
rc=$?
set -e
(( rc != 0 )) || { echo "FAIL: invalid OpenCCK list was accepted" >&2; cat /tmp/awg-opencck-test-bad.log; exit 1; }
after="$(sudo sha256sum "$tmp/data/youtube.domains" | awk '{print $1}')"
[[ "$before" == "$after" ]] || { echo "FAIL: last-known-good cache changed after invalid update" >&2; exit 1; }

echo "OpenCCK updater: OK"
