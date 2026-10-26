# Документация AWG Pi Gateway

**Статус на 2026-10-26:** стабильный [v1.3.0](https://github.com/karlinksk/awg-pi/releases/tag/v1.3.0) опубликован. Тег указывает на `5b1a8b802ce09a27c51f4e284f1a13207059a48e`. PR #165–167 merged; CI shell/awg-v31 успешен на их точных head-кандидатах. Отдельный main-push CI на коммите тега не заявляется. Production deployment не выполнялся.

## Действующие руководства

| Задача | Документ |
| --- | --- |
| Обзор | [README](../README.md) |
| Реализованная система, режимы, политики, команды | [Руководство](PRODUCT-GUIDE-v1.3.0.md) |
| Установка и обновление | [Инструкция](CLEAN-INSTALL-v1.3.0-CANDIDATE.md) — старое имя сохранено для ссылок |
| Подписки и узлы | [Mihomo/Xray](UNIFIED-MIHOMO-XRAY-NODES.md) |
| Ограничения Xray | [Адаптер](XRAY-VLESS-ADAPTER.md) |
| SSH-интерфейс | [Меню](SSH-MENU-DESIGN-v1.3.0.md) |
| Оповещения | [Telegram](AWG-NOTIFY.md) |
| Удалённое управление | [Desktop Commander](DESKTOP-COMMANDER.md) |
| Образы носителей | [Backup/restore](BACKUP-RESTORE.md) |

## Проверки и сопровождение

[Приёмка](RELEASE-ACCEPTANCE-MATRIX-v1.3.0.md), [испытания](TESTING-v1.3.0.md), [состояние проекта](PROJECT_STATE.md), [безопасность новых испытаний](RELEASE-TEST-SAFETY-v1.3.0.md), [installer policy](INSTALLER-CHANGE-POLICY.md), [AGENTS](../AGENTS.md), [инструкции ChatGPT](CHATGPT-PROJECT-INSTRUCTIONS.md).

## История

Документы ниже сохранены для аудита, не задают актуальный статус GitHub и не предписывают включать устаревшие функции:

- [EXPERIMENTAL-UNIFIED-AUTO-XRAY.md](EXPERIMENTAL-UNIFIED-AUTO-XRAY.md)
- [HOT-POOL-READY-AUTO.md](HOT-POOL-READY-AUTO.md)
- [READY-AUTO-CANARY.md](READY-AUTO-CANARY.md)
- [MIHOMO_SERVICE_ELIGIBILITY.md](MIHOMO_SERVICE_ELIGIBILITY.md)
- [MIHOMO_IP_CONNECT_REVIEW.md](MIHOMO_IP_CONNECT_REVIEW.md)
- [RC1-INTEGRATION-REVIEW.md](RC1-INTEGRATION-REVIEW.md)
- [ROADMAP-v1.2.0-TRANSIT.md](ROADMAP-v1.2.0-TRANSIT.md)
- [TESTING-v1.1.0.md](TESTING-v1.1.0.md)
- [TESTING-v1.2.0.md](TESTING-v1.2.0.md)

[RouterOS-шаблон v1.2.0](MIKROTIK-TRANSIT-v1.2.0.md) — отдельно применяемый справочный пример, не автоматическая настройка роутера. В действующих руководствах исторические записи свёрнуты и отделены от текущего текста.
