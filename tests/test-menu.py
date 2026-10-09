#!/usr/bin/env python3
from pathlib import Path

menu = Path("src/awg-menu").read_text()

# Core safety / configuration flows must stay present.
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
    '"Mihomo"',
    '"Резервирование узлов Mihomo"',
    '"Редактировать цепочку FIXED"',
    '"Часовой пояс"',
    '"Статистика трафика"',
    '"Проверить / восстановить Mihomo"',
    '"VPN-сервисы / домены"',
    '"Подписка / источник"',
    '"Заменить URL подписки"',
    '"Обновить подписку — AUTO"',
    '"Импорт профиля / подписки"',
    '"Импортировать из файла"',
    '"Вставить текстом"',
    '"Обновить через выбранный канал"',
    '"Подготовленный профиль"',
    '"Локальное восстановление Mihomo (.gz)"',
    '"Точка выхода / узел"',
    '"Активный транспорт"',
    '"Расширенные / восстановление"',
    '"Добавить / настроить транспорт"',
    '"Политика выбора транспорта"',
    '"Citadel / Remnawave"',
    '"Формат подписки"',
    '"Mihomo / Clash YAML"',
    '"VLESS URI"',
    '"Base64 VLESS"',
]
for needle in required:
    assert needle in menu, f"missing menu safety/config feature: {needle}"

# Pasted AWG profile is always checked before replacement.
check_pos = menu.index('config check "$PASTE_TMP"')
replace_pos = menu.index('config replace "$PASTE_TMP" --yes')
assert check_pos < replace_pos
assert 'PASTE_TMP=""' in menu
assert 'PASTE_OUT=""' in menu
assert 'trap cleanup EXIT' in menu

# Long/silent menu commands must expose a live heartbeat instead of leaving a
# blank terminal while the user waits.
assert 'run_with_progress(){' in menu
assert '--infobox' in menu
assert 'Прошло: ${elapsed} с' in menu
assert 'SSH-сессию не закрывайте' in menu
assert 'kill -0 "$pid"' in menu
assert 'wait "$pid"' in menu
assert 'run_with_progress "$heading" "$@"' in menu
assert 'run_with_progress "Перезапуск $label" systemctl restart "$service"' in menu
assert 'run_with_progress "Перезапуск монитора состояния" systemctl restart awg-pbr-health.service' in menu

# Non-interactive long operations should use the progress-aware capture path.
assert 'run_interactive "Переключение на Mihomo"' not in menu
assert 'run_interactive "Переключение на AmneziaWG"' not in menu
assert 'run_interactive "Обновление AWG Pi Gateway"' not in menu
assert 'run_interactive "Обновление AmneziaWG"' not in menu
assert 'run_interactive "Проверка Mihomo"' not in menu
assert 'run_interactive "Полное обновление"' not in menu
assert 'run_interactive "Изменение DNS"' not in menu
assert '"$AWG_ROUTE" dns set "$servers" --yes' in menu
assert '"$AWG_ROUTE" config replace "$path" --yes' in menu
assert '"$AWG_ROUTE" config rollback --yes' in menu

# Truly interactive wizards still keep a terminal screen, but explicitly tell
# the user that silent stages may take time.
assert 'Операция запущена. Сообщения и запросы появятся ниже.' in menu
assert 'процесс не завис' in menu

# dialog --editbox returns edited text on its output stream; it does not modify
# the input file. Both paste flows must capture that output into a root-only
# temporary file before validating/using it.
assert menu.count('dialog --stdout --backtitle "$BACKTITLE"') >= 2
assert menu.count('>"$PASTE_OUT"') == 2
assert menu.count('mv -f "$PASTE_OUT" "$PASTE_TMP"') == 2
assert 'config-paste-result.XXXXXX.conf' in menu
assert 'mihomo-paste-result.XXXXXX' in menu

# Every dialog menu has item help.
assert menu.count("--menu") == menu.count("--item-help --menu")

# Main menu: compact and Russian-first.
main_start = menu.index('while true; do\n  refresh_backtitle', menu.index('system_menu(){'))
main_block = menu[main_start:]
for label in (
    '1 "Состояние системы"',
    '2 "VPN-маршрутизация"',
    '3 "VPN-сервисы / домены"',
    '4 "DIRECT-исключения"',
    '5 "Клиенты"',
    '6 "Диагностика"',
    '7 "Обновления"',
    '8 "Журналы"',
    '9 "Системные функции"',
    '10 "Выйти в командную строку"',
    '0 "Завершить SSH-сессию"',
):
    assert label in main_block, f"missing main-menu item: {label}"
