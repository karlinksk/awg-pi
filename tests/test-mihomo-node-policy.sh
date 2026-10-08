#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'sudo rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/etc"
printf '%s\n' '🇫🇮 Finland' >"$TMP/etc/node-name"
: >"$TMP/log"

cat >"$TMP/bin/configure" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"${MOCK_NODE_LOG:?}"
case "$*" in
  "node prepare 🇫🇮 Finland"|"node prepare DE (backup)+1"|"node prepare NL [test]*")
    printf 'Resolved IPv4 endpoints:\n  - 192.0.2.10\n'
    ;;
  "node select-auto DE (backup)+1")
    [[ "${MOCK_DE_OK:-1}" == 1 ]] || exit 1
    printf '%s\n' 'DE (backup)+1' >"${MOCK_NODE_NAME_FILE:?}"
    ;;
  "node select-auto NL [test]*")
    [[ "${MOCK_NL_OK:-1}" == 1 ]] || exit 1
    printf '%s\n' 'NL [test]*' >"${MOCK_NODE_NAME_FILE:?}"
    ;;
  *)
    exit 1
    ;;
esac
MOCK
chmod +x "$TMP/bin/configure"

run_policy(){
  sudo env \
    MIHOMO_NODE_POLICY_MODE_FILE="$TMP/etc/node-policy.mode" \
    MIHOMO_NODE_POLICY_ORDER_FILE="$TMP/etc/node-policy.nodes" \
    MIHOMO_NODE_NAME_FILE="$TMP/etc/node-name" \
    MIHOMO_CONFIGURE_BIN="$TMP/bin/configure" \
    MOCK_NODE_LOG="$TMP/log" \
    MOCK_NODE_NAME_FILE="$TMP/etc/node-name" \
    MOCK_DE_OK="${MOCK_DE_OK:-1}" \
    MOCK_NL_OK="${MOCK_NL_OK:-1}" \
    bash "$ROOT/src/awg-mihomo-node-policy" "$@"
}

echo "=== MANUAL is the node-policy default ==="
out="$(run_policy status)"
grep -Fqx 'Mihomo node policy: manual' <<<"$out"
grep -Fqx 'Automatic Mihomo node switching: disabled' <<<"$out"
grep -Fqx 'Country inference: disabled' <<<"$out"

echo "=== FIXED validates exact user-listed nodes ==="
: >"$TMP/log"
out="$(run_policy mode fixed '🇫🇮 Finland' 'DE (backup)+1' 'NL [test]*')"
grep -Fqx 'MIHOMO_NODE_POLICY=fixed' <<<"$out"
sudo grep -Fqx '🇫🇮 Finland' "$TMP/etc/node-policy.nodes"
sudo grep -Fqx 'DE (backup)+1' "$TMP/etc/node-policy.nodes"
sudo grep -Fqx 'NL [test]*' "$TMP/etc/node-policy.nodes"
grep -Fqx 'node prepare 🇫🇮 Finland' "$TMP/log"
grep -Fqx 'node prepare DE (backup)+1' "$TMP/log"
grep -Fqx 'node prepare NL [test]*' "$TMP/log"

echo "=== duplicate exact node is rejected even with shell metacharacters elsewhere ==="
if run_policy mode fixed 'NL [test]*' 'NL [test]*' >"$TMP/out" 2>"$TMP/err"; then
  echo 'FAIL: duplicate exact node was accepted' >&2
  exit 1
fi
grep -Fq 'Duplicate node in failover order' "$TMP/err"

echo "=== unknown node is rejected before policy commit ==="
sudo cp "$TMP/etc/node-policy.nodes" "$TMP/order.before"
if run_policy mode fixed '🇫🇮 Finland' 'Unknown country/node' >"$TMP/out" 2>"$TMP/err"; then
  echo 'FAIL: unknown node was accepted' >&2
  exit 1
fi
sudo cmp -s "$TMP/order.before" "$TMP/etc/node-policy.nodes"
grep -Fq 'not present/resolvable' "$TMP/err"

echo "=== failover never chooses an unlisted node ==="
printf '%s\n' '🇫🇮 Finland' | sudo tee "$TMP/etc/node-name" >/dev/null
: >"$TMP/log"
out="$(run_policy failover)"
grep -Fqx 'MIHOMO_NODE_FAILOVER=🇫🇮 Finland->DE (backup)+1' <<<"$out"
grep -Fqx 'node select-auto DE (backup)+1' "$TMP/log"
if grep -Fq 'Unknown' "$TMP/log"; then
  echo 'FAIL: failover attempted an unlisted node' >&2
  exit 1
fi

echo "=== failed first fallback tries next explicitly allowed exact node ==="
printf '%s\n' '🇫🇮 Finland' | sudo tee "$TMP/etc/node-name" >/dev/null
: >"$TMP/log"
out="$(MOCK_DE_OK=0 MOCK_NL_OK=1 run_policy failover)"
grep -Fqx 'MIHOMO_NODE_FAILOVER=🇫🇮 Finland->NL [test]*' <<<"$out"
grep -Fqx 'node select-auto DE (backup)+1' "$TMP/log"
grep -Fqx 'node select-auto NL [test]*' "$TMP/log"

echo "=== current node outside policy disables node auto-failover ==="
printf '%s\n' 'Unlisted current' | sudo tee "$TMP/etc/node-name" >/dev/null
: >"$TMP/log"
if run_policy failover >"$TMP/out" 2>"$TMP/err"; then
  echo 'FAIL: failover acted on a current node outside the explicit allow-list' >&2
  exit 1
fi
[[ ! -s "$TMP/log" ]]

echo "=== MANUAL clears the fallback allow-list ==="
out="$(run_policy mode manual)"
grep -Fqx 'MIHOMO_NODE_POLICY=manual' <<<"$out"
sudo test ! -e "$TMP/etc/node-policy.nodes"

echo "Mihomo exact-node policy: OK"
