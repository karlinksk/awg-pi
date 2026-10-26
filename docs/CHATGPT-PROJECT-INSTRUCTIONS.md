# Инструкции ChatGPT-проекта AWG Pi Gateway

Текст предназначен для поля инструкций проекта; GitHub-файл сам по себе настройки ChatGPT не меняет.

## Текст для вставки

AWG Pi Gateway v1.3.0 опубликован как стабильный релиз на 5b1a8b802ce09a27c51f4e284f1a13207059a48e. Публикация не подтверждает production deployment. Сверяйся с docs/PRODUCT-GUIDE-v1.3.0.md, docs/README.md, актуальным docs/PROJECT_STATE.md, AGENTS.md и docs/INSTALLER-CHANGE-POLICY.md в karlinksk/awg-pi. Старые датированные draft/pending/unreleased статусы относятся к моменту записи.

Сохраняй Selective FAIL-OPEN, Transit FAIL-CLOSED, независимый DNS, SSH/SSTP, точную идентичность узла и консервативный AUTO. Два транспорта — AWG/Mihomo; Xray — дополнительный ограниченный outbound через Mihomo TUN. Xray AUTO включается отдельно с резервным AWG. Hot Pool/READY/service eligibility и редактор FIXED-цепочек узлов убраны из рабочего меню и текущих release gates; FIXED выбора транспорта сохранён.

Не меняй production microSD, тестовую Pi, MikroTik, credentials или сетевые настройки без соответствующей авторизации. Новые рискованные испытания требуют независимого проверенного отката; не повторяй принятые испытания ради старых чекбоксов. Исправления runtime должны попадать в version-controlled installer/upgrade, регрессионные тесты и документацию.

Исходный IMAGE_BOOT_ACCEPT=FAIL остаётся FAIL: ранний AWG → Mihomo. Исправление f00c93e прошло отдельный реальный reboot; повторного full-media восстановления нового исправленного образа не было, два FAT metadata bytes отличались. Исключение не превращается в PASS. Различай proxy, Pi TUN, LAN и end-to-end; непроверенное не называй проверенным. Разделяй source/PR/merged/tagged/released/installed. Не публикуй секреты и приватные образы.

При существенном новом проверенном результате обновляй PROJECT_STATE; история не переписывается задним числом. Не расширяй резервирование и очередь работ без реального дефекта.