assert '5 "OpenCCK"' not in main_block
assert 'OpenCCK — расширенно' in menu
assert 'поддерживаемой версии Mihomo' in main_block

# Provider/subscription staging remains transactional. Setup input is visible
# by design; secrets remain redacted only after they have been applied.
assert '--passwordbox' not in menu
assert '--insecure' not in menu
assert 'secret_input' not in menu
assert 'Ввод отображается полностью.' in menu
assert '--inputbox "$prompt" 11 110 "$initial"' in menu
assert 'MIHOMO_ENV_FILE=/etc/awg-pbr/transports/mihomo/provider.env' in menu
assert 'current_mihomo_provider_url' in menu
assert '"$current_url"' in menu
assert 'Текущий URL подставлен в поле, если он сохранён.' in menu
assert '"$MIHOMO_CONFIGURE" provider stage-url-file "$url_tmp"' in menu
assert '"$MIHOMO_CONFIGURE" provider stage-file "$path" "$source_mode"' in menu
assert '"$MIHOMO_CONFIGURE" provider candidate commit-auto "$node_name"' in menu
assert 'provider-url set-file "$url_tmp"' not in menu
assert '"$MIHOMO_CONFIGURE" provider update auto' in menu
assert 'direct "DIRECT"' in menu
assert 'router "Router/default"' not in menu
assert 'сначала пробует DIRECT' in menu
assert 'Рабочий профиль не меняется до выбора узла и применения.' in menu
assert 'mktemp /run/awg-pbr/mihomo-paste.XXXXXX' in menu
assert '"$MIHOMO_CONFIGURE" provider stage-file "$PASTE_TMP" "$source_mode"' in menu

# Manual transport switching exists only in the dedicated VPN-routing menu.
assert menu.count('"$AWG_TRANSPORT" select mihomo') == 1
assert menu.count('"$AWG_TRANSPORT" select awg') == 1
assert 'active_transport_menu' in menu
assert 'mihomo_active_transport_menu' not in menu

# Mihomo node selection and DIRECT invariant.
assert '"$MIHOMO_CONFIGURE" node select-auto "$node_name"' in menu
assert '--direct-confirmed' not in menu
assert '"$MIHOMO_CONFIGURE" node prepare "$node_name"' in menu
assert 'Отдельное правило MikroTik для этого IP не требуется' in menu
assert 'постоянное DIRECT-исключение на уровне шлюза' in menu
assert 'Введите один из показанных выше IPv4-адресов сервера:' not in menu
assert 'повторно вводить его не нужно' in menu

# Secondary-transport onboarding is state-aware; first-run is not called directly
# by the normal VPN menus.
assert '"$AWG_FIRST_RUN" wizard' in menu
assert 'secondary_transport_setup' in menu
assert 'rollback_state="доступен"' in menu
assert 'rollback_state="нет предыдущего профиля"' in menu
assert 'Предыдущий AWG-профиль для быстрого отката отсутствует.' in menu
assert 'Архивные резервные копии установки и обновлений' in menu
assert 'if [[ ! -s "$previous" ]]' in menu
assert '5) secondary_transport_setup' in menu
assert '6) secondary_transport_setup' in menu
assert 'mihomo_initial_setup_flow secondary' in menu
assert 'Mihomo уже настроен как дополнительный транспорт' in menu
assert 'Активный транспорт: AWG' in menu
assert 'не изменён' in menu
vpn_function = menu[menu.index('vpn_menu(){'):menu.index('dns_menu(){')]
assert 'run_interactive "Первичная настройка транспорта" "$AWG_FIRST_RUN" wizard' not in vpn_function

# Transport selection policies.
assert 'AWG_SELECTION=/usr/local/sbin/awg-selection' in menu
for command in (
    '"$AWG_SELECTION" mode manual',
    '"$AWG_SELECTION" mode fixed awg mihomo',
    '"$AWG_SELECTION" mode fixed mihomo awg',
    '"$AWG_SELECTION" mode auto awg mihomo',
    '"$AWG_SELECTION" mode auto mihomo awg',
):
    assert command in menu
assert 'узел и страна Mihomo не переключаются автоматически' in menu

