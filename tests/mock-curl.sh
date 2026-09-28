#!/usr/bin/env bash
set -Eeuo pipefail
out=""
while (($#)); do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$out" ]] || { echo "mock curl: missing -o" >&2; exit 2; }
cp "${MOCK_FIXTURE:?}" "$out"
