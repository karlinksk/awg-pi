#!/usr/bin/env python3
from pathlib import Path

menu = Path("src/awg-menu").read_text()

required = [
    'mktemp /run/awg-pbr/config-paste.XXXXXX.conf',
    'chmod 600 "$PASTE_TMP"',
    '--editbox "$PASTE_TMP"',
    "sed -i 's/\\r$//' \"$PASTE_TMP\"",
    'config check "$PASTE_TMP"',
    'config replace "$PASTE_TMP" --yes',
    '"Вставить конфигурацию текстом"',
    '"Загрузить конфигурацию из файла"',
    '"Откатить предыдущую конфигурацию"',
]

for needle in required:
    assert needle in menu, f"missing menu safety/config feature: {needle}"

check_pos = menu.index('config check "$PASTE_TMP"')
replace_pos = menu.index('config replace "$PASTE_TMP" --yes')
assert check_pos < replace_pos, "pasted profile must be validated before replacement"

assert 'PASTE_TMP=""' in menu
assert 'trap cleanup EXIT' in menu

print("menu config paste checks: OK")