# Mihomo exact-node failover editor.
assert 'MIHOMO_NODE_POLICY=/usr/local/sbin/awg-mihomo-node-policy' in menu
assert '"$MIHOMO_NODE_POLICY" mode manual' in menu
assert '"$MIHOMO_NODE_POLICY" mode fixed "${nodes[@]}"' in menu
assert 'При отказе переход выполняется только слева направо' in menu
assert 'resolve_tsv_node_choice' in menu
assert 'select_tsv_node_dialog' in menu
assert 'Введите номер или ТОЧНОЕ имя узла из списка выше:' not in menu
assert 'Введите номер или ТОЧНОЕ имя узла из списка:' not in menu
assert 'Выберите узел. В строке сразу показаны тип и адрес сервера.' in menu
assert 'Выберите основной узел. В строке сразу показаны тип и адрес сервера.' in menu

# Existing-item operations use selectors instead of asking the user to
# remember and retype values already known to the gateway.
assert 'select_opencck_source' in menu
assert 'name="$(input "OpenCCK" "Имя источника:")"' not in menu
assert 'select_client' in menu
assert menu.count('ip="$(input "Клиенты" "IPv4 клиента:")"') == 1  # add only
assert 'select_chain_index' in menu
assert 'Номер элемента 1..' not in menu
assert 'Номер элемента 2..' not in menu
assert 'select_timezone' in menu
assert 'Введите точное имя часового пояса IANA:' not in menu
assert 'select_manual_domain' in menu
assert 'Введите домен для удаления:' not in menu
assert 'Введите домен для удаления из ручного списка:' not in menu
assert 'if (( count > 200 )); then' in menu

# OpenCCK unified input and system helpers.
assert '"$AWG_ROUTE" source add opencck "$target" --type domains --kind "$method"' in menu
assert 'Имя вводится один раз' in menu
assert 'AWG_TRAFFIC=/usr/local/sbin/awg-traffic' in menu
assert '"$AWG_TRAFFIC" status compact' in menu
assert 'timedatectl set-timezone "$zone"' in menu
assert '"$AWG_UPDATE" --yes mihomo' in menu
assert 'Произвольная самая новая версия из интернета не устанавливается.' in menu
assert 'cpu_temperature' in menu
assert 'memory_summary' in menu
assert 'system_uptime' in menu
assert 'localize_status_file' in menu
assert 'capture_ru' in menu
assert 'capture_ru "$AWG_ROUTE" status' in menu
assert 'capture_ru "$MIHOMO_CONFIGURE" status' in menu
assert 'capture_ru "$MIHOMO_NODE_POLICY" status' in menu
assert 'capture_ru "$AWG_SELECTION" status' in menu
assert 'capture_ru "$AWG_UPDATE" status' in menu
assert '=== Политика выбора транспорта ===' in menu
assert 'Активный транспорт:' in menu
assert 'URL подписки:' in menu
assert '"$MIHOMO_INSTALLER" --file "$path"' in menu

# Replacing a URL before Mihomo is configured must go through the initial
# source-profile wizard so Citadel/Remnawave cannot be staged as a generic URL.
assert "status=\"$(\"$MIHOMO_CONFIGURE\" status 2>/dev/null || true)\"" in menu
assert "grep -Fqx 'Configured: no'" in menu
assert '"$MIHOMO_CONFIGURE" provider candidate clear' in menu
assert 'mihomo_initial_setup_flow secondary' in menu
assert 'Citadel / Remnawave' in menu

# URL entry is intentionally visible during setup, while post-apply handling
# stays file-based and ordinary status/diagnostics continue to redact it.
assert 'Введённые символы отображаются как *' not in menu
assert 'После применения полный URL не выводится в обычном статусе и диагностике.' in menu
assert 'содержимым' in menu or 'содержимое отображается полностью' in menu

# URL handling stays file-based.
assert 'mktemp /run/awg-pbr/mihomo-url.XXXXXX' in menu
assert 'chmod 600 "$url_tmp"' in menu
assert "printf 'MIHOMO_PROVIDER_URL=%q\\n' \"$url\" >\"$url_tmp\"" in menu
assert 'provider-url set "$url"' not in menu
assert 'mktemp /run/awg-pbr/mihomo-init.XXXXXX' in menu
assert 'chmod 600 "$init_tmp"' in menu
assert '"$MIHOMO_CONFIGURE" init "$init_tmp"' in menu
assert 'MIHOMO_PROVIDER_PROFILE=%q' in menu
assert 'MIHOMO_PROVIDER_FORMAT=%q' in menu
assert '"$MIHOMO_CONFIGURE" provider format set "$provider_format"' in menu

