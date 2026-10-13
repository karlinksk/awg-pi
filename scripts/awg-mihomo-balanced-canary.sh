#!/usr/bin/env bash
# Passive balanced canary: backup exact installed helpers, stage files, no live switch.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_BASE=/var/backups/awg-gateway
GATE=/etc/awg-pbr/transports/mihomo/service-eligibility.mode
MODE="${1:-check}"

SOURCE=(
 src/awg-mihomo-smart
 src/awg-mihomo-service-check.py
 src/awg-mihomo-video-decode.py
 src/awg-mihomo-network-eligibility.py
 src/awg-mihomo-node-policy
 src/awg-selection-monitor
 scripts/awg-mihomo-stage18-ram-runtime.sh
 units/awg-mihomo-stage18-ram-runtime.service
 units/awg-mihomo-stage18-ram-runtime.timer
)
TARGET=(
 /usr/local/sbin/awg-mihomo-smart
 /usr/local/sbin/awg-mihomo-service-check.py
 /usr/local/sbin/awg-mihomo-video-decode.py
 /usr/local/sbin/awg-mihomo-network-eligibility.py
 /usr/local/sbin/awg-mihomo-node-policy
 /usr/local/sbin/awg-selection-monitor
 /usr/local/sbin/awg-mihomo-stage18-ram-runtime
 /etc/systemd/system/awg-mihomo-stage18-ram-runtime.service
 /etc/systemd/system/awg-mihomo-stage18-ram-runtime.timer
)
FILE_MODE=(755 755 755 755 755 755 755 644 644)

