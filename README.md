# AWG Pi Gateway
Raspberry Pi 4 AmneziaWG policy-routing gateway installer.

Для первого теста на Raspberry Pi: 

curl -fsSL https://raw.githubusercontent.com/karlinksk/awg-pi/563c768e43ff3648bb9d3ce4ed6d872a2dfe0f01/install.sh -o /tmp/install.sh

grep '^VERSION=' /tmp/install.sh

sudo env AWG_PI_REF=563c768e43ff3648bb9d3ce4ed6d872a2dfe0f01 bash /tmp/install.sh
