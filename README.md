# AWG Pi Gateway
Raspberry Pi 4 AmneziaWG policy-routing gateway installer.

Для первого теста на Raspberry Pi: 

curl -fsSL https://raw.githubusercontent.com/karlinksk/awg-pi/rc/v1.1.0-rc1/install.sh -o /tmp/install.sh

grep '^VERSION=' /tmp/install.sh

Получаем ответ: VERSION="1.1.0"

sudo env AWG_PI_REF=rc/v1.1.0-rc1 bash /tmp/install.sh
