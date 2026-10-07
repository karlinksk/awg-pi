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
    '"Mihomo / Multi-Transport"',
    '"Заменить ссылку подписки"',
    '"Обновить подписку — AUTO"',
    '"Импортировать локальный профиль"',
    '"Переключить транспорт на Mihomo"',
    '"Переключить транспорт на AmneziaWG"',
    '"Точка выхода / узел"',
    '"MikroTik DIRECT обязателен"',
    '"Первичная настройка Mihomo"',
    '"Citadel / Remnawave"',
]

for needle in required:
    assert needle in menu, f"missing menu safety/config feature: {needle}"

check_pos = menu.index('config check "$PASTE_TMP"')
replace_pos = menu.index('config replace "$PASTE_TMP" --yes')
assert check_pos < replace_pos, "pasted profile must be validated before replacement"

assert 'PASTE_TMP=""' in menu
assert 'trap cleanup EXIT' in menu


# Every interactive menu must provide context help for the highlighted item.
assert menu.count("--menu") == menu.count("--item-help --menu"), (
    "every dialog menu must use --item-help"
)

for label in (
    '"Состояние системы"',
    '"VPN-маршрутизация"',
    '"Домены VPN"',
    '"DIRECT-исключения"',
    '"OpenCCK"',
    '"Клиенты"',
    '"Диагностика"',
    '"Обновления"',
    '"Журналы"',
    '"Системные функции"',
    '"Выйти в обычный Shell"',
    '"Завершить SSH-сессию"',
    '"Selective Gateway"',
    '"MikroTik Transit / Backup VPN"',
):
    assert label in menu, f"missing documented menu item: {label}"

assert "Весь маршрутизируемый трафик будет идти DIRECT" in menu
assert "SSH и Transit backup" in menu

assert '--passwordbox "$prompt"' in menu
assert '"$MIHOMO_CONFIGURE" provider-url set "$url"' in menu
assert '"$MIHOMO_CONFIGURE" provider update auto' in menu
assert '"$MIHOMO_CONFIGURE" provider import "$path"' in menu
assert '"$AWG_TRANSPORT" select mihomo' in menu
assert '"$AWG_TRANSPORT" select awg' in menu
assert '"$MIHOMO_CONFIGURE" node select "$node_name" "$endpoint" --direct-confirmed' in menu
assert '"$MIHOMO_CONFIGURE" node prepare "$node_name"' in menu
assert 'action=accept' in menu
assert 'place-before=0' in menu
assert 'mktemp /run/awg-pbr/mihomo-init.XXXXXX' in menu
assert 'chmod 600 "$init_tmp"' in menu
assert '"$MIHOMO_CONFIGURE" init "$init_tmp"' in menu
assert 'MIHOMO_PROVIDER_PROFILE=%q' in menu


for needle in (
    'BASE_BACKTITLE="AWG Pi Gateway v$VERSION"',
    'BACKTITLE="$BASE_BACKTITLE | Режим: $(operating_mode_badge "$mode")"',
    "РЕЖИМ РАБОТЫ:",
    'Главное меню — [$mode_badge]',
    '[ТЕКУЩИЙ]',
    'Operating mode [$mode_badge]',
    'AWG / Transit [TRANSIT]',
    'VPN policy [SELECTIVE]',
):
    assert needle in menu, f"missing operating-mode indicator: {needle}"

print("menu config paste/help checks: OK")
