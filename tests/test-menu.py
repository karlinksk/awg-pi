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
    '"Откатить предыдущую конфигурацию [$rollback_state]"',
    '"Mihomo / Multi-Transport"',
    '"Mihomo Node Failover"',
    '"Редактировать FIXED chain"',
    '"Часовой пояс"',
    '"Статистика traffic"',
    '"Проверить / восстановить Mihomo engine"',
    '"VPN-сервисы / домены"',
    '"Subscription / Provider"',
    '"Заменить URL subscription"',
    '"Обновить subscription — AUTO"',
    '"Импорт provider / subscription"',
    '"Импортировать из файла"',
    '"Вставить текстом"',
    '"Обновить через выбранный канал"',
    '"Staged provider / candidate"',
    '"Offline engine recovery (.gz)"',
    '"Точка выхода / узел"',
    '"Активный transport"',
    '"Расширенные / Recovery"',
    '"Добавить / настроить transport"',
    '"Transport Selection Policy"',
    '"Citadel / Remnawave"',
    '"Формат подписки"',
    '"Mihomo / Clash YAML"',
    '"VLESS URI"',
    '"Base64 VLESS"',
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
    '"VPN-сервисы / домены"',
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
    '"Добавить / настроить transport"',
):
    assert label in menu, f"missing documented menu item: {label}"

assert "Весь маршрутизируемый трафик будет идти DIRECT" in menu
assert "SSH и Transit backup" in menu

# Main menu stays compact: OpenCCK administration is available from
# VPN-сервисы / домены -> OpenCCK — расширенно, not duplicated at top level.
main_start = menu.index('while true; do\n  refresh_backtitle', menu.index('system_menu(){'))
main_block = menu[main_start:]
assert '    5 "OpenCCK"' not in main_block
assert '    5 "Клиенты"' in main_block
assert '    6 "Диагностика"' in main_block
assert '    7 "Обновления"' in main_block
assert '    8 "Журналы"' in main_block
assert '    9 "Системные функции"' in main_block
assert '    10 "Выйти в обычный Shell"' in main_block
assert '5) client_menu' in main_block
assert '6) diagnostics_screen' in main_block
assert '7) update_menu' in main_block
assert '8) logs_screen' in main_block
assert '9) system_menu' in main_block
assert '10) clear; exit 10' in main_block
assert 'OpenCCK — расширенно' in menu
assert 'проверка/восстановление Mihomo engine' in main_block

assert '--passwordbox "$prompt"' in menu
assert '"$MIHOMO_CONFIGURE" provider stage-url-file "$url_tmp"' in menu
assert '"$MIHOMO_CONFIGURE" provider stage-file "$path" "$source_mode"' in menu
assert '"$MIHOMO_CONFIGURE" provider candidate commit "$node_name" "$endpoint"' in menu
assert 'provider-url set-file "$url_tmp"' not in menu
assert '"$MIHOMO_CONFIGURE" provider update auto' in menu
assert 'direct "DIRECT"' in menu
assert 'router "Router/default"' not in menu
assert "DIRECT → текущий healthy transport → остальные healthy transports" in menu
assert "Live не меняется до выбора node и commit" in menu
assert 'mktemp /run/awg-pbr/mihomo-paste.XXXXXX' in menu
assert '"$MIHOMO_CONFIGURE" provider stage-file "$PASTE_TMP" "$source_mode"' in menu
assert '"$AWG_TRANSPORT" select mihomo' in menu
assert '"$AWG_TRANSPORT" select awg' in menu
assert '"$MIHOMO_CONFIGURE" node select "$node_name" "$endpoint"' in menu
assert '--direct-confirmed' not in menu
assert '"$MIHOMO_CONFIGURE" node prepare "$node_name"' in menu
assert 'Отдельное MikroTik правило для этого IP больше НЕ требуется' in menu
assert 'gateway-wide DIRECT bypass' in menu
assert '"$AWG_FIRST_RUN" wizard' in menu
assert 'secondary_transport_setup' in menu
assert 'rollback_state="доступен"' in menu
assert 'rollback_state="нет предыдущего профиля"' in menu
assert 'Предыдущий AWG-профиль для быстрого rollback отсутствует.' in menu
assert 'Архивные upgrade/install backups не используются как automatic rollback' in menu
assert 'if [[ ! -s "$previous" ]]' in menu
assert '5) secondary_transport_setup' in menu
assert '6) secondary_transport_setup' in menu
assert 'mihomo_initial_setup_flow secondary' in menu
assert 'Mihomo уже настроен как дополнительный backend' in menu
assert 'Текущий active transport' in menu
assert 'НЕ изменён' in menu
assert 'optional ordered fallback-chain' in menu
# The normal VPN menus must not invoke first-run directly when a transport exists.
transit_block = menu[menu.index('vpn_menu(){'):menu.index('dns_menu(){')]
assert 'run_interactive "Первичная настройка transport" "$AWG_FIRST_RUN" wizard' not in transit_block
assert 'AWG_SELECTION=/usr/local/sbin/awg-selection' in menu
assert '"$AWG_SELECTION" mode manual' in menu
assert '"$AWG_SELECTION" mode fixed awg mihomo' in menu
assert '"$AWG_SELECTION" mode fixed mihomo awg' in menu
assert '"$AWG_SELECTION" mode auto awg mihomo' in menu
assert '"$AWG_SELECTION" mode auto mihomo awg' in menu
assert 'Mihomo node/страна не меняются' in menu
assert 'MIHOMO_INSTALLER=/usr/local/sbin/awg-mihomo-install' in menu
assert 'MIHOMO_NODE_POLICY=/usr/local/sbin/awg-mihomo-node-policy' in menu
assert '"$MIHOMO_NODE_POLICY" mode manual' in menu
assert '"$MIHOMO_NODE_POLICY" mode fixed "${nodes[@]}"' in menu
assert 'Failover идёт только слева направо' in menu
assert 'resolve_tsv_node_choice' in menu
assert 'Введите номер или ТОЧНОЕ имя узла из списка выше:' in menu
assert 'Введите номер или ТОЧНОЕ имя live-node:' in menu
assert '"$AWG_ROUTE" source add opencck "$target" --type domains --kind "$method"' in menu
assert 'Имя вводится один раз' in menu
assert 'AWG_TRAFFIC=/usr/local/sbin/awg-traffic' in menu
assert '"$AWG_TRAFFIC" status compact' in menu
assert 'timedatectl set-timezone "$zone"' in menu
assert '"$AWG_UPDATE" --yes mihomo' in menu
assert 'Произвольный upstream latest не устанавливается.' in menu
assert 'installed=supported' in menu
assert 'cpu_temperature' in menu
assert 'memory_summary' in menu
assert 'system_uptime' in menu
assert 'страна автоматически не определяется' in menu
assert '"$MIHOMO_INSTALLER" --file "$path"' in menu
assert 'mktemp /run/awg-pbr/mihomo-url.XXXXXX' in menu
assert 'chmod 600 "$url_tmp"' in menu
assert 'printf \'MIHOMO_PROVIDER_URL=%q\\n\' "$url" >"$url_tmp"' in menu
assert 'provider-url set "$url"' not in menu
assert 'mktemp /run/awg-pbr/mihomo-init.XXXXXX' in menu
assert 'chmod 600 "$init_tmp"' in menu
assert '"$MIHOMO_CONFIGURE" init "$init_tmp"' in menu
assert 'MIHOMO_PROVIDER_PROFILE=%q' in menu
assert 'MIHOMO_PROVIDER_FORMAT=%q' in menu
assert '"$MIHOMO_CONFIGURE" provider format set "$provider_format"' in menu
assert 'mihomo_provider_format_dialog' in menu
assert 'mihomo_subscription_menu' in menu
assert 'mihomo_import_menu' in menu
assert 'active_transport_menu' in menu
assert 'mihomo_advanced_menu' in menu