fatal(){ echo "CANARY_ERROR=$*" >&2; exit 1; }
require_root(){ (( EUID == 0 )) || fatal "root access required for this action"; }
precheck(){
  [[ -e "$ROOT/.git" ]] || fatal "expected local Git checkout"
  [[ "$(git -c safe.directory="$ROOT" -C "$ROOT" rev-parse --is-inside-work-tree)" == true ]] || fatal "not a Git worktree"
  [[ -z "$(git -c safe.directory="$ROOT" -C "$ROOT" status --porcelain)" ]] || fatal "dirty source tree"
  for i in "${!SOURCE[@]}"; do
    [[ -f "$ROOT/${SOURCE[i]}" && ! -L "$ROOT/${SOURCE[i]}" ]] || fatal "missing source ${SOURCE[i]}"
    [[ ! -L "${TARGET[i]}" ]] || fatal "symlink destination ${TARGET[i]}"
  done
  bash -n "$ROOT/src/awg-mihomo-node-policy" "$ROOT/src/awg-selection-monitor" "$ROOT/scripts/awg-mihomo-stage18-ram-runtime.sh"
  python3 -B - "$ROOT" <<'PY'
import ast, pathlib, sys
root=pathlib.Path(sys.argv[1])
for name in (
"src/awg-mihomo-smart","src/awg-mihomo-service-check.py",
"src/awg-mihomo-video-decode.py","src/awg-mihomo-network-eligibility.py"):
    ast.parse((root/name).read_text(),filename=name)
PY
}
safe_backup(){
  local dir="$1"
  [[ "$dir" == "$BACKUP_BASE"/balanced-canary-* && "$dir" != *'..'* ]] || fatal "untrusted backup path"
  [[ -d "$dir" && ! -L "$dir" ]] || fatal "backup directory missing"
  [[ "$(stat -c '%u:%a' "$dir")" == 0:700 ]] || fatal "backup directory not private root-owned"
  [[ -f "$dir/manifest" && ! -L "$dir/manifest" ]] || fatal "backup manifest missing"
}
restore_files(){
  local dir="$1" index mark
  safe_backup "$dir"
  while read -r index mark; do
    [[ "$index" =~ ^[0-8]$ ]] || fatal "invalid manifest index"
    if [[ "$mark" == PRESENT ]]; then
      [[ -f "$dir/before/$index" && ! -L "$dir/before/$index" ]] || fatal "invalid backup item"
      cp -p -- "$dir/before/$index" "${TARGET[index]}.restore-$$"
      mv -fT -- "${TARGET[index]}.restore-$$" "${TARGET[index]}"
    elif [[ "$mark" == ABSENT ]]; then
      rm -f -- "${TARGET[index]}"
    else
      fatal "invalid manifest state"
    fi
  done < "$dir/manifest"
  systemctl daemon-reload
}
case "$MODE" in
  check)
    precheck
    echo "CANARY_SOURCE_TREE=$(git -c safe.directory="$ROOT" -C "$ROOT" rev-parse HEAD^{tree})"
    for i in "${!SOURCE[@]}"; do
      if [[ -f "${TARGET[i]}" ]] && cmp -s "$ROOT/${SOURCE[i]}" "${TARGET[i]}"; then
        echo "CANARY_FILE_$i=UNCHANGED"
      else
        echo "CANARY_FILE_$i=STAGED_CHANGE"
      fi
    done
    echo CANARY_READONLY_CHECK=PASS
    ;;
  apply)
    require_root
    precheck
    [[ "$(cat "$GATE" 2>/dev/null || echo off)" == off ]] || fatal "service gate must be OFF"
    /usr/local/sbin/awg-transport status | grep -Fq 'Transport ID: mihomo' || fatal "requires live Mihomo"
    /usr/local/sbin/awg-transport status | grep -Fq 'Transport health: healthy' || fatal "Mihomo must be healthy"
    mkdir -p "$BACKUP_BASE"
    [[ ! -L "$BACKUP_BASE" ]] || fatal "backup base is symlink"
    dir="$BACKUP_BASE/balanced-canary-$(date +%Y%m%d-%H%M%S)"
    mkdir -m 700 "$dir"
    mkdir -m 700 "$dir/before"
    for i in "${!TARGET[@]}"; do
      if [[ -e "${TARGET[i]}" ]]; then
        [[ -f "${TARGET[i]}" ]] || fatal "destination not regular file"
        cp -p -- "${TARGET[i]}" "$dir/before/$i"
        echo "$i PRESENT" >> "$dir/manifest"
      else
        echo "$i ABSENT" >> "$dir/manifest"
      fi
    done
    chmod 600 "$dir/manifest"
    rollback_pending=1
    rollback_if_needed(){
      local rc=$?
      trap - EXIT ERR INT TERM HUP
      if (( rollback_pending )); then
        echo "CANARY_ERROR=auto-restore-after-failure" >&2
        restore_files "$dir"
      fi
      exit "$rc"
    }
    trap rollback_if_needed EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    for i in "${!TARGET[@]}"; do
      tmp="${TARGET[i]}.canary-$$"
      install -m "${FILE_MODE[i]}" "$ROOT/${SOURCE[i]}" "$tmp"
      mv -fT -- "$tmp" "${TARGET[i]}"
    done
    systemctl daemon-reload
    systemd-analyze verify /etc/systemd/system/awg-mihomo-stage18-ram-runtime.service /etc/systemd/system/awg-mihomo-stage18-ram-runtime.timer >/dev/null
    [[ "$(cat "$GATE" 2>/dev/null || echo off)" == off ]] || fatal "service gate changed unexpectedly"
    rollback_pending=0
    trap - EXIT INT TERM HUP
    echo "CANARY_PASSIVE_INSTALL=PASS"
    echo "CANARY_BACKUP=$dir"
    echo "CANARY_GATE=OFF"
    echo "CANARY_TIMER=NOT_ENABLED"
    ;;
  restore)
    require_root
    [[ $# -eq 2 ]] || fatal "usage: restore BACKUP_DIR"
    dir="$2"
    safe_backup "$dir"
    if [[ "$(cat "$GATE" 2>/dev/null || echo off)" == balanced ]]; then
      temp_gate="$(mktemp "$(dirname "$GATE")/.balanced-off.XXXXXX")"
      printf 'off\n' > "$temp_gate"
      chmod 600 "$temp_gate"
      mv -fT -- "$temp_gate" "$GATE"
    fi
    systemctl disable --now awg-mihomo-stage18-ram-runtime.timer >/dev/null 2>&1 || true
    restore_files "$dir"
    systemctl restart awg-selection-monitor.service
    echo "CANARY_RESTORE=COMPLETE"
    /usr/local/sbin/awg-transport status
    ;;
  *)
    fatal "usage: check|apply|restore BACKUP_DIR"
    ;;
esac