# Top-level Mihomo menu contains only daily operations.
mihomo_start = menu.index('mihomo_menu(){')
mihomo_end = menu.index('selection_policy_menu(){', mihomo_start)
mihomo_block = menu[mihomo_start:mihomo_end]
for label in (
    '1 "Состояние Mihomo"',
    '2 "Подписка / источник"',
    '3 "Точка выхода / узел"',
    '4 "Резервирование узлов Mihomo"',
    '5 "Расширенные / восстановление"',
):
    assert label in mihomo_block, f"missing compact Mihomo item: {label}"
assert '"Активный транспорт"' not in mihomo_block
for legacy in (
    '"Mihomo / Multi-Transport"',
    '"Subscription / Provider"',
    '"Mihomo Node Failover"',
    '"Расширенные / Recovery"',
    '"Staged provider / candidate"',
    '"Offline engine recovery (.gz)"',
):
    assert legacy not in mihomo_block

# Active transport lives at VPN-routing level in both modes.
vpn_start = menu.index('vpn_menu(){')
vpn_end = menu.index('dns_menu(){', vpn_start)
vpn_block = menu[vpn_start:vpn_end]
assert vpn_block.count('"Активный транспорт"') == 2
assert '6 "Активный транспорт"' in vpn_block
assert '7 "Активный транспорт"' in vpn_block
assert '6) active_transport_menu' in vpn_block
assert '7) active_transport_menu' in vpn_block

# Restart action is transport-aware and safe in fresh/recovery installs.
assert 'restart_active_transport(){' in menu
assert menu.count('"Перезапустить активный транспорт и монитор состояния"') == 2
assert 'service="awg-quick@awg0.service"' in menu
assert 'service="awg-mihomo.service"' in menu
assert 'Активный транспорт пока не настроен.' in menu
assert 'Сначала используйте «Добавить / настроить транспорт».' in menu
assert 'systemctl restart awg-quick@awg0.service awg-pbr-health.service' not in vpn_block
assert 'Перезапустить awg0 и монитор состояния' not in vpn_block
assert '7 "Политика выбора транспорта"' in vpn_block
assert '8 "Политика выбора транспорта"' in vpn_block

# Mode-change result dialogs refresh the header after the command, so the
# backtitle cannot show the previous SELECTIVE/TRANSIT state.
assert 'capture_mode_change(){' in menu
assert 'capture_mode_change "$AWG_ROUTE" mode selective' in menu
assert 'capture_mode_change "$AWG_ROUTE" mode transit' in menu
mode_change_start = menu.index('capture_mode_change(){')
mode_change_end = menu.index('localize_status_file(){', mode_change_start)
mode_change_block = menu[mode_change_start:mode_change_end]
assert 'refresh_backtitle' in mode_change_block
assert 'dialog --backtitle "$BACKTITLE"' in mode_change_block

# Mode indicators remain explicit technical IDs, but labels/help are Russian.
for needle in (
    'BASE_BACKTITLE="AWG Pi Gateway v$VERSION"',
    'BACKTITLE="$BASE_BACKTITLE | Режим: $(operating_mode_badge "$mode")"',
    "РЕЖИМ:",
    'Главное меню — [$mode_badge]',
    '[ТЕКУЩИЙ]',
    'Режим работы [$mode_badge]',
    'VPN-маршрутизация [TRANSIT]',
    'VPN-маршрутизация [SELECTIVE]',
):
    assert needle in menu, f"missing operating-mode indicator: {needle}"

# Russian-first UI guard: these old English/mixed user-facing labels must not return.
for forbidden in (
    '"Mihomo / Multi-Transport"',
    '"Transport Selection Policy"',
    '"Активный transport"',
    '"Subscription / Provider"',
    '"Mihomo Node Failover"',
    '"Расширенные / Recovery"',
    '"Operating mode',
    '"DNS upstream"',
    '"Статистика traffic"',
    '"Выйти в обычный Shell"',
    '"Проверить / восстановить Mihomo engine"',
    '"Добавить / настроить transport"',
):
    assert forbidden not in menu, f"untranslated UI label returned: {forbidden}"

print("menu localization/safety checks: OK")