# The top-level Mihomo menu is intentionally compact. Technical/recovery
# operations remain available only through their dedicated submenus.
mihomo_start = menu.index('mihomo_menu(){')
mihomo_end = menu.index('selection_policy_menu(){', mihomo_start)
mihomo_block = menu[mihomo_start:mihomo_end]
for label in (
    '1 "Состояние Mihomo"',
    '2 "Subscription / Provider"',
    '3 "Точка выхода / узел"',
    '4 "Mihomo Node Failover"',
    '5 "Расширенные / Recovery"',
):
    assert label in mihomo_block, f"missing compact Mihomo item: {label}"

for old_top_level in (
    '"Заменить ссылку подписки"',
    '"Обновить подписку — AUTO"',
    '"Импортировать локальный профиль"',
    '"Переключить транспорт на Mihomo"',
    '"Переключить транспорт на AmneziaWG"',
    '"Добавить / первично настроить Mihomo"',
    '"Формат подписки"',
    '"Staged provider / candidate"',
    '"Установить Mihomo engine из локального .gz"',
):
    assert old_top_level not in mihomo_block, (
        f"legacy/advanced item leaked into top-level Mihomo menu: {old_top_level}"
    )

subscription_start = menu.index('mihomo_subscription_menu(){')
subscription_end = menu.index('active_transport_menu(){', subscription_start)
subscription_block = menu[subscription_start:subscription_end]
assert '"Заменить URL subscription"' in subscription_block
assert '"Обновить subscription — AUTO"' in subscription_block
assert '"Импорт provider / subscription"' in subscription_block

advanced_start = menu.index('mihomo_advanced_menu(){')
advanced_end = menu.index('mihomo_menu(){', advanced_start)
advanced_block = menu[advanced_start:advanced_end]
assert '"Обновить через выбранный канал"' in advanced_block
assert '"Формат подписки"' in advanced_block
assert '"Staged provider / candidate"' in advanced_block
assert '"Offline engine recovery (.gz)"' in advanced_block

assert 'mihomo_initial_setup_flow secondary' in menu
assert '"Добавить / первично настроить Mihomo"' not in mihomo_block
assert '"Активный transport"' not in mihomo_block
assert 'mihomo_active_transport_menu' not in menu

vpn_start = menu.index('vpn_menu(){')
vpn_end = menu.index('dns_menu(){', vpn_start)
vpn_block = menu[vpn_start:vpn_end]
assert vpn_block.count('"Активный transport"') == 2
assert '6 "Активный transport"' in vpn_block
assert '7 "Активный transport"' in vpn_block
assert '6) active_transport_menu' in vpn_block
assert '7) active_transport_menu' in vpn_block
assert '7 "Transport Selection Policy"' in vpn_block
assert '8 "Transport Selection Policy"' in vpn_block
assert 'active transport меняется отдельным пунктом ниже' in vpn_block


for needle in (
    'BASE_BACKTITLE="AWG Pi Gateway v$VERSION"',
    'BACKTITLE="$BASE_BACKTITLE | Режим: $(operating_mode_badge "$mode")"',
    "РЕЖИМ:",
    'Главное меню — [$mode_badge]',
    '[ТЕКУЩИЙ]',
    'Operating mode [$mode_badge]',
    'AWG / Transit [TRANSIT]',
    'VPN policy [SELECTIVE]',
):
    assert needle in menu, f"missing operating-mode indicator: {needle}"

print("menu config paste/help checks: OK")
