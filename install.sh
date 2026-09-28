#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

VERSION="1.1.0"
PROJECT_REF="${AWG_PI_REF:-develop/v1.1.0}"
PROJECT_RAW_BASE="https://raw.githubusercontent.com/karlinksk/awg-pi/${PROJECT_REF}"
TTY=/dev/tty
STAGE="preflight"

VPN_IF="awg0"
CONF_DIR="/etc/amnezia/amneziawg"
CONF_FILE="$CONF_DIR/$VPN_IF.conf"
SRC_ROOT="/opt/amneziawg-src"
PBR_DIR="/etc/awg-pbr"
ENV_FILE="$PBR_DIR/env"
VPN_DOMAINS="$PBR_DIR/vpn-domains.txt"
DIRECT_DOMAINS="$PBR_DIR/direct-domains.txt"
CLIENTS_FILE="$PBR_DIR/clients.txt"
VPN_ENABLED_FILE="$PBR_DIR/vpn-enabled"
DNS_CONF="/etc/dnsmasq.d/99-awg-pbr.conf"
DNS_DOMAINS_CONF="/etc/dnsmasq.d/99-awg-pbr-domains.conf"
NFT_FILE="/etc/nftables.d/99-awg-pbr.nft"
SETUP_SCRIPT="/usr/local/sbin/awg-pbr-setup"
FAILOPEN_SCRIPT="/usr/local/sbin/awg-pbr-failopen"
HEALTH_SCRIPT="/usr/local/sbin/awg-pbr-health"
ROUTE_CLI="/usr/local/sbin/awg-route"
UPDATE_SCRIPT="/usr/local/sbin/awg-update"
SETUP_SERVICE="/etc/systemd/system/awg-pbr-setup.service"
HEALTH_SERVICE="/etc/systemd/system/awg-pbr-health.service"
SYSCTL_FILE="/etc/sysctl.d/99-awg-pbr.conf"
WATCHDOG_DROPIN="/etc/systemd/system.conf.d/99-awg-gateway-watchdog.conf"
LOG_DIR="/var/log/awg-gateway"
BACKUP_DIR="/var/backups/awg-gateway"
VPN_MARK="0x100"
HEALTH_MARK="0x101"
VPN_TABLE="100"
HEALTH_TABLE="101"
HEALTH_INTERVAL="5"
HANDSHAKE_MAX_AGE="180"

R='\033[0m'; B='\033[1m'; G='\033[32m'; Y='\033[33m'; C='\033[36m'; E='\033[31m'
log(){ printf "%b%s%b\n" "$C" "$*" "$R"; }
ok(){ printf "%b[OK] %s%b\n" "$G" "$*" "$R"; }
warn(){ printf "%b[WARN] %s%b\n" "$Y" "$*" "$R"; }
err(){ printf "%b[ERROR] %s%b\n" "$E" "$*" "$R" >&2; }
die(){ err "$*"; printf "Этап: %s\n" "$STAGE" >&2; [[ -n "${INSTALL_REPORT:-}" ]] && printf "Журнал: %s\n" "$INSTALL_REPORT" >&2; exit 1; }

on_err(){
  local rc=$? line="${BASH_LINENO[0]:-?}"
  err "Непредвиденная ошибка на строке $line, код $rc"
  printf "Этап: %s\n" "$STAGE" >&2
  [[ -n "${INSTALL_REPORT:-}" ]] && printf "Журнал: %s\n" "$INSTALL_REPORT" >&2
  exit "$rc"
}
trap on_err ERR

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Запустите установщик через sudo/root" >&2; exit 1; }
[[ -r "$TTY" ]] || { echo "Нужен интерактивный терминал" >&2; exit 1; }

mkdir -p "$LOG_DIR" "$BACKUP_DIR"
chmod 700 "$LOG_DIR" "$BACKUP_DIR"
INSTALL_REPORT="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
touch "$INSTALL_REPORT"; chmod 600 "$INSTALL_REPORT"
exec > >(tee -a "$INSTALL_REPORT") 2>&1

ask(){
  local p="$1" d="${2:-}" v
  if [[ -n "$d" ]]; then
    read -r -p "$p [$d]: " v <"$TTY"
    REPLY="${v:-$d}"
  else
    read -r -p "$p: " v <"$TTY"
    REPLY="$v"
  fi
}
confirm(){
  local p="$1" d="${2:-N}" v s
  [[ "$d" =~ ^[YyДд]$ ]] && s="Y/n" || s="y/N"
  read -r -p "$p [$s]: " v <"$TTY"
  v="${v:-$d}"
  [[ "$v" =~ ^([Yy]|[Дд][Аа]?)$ ]]
}
valid_ipv4(){
  local IFS=. a b c d
  read -r a b c d <<<"$1" || return 1
  [[ $a =~ ^[0-9]+$ && $b =~ ^[0-9]+$ && $c =~ ^[0-9]+$ && $d =~ ^[0-9]+$ ]] || return 1
  ((a<=255 && b<=255 && c<=255 && d<=255))
}
valid_cidr4(){
  local x="$1" ip="${x%/*}" p="${x#*/}"
  [[ "$x" == */* ]] || return 1
  valid_ipv4 "$ip" && [[ "$p" =~ ^[0-9]+$ ]] && ((p>=0 && p<=32))
}
in_cidr(){
  python3 - "$1" "$2" <<'PY'
import ipaddress, sys
try:
    print("yes" if ipaddress.ip_address(sys.argv[1]) in ipaddress.ip_network(sys.argv[2], strict=False) else "no")
except Exception:
    print("no")
PY
}
first_working_url(){
  local u
  for u in "$@"; do
    if curl -4fsSI --max-time 8 "$u" >/dev/null 2>&1; then return 0; fi
  done
  return 1
}

printf "%b=== AmneziaWG Raspberry Pi 4 Policy Gateway Installer v%s ===%b\n" "$B" "$VERSION" "$R"
printf "Архитектура: Archer C64 = основной DHCP/NAT; Raspberry Pi = выборочный PBR-шлюз.\n"
printf "Default = DIRECT. Домены из VPN-list = AmneziaWG. VPN недоступен = FAIL-OPEN напрямую.\n"
printf "IPv6 в этой версии не маршрутизируется.\n\n"
printf "Журнал установки: %s\n\n" "$INSTALL_REPORT"

UPGRADE_EXISTING=0
AUTO_UPGRADE="${AWG_PI_UPGRADE_AUTO:-0}"
EXISTING_VERSION="$(cat /etc/awg-pbr/version 2>/dev/null || true)"
if [[ -f "$ENV_FILE" && -f "$CONF_FILE" ]]; then
  printf "Обнаружена существующая AWG Pi Gateway: %s\n" "${EXISTING_VERSION:-версия до v1.1.0}"
  if [[ "$AUTO_UPGRADE" == 1 ]] || confirm "Выполнить безопасное обновление существующей установки до v$VERSION с сохранением AWG-конфига, доменов и клиентов?" "Y"; then
    UPGRADE_EXISTING=1
    ok "Режим обновления: пользовательские списки и $CONF_FILE будут сохранены"
  else
    die "Обновление отменено пользователем"
  fi
fi

# -----------------------------------------------------------------------------
# 1. Preflight
# -----------------------------------------------------------------------------
STAGE="предварительная проверка Raspberry Pi"
log "[1/12] Предварительные проверки"

MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
[[ "$MODEL" == *"Raspberry Pi 4 Model B"* ]] || die "Ожидалась Raspberry Pi 4 Model B, обнаружено: ${MODEL:-неизвестно}"
ok "$MODEL"

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) GO_ARCH="arm64" ;;
  *) die "Для этого проекта требуется 64-битная Raspberry Pi OS (aarch64). Сейчас: $ARCH" ;;
esac
ok "Архитектура ARM64: $ARCH"

[[ -r /etc/os-release ]] || die "Не найден /etc/os-release"
# shellcheck disable=SC1091
source /etc/os-release
case "${ID:-}:${ID_LIKE:-}" in
  *debian*|*raspbian*) ;;
  *) die "Нужна Raspberry Pi OS/Debian. Обнаружено: ${PRETTY_NAME:-unknown}" ;;
esac
ok "ОС: ${PRETTY_NAME:-$ID}"

[[ "$(cat /proc/1/comm 2>/dev/null)" == "systemd" ]] || die "PID 1 не systemd"
command -v systemctl >/dev/null || die "systemctl не найден"

FREE_KB="$(df -Pk / | awk 'NR==2{print $4}')"
(( FREE_KB >= 1500000 )) || die "Недостаточно места: нужно минимум ~1.5 GB свободно на /"
ok "Свободное место: $((FREE_KB/1024)) MB"

if ip -6 route show default | grep -q '^default'; then
  err "Обнаружен IPv6 default route. Текущая архитектура рассчитана только на IPv4."
  ip -6 route show default
  die "Отключите IPv6/RA на Archer C64 для этой схемы либо вернитесь к установке после отключения IPv6"
else
  ok "IPv6 default route отсутствует"
fi

if ! first_working_url https://github.com https://go.dev; then
  die "Нет доступа к GitHub/go.dev. Без него установка AmneziaWG невозможна"
fi
ok "Интернет до источников установки доступен"

if command -v timedatectl >/dev/null; then
  NTP_SYNC="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
  [[ "$NTP_SYNC" == "yes" ]] && ok "Системное время синхронизировано" || warn "NTP пока не подтверждён; неверное время может мешать HTTPS"
fi

# -----------------------------------------------------------------------------
# 2. Dependencies
# -----------------------------------------------------------------------------
STAGE="установка системных пакетов"
log "[2/12] Системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl git jq build-essential make pkg-config \
  iproute2 iputils-ping dnsutils nftables dnsmasq procps \
  python3-minimal openssl dialog

command -v nft >/dev/null || die "nft не установлен"
command -v dnsmasq >/dev/null || die "dnsmasq не установлен"
command -v dig >/dev/null || die "dig не установлен"
dnsmasq --version | grep -qi nftset || die "Установленный dnsmasq собран без поддержки nftset"
ok "dnsmasq поддерживает nftset"

# -----------------------------------------------------------------------------
# 3. Go
# -----------------------------------------------------------------------------
STAGE="установка Go"
log "[3/12] Go"
install_go(){
  local j f s t
  j="$(curl -fsSL --max-time 30 https://go.dev/dl/?mode=json)"
  f="$(jq -r --arg a "$GO_ARCH" '.[0].files[]|select(.os=="linux" and .arch==$a and .kind=="archive")|.filename' <<<"$j" | head -1)"
  s="$(jq -r --arg a "$GO_ARCH" '.[0].files[]|select(.os=="linux" and .arch==$a and .kind=="archive")|.sha256' <<<"$j" | head -1)"
  [[ -n "$f" && "$f" != null && -n "$s" && "$s" != null ]] || die "Не удалось определить актуальную стабильную версию Go"
  t="/tmp/$f"
  curl -fL --retry 3 "https://go.dev/dl/$f" -o "$t"
  echo "$s  $t" | sha256sum -c -
  rm -rf /usr/local/go
  tar -C /usr/local -xzf "$t"
  rm -f "$t"
  export PATH=/usr/local/go/bin:$PATH
  printf 'export PATH=/usr/local/go/bin:$PATH\n' >/etc/profile.d/go.sh
}
install_go
ok "$(go version)"

# -----------------------------------------------------------------------------
# 4. Build/install AmneziaWG stable tags
# -----------------------------------------------------------------------------
STAGE="установка AmneziaWG"
log "[4/12] AmneziaWG"
GO_REPO="https://github.com/amnezia-vpn/amneziawg-go.git"
TOOLS_REPO="https://github.com/amnezia-vpn/amneziawg-tools.git"
latest_tag(){
  git ls-remote --tags --refs "$1" 'refs/tags/v*' \
    | awk -F/ '{print $3}' \
    | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+
    | sort -V | tail -1
}
sync_repo(){
  local repo="$1" dir="$2" tag="$3"
  mkdir -p "$SRC_ROOT"
  if [[ -d "$dir/.git" ]]; then
    git -C "$dir" fetch --tags --prune origin
    git -C "$dir" checkout -f "$tag"
    git -C "$dir" reset --hard "$tag"
  else
    rm -rf "$dir"
    git clone --depth 1 --branch "$tag" "$repo" "$dir"
  fi
}

GO_TAG="$(latest_tag "$GO_REPO")"
TOOLS_TAG="$(latest_tag "$TOOLS_REPO")"
[[ -n "$GO_TAG" && -n "$TOOLS_TAG" ]] || die "Не удалось получить стабильные теги AmneziaWG"
printf "Найдены стабильные теги: amneziawg-go=%s, tools=%s\n" "$GO_TAG" "$TOOLS_TAG"
if [[ "$AUTO_UPGRADE" != 1 ]]; then
  confirm "Установить эти стабильные версии?" "Y" || die "Установка отменена пользователем"
fi

sync_repo "$GO_REPO" "$SRC_ROOT/amneziawg-go" "$GO_TAG"
make -C "$SRC_ROOT/amneziawg-go" clean >/dev/null 2>&1 || true
make -C "$SRC_ROOT/amneziawg-go"
make -C "$SRC_ROOT/amneziawg-go" PREFIX=/usr install

sync_repo "$TOOLS_REPO" "$SRC_ROOT/amneziawg-tools" "$TOOLS_TAG"
make -C "$SRC_ROOT/amneziawg-tools/src" clean >/dev/null 2>&1 || true
make -C "$SRC_ROOT/amneziawg-tools/src"
make -C "$SRC_ROOT/amneziawg-tools/src" install PREFIX=/usr WITH_WGQUICK=yes WITH_SYSTEMDUNITS=yes
systemctl daemon-reload

command -v awg >/dev/null || die "awg не установлен"
command -v awg-quick >/dev/null || die "awg-quick не установлен"
command -v amneziawg-go >/dev/null || die "amneziawg-go не установлен"
ok "$(awg --version 2>/dev/null || echo 'awg установлен')"
ok "$(amneziawg-go --version 2>/dev/null || echo 'amneziawg-go установлен')"

# -----------------------------------------------------------------------------
# 5. Import and validate AWG config
# -----------------------------------------------------------------------------
STAGE="импорт конфигурации AmneziaWG"
log "[5/12] Конфигурация AmneziaWG"
mkdir -p "$CONF_DIR" "$PBR_DIR" /etc/nftables.d
chmod 700 "$CONF_DIR" "$PBR_DIR"

if [[ -f "$CONF_FILE" ]]; then
  cp -a "$CONF_FILE" "$CONF_FILE.bak.$(date +%Y%m%d-%H%M%S)"
fi

if (( UPGRADE_EXISTING == 0 )); then
printf "1) указать путь к .conf\n2) вставить конфиг в терминал\n"
ask "Способ импорта" "2"
mode="$REPLY"
tmp="$(mktemp --suffix=.conf)"
cleanup_tmp(){ rm -f "$tmp" "${tmp}.new" 2>/dev/null || true; }
trap cleanup_tmp EXIT
case "$mode" in
  1)
    ask "Полный путь к .conf"
    [[ -f "$REPLY" ]] || die "Файл не найден: $REPLY"
    cp "$REPLY" "$tmp"
    ;;
  2)
    printf "Вставьте конфиг. Завершите отдельной строкой __END__\n"
    : >"$tmp"
    while IFS= read -r line <"$TTY"; do
      [[ "$line" == "__END__" ]] && break
      printf '%s\n' "$line" >>"$tmp"
    done
    ;;
  *) die "Неверный способ импорта" ;;
esac
sed -i 's/\r$//' "$tmp"

[[ "$(grep -Ec '^\s*\[Interface\]\s*$' "$tmp")" -eq 1 ]] || die "Конфиг должен содержать ровно один [Interface]"
[[ "$(grep -Ec '^\s*\[Peer\]\s*$' "$tmp")" -ge 1 ]] || die "В конфиге нет [Peer]"
grep -qE '^\s*PrivateKey\s*=' "$tmp" || die "В [Interface] нет PrivateKey"
grep -qE '^\s*Address\s*=' "$tmp" || die "В [Interface] нет Address"
grep -qE '^\s*PublicKey\s*=' "$tmp" || die "В [Peer] нет PublicKey"
grep -qE '^\s*Endpoint\s*=' "$tmp" || die "В [Peer] нет Endpoint"
grep -qE '^\s*AllowedIPs\s*=.*0\.0\.0\.0/0' "$tmp" || die "Для PBR peer должен разрешать 0.0.0.0/0 в AllowedIPs"

if grep -qE '^\s*(Jc|Jmin|Jmax|S1|H1)\s*=' "$tmp"; then
  ok "Обнаружены параметры AmneziaWG"
else
  warn "Специфические параметры AWG не обнаружены; убедитесь, что экспортирован именно профиль AmneziaWG"
fi

if grep -qE '^\s*PersistentKeepalive\s*=' "$tmp"; then
  ok "PersistentKeepalive уже задан"
else
  warn "PersistentKeepalive отсутствует"
  if confirm "Добавить PersistentKeepalive = 25 в первый [Peer]?" "Y"; then
    awk '
      BEGIN{inp=0; done=0}
      /^[[:space:]]*\[Peer\][[:space:]]*$/ { if(!done){inp=1}; print; next }
      /^[[:space:]]*\[/ { if(inp && !done){print "PersistentKeepalive = 25"; done=1; inp=0}; print; next }
      {print}
      END{if(inp && !done) print "PersistentKeepalive = 25"}
    ' "$tmp" >"${tmp}.new"
    mv "${tmp}.new" "$tmp"
    ok "Добавлен PersistentKeepalive = 25"
  fi
fi

# We own routing and DNS. Remove DNS/Table from imported Interface and force Table=off.
awk '
  BEGIN{inif=0; inserted=0}
  /^[[:space:]]*\[Interface\][[:space:]]*$/ {print; inif=1; next}
  /^[[:space:]]*\[/ && $0 !~ /^[[:space:]]*\[Interface\][[:space:]]*$/ {
    if(inif && !inserted){print "Table = off"; inserted=1}
    inif=0
  }
  inif && /^[[:space:]]*Table[[:space:]]*=/ {next}
  inif && /^[[:space:]]*DNS[[:space:]]*=/ {next}
  {print}
  END{if(inif && !inserted) print "Table = off"}
' "$tmp" >"${tmp}.new"
mv "${tmp}.new" "$tmp"
install -m 600 "$tmp" "$CONF_FILE"
cleanup_tmp
trap - EXIT
else
  ok "Существующий AWG-конфиг сохранён: $CONF_FILE"
fi

# Parser-level validation without bringing the tunnel up yet.
if ! awg-quick strip "$CONF_FILE" >/dev/null 2>&1; then
  die "awg-quick не смог разобрать импортированный конфиг. Проверьте синтаксис и параметры версии AWG"
fi
ok "Конфиг валиден для awg-quick; Table=off включён; DNS управляется отдельно"

# -----------------------------------------------------------------------------
# 6. LAN/Archer parameters
# -----------------------------------------------------------------------------
STAGE="проверка локальной сети"
log "[6/12] Archer C64 и локальная сеть"
if (( UPGRADE_EXISTING == 1 )); then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  : "${LAN_IF:?В существующем env отсутствует LAN_IF}"
  : "${LAN_CIDR:?В существующем env отсутствует LAN_CIDR}"
  : "${PI_IP:?В существующем env отсутствует PI_IP}"
  : "${ROUTER_IP:?В существующем env отсутствует ROUTER_IP}"
  : "${UPSTREAM_DNS:?В существующем env отсутствует UPSTREAM_DNS}"
  DNS_REDIRECT="${DNS_REDIRECT:-1}"
  HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"
  HANDSHAKE_MAX_AGE="${HANDSHAKE_MAX_AGE:-180}"
  LAN_MAC="$(cat "/sys/class/net/$LAN_IF/address" 2>/dev/null || true)"
  ip link show "$LAN_IF" >/dev/null 2>&1 || die "Сохранённый LAN интерфейс $LAN_IF отсутствует"
  ip -o -4 addr show dev "$LAN_IF" | grep -qE "[[:space:]]${PI_IP}/" || die "Сохранённый IP Raspberry Pi $PI_IP сейчас не назначен $LAN_IF"
  [[ "$(in_cidr "$PI_IP" "$LAN_CIDR")" == "yes" ]] || die "Сохранённый IP $PI_IP не принадлежит $LAN_CIDR"
  if ! ping -4 -c 2 -W 2 "$ROUTER_IP" >/dev/null 2>&1; then
    die "Сохранённый роутер $ROUTER_IP не отвечает"
  fi
  IFS=',' read -ra DNSA <<<"$UPSTREAM_DNS"
  DNS_OK=0
  for d in "${DNSA[@]}"; do
    d="${d//[[:space:]]/}"
    valid_ipv4 "$d" || die "В существующем env неверный DNS: $d"
    if dig +time=3 +tries=1 +short A example.com @"$d" | grep -qE '^[0-9]+\.'; then DNS_OK=$((DNS_OK+1)); fi
  done
  (( DNS_OK > 0 )) || die "Upstream DNS из существующей конфигурации не отвечает"
  touch "$VPN_DOMAINS" "$DIRECT_DOMAINS" "$CLIENTS_FILE"
  chmod 600 "$VPN_DOMAINS" "$DIRECT_DOMAINS" "$CLIENTS_FILE"
  [[ -f "$VPN_ENABLED_FILE" ]] || echo 1 >"$VPN_ENABLED_FILE"
  chmod 600 "$VPN_ENABLED_FILE"
  ok "Сетевая конфигурация сохранена: Pi=$PI_IP, Router=$ROUTER_IP, LAN=$LAN_CIDR"
else
printf "\nIPv4 интерфейсы:\n"
ip -br -4 addr show | sed 's/^/  /'
printf "Default route:\n"
ip -4 route show default | sed 's/^/  /'

UPLINK_IF="$(ip -4 route show default | awk 'NR==1{for(i=1;i<=NF;i++)if($i=="dev"){print $(i+1);exit}}')"
UPLINK_GW="$(ip -4 route show default | awk 'NR==1{for(i=1;i<=NF;i++)if($i=="via"){print $(i+1);exit}}')"
[[ -n "$UPLINK_IF" && -n "$UPLINK_GW" ]] || die "Не найден обычный IPv4 default route через Archer C64"

ask "LAN/uplink интерфейс Raspberry Pi" "$UPLINK_IF"
LAN_IF="$REPLY"
ip link show "$LAN_IF" >/dev/null 2>&1 || die "Нет интерфейса $LAN_IF"
[[ "$LAN_IF" == "eth0" ]] || warn "Для Raspberry Pi 4 рекомендуется проводной eth0; выбран $LAN_IF"

PI_CIDR="$(ip -o -4 addr show dev "$LAN_IF" scope global | awk 'NR==1{print $4}')"
[[ -n "$PI_CIDR" ]] || die "На $LAN_IF нет IPv4 адреса"
PI_IP="${PI_CIDR%/*}"
LAN_CIDR="$(ip -4 route show dev "$LAN_IF" proto kernel scope link | awk -v ip="$PI_IP" 'index($0,"src "ip){print $1;exit}')"
[[ -n "$LAN_CIDR" ]] || LAN_CIDR="$PI_CIDR"
LAN_MAC="$(cat "/sys/class/net/$LAN_IF/address")"

printf "\nMAC Raspberry Pi (%s): %s\n" "$LAN_IF" "$LAN_MAC"
printf "Текущий адрес: %s\n" "$PI_CIDR"
printf "Текущий роутер: %s\n" "$UPLINK_GW"

ask "Постоянный IPv4 Raspberry Pi (должен быть зарезервирован на Archer C64)" "$PI_IP"
PI_IP="$REPLY"
valid_ipv4 "$PI_IP" || die "Неверный IPv4 Raspberry Pi"
ip -o -4 addr show dev "$LAN_IF" | grep -qE "[[:space:]]${PI_IP}/" || die "$PI_IP сейчас не назначен $LAN_IF. Сначала создайте DHCP reservation на Archer C64 и обновите lease/перезагрузите Pi"

ask "Домашняя IPv4 подсеть" "$LAN_CIDR"
LAN_CIDR="$REPLY"
valid_cidr4 "$LAN_CIDR" || die "Неверная подсеть: $LAN_CIDR"
[[ "$(in_cidr "$PI_IP" "$LAN_CIDR")" == "yes" ]] || die "IP Raspberry Pi $PI_IP не принадлежит $LAN_CIDR"

ask "IP Archer C64" "$UPLINK_GW"
ROUTER_IP="$REPLY"
valid_ipv4 "$ROUTER_IP" || die "Неверный IP роутера"
[[ "$(in_cidr "$ROUTER_IP" "$LAN_CIDR")" == "yes" ]] || die "IP Archer $ROUTER_IP не принадлежит $LAN_CIDR"

if ! ping -4 -c 2 -W 2 "$ROUTER_IP" >/dev/null 2>&1; then
  die "Archer C64 ($ROUTER_IP) не отвечает с Raspberry Pi"
fi
ok "Archer C64 доступен: $ROUTER_IP"

printf "\nНа Archer C64 должна быть DHCP Reservation:\n  MAC: %s\n  IP:  %s\n" "$LAN_MAC" "$PI_IP"
confirm "Вы уже закрепили этот IP за MAC Raspberry Pi на Archer C64?" "N" || die "Сначала настройте DHCP Reservation на Archer C64, затем повторите установку"

ask "Upstream DNS для Raspberry Pi через запятую" "1.1.1.1,9.9.9.9"
UPSTREAM_DNS="$REPLY"
IFS=',' read -ra DNSA <<<"$UPSTREAM_DNS"
DNS_OK=0
for d in "${DNSA[@]}"; do
  d="${d//[[:space:]]/}"
  valid_ipv4 "$d" || die "Неверный DNS: $d"
  if dig +time=3 +tries=1 +short A example.com "@$d" | grep -qE '^[0-9]+\.'; then
    ok "Upstream DNS отвечает: $d"
    DNS_OK=$((DNS_OK+1))
  else
    warn "Upstream DNS не ответил: $d"
  fi
done
(( DNS_OK > 0 )) || die "Ни один выбранный upstream DNS не работает напрямую"

if confirm "Перехватывать обычный DNS TCP/UDP 53 у клиентов, использующих Pi как gateway?" "Y"; then
  DNS_REDIRECT=1
else
  DNS_REDIRECT=0
fi

cat >"$ENV_FILE" <<EOF
LAN_IF='$LAN_IF'
LAN_CIDR='$LAN_CIDR'
PI_IP='$PI_IP'
ROUTER_IP='$ROUTER_IP'
VPN_IF='$VPN_IF'
VPN_MARK='$VPN_MARK'
HEALTH_MARK='$HEALTH_MARK'
VPN_TABLE='$VPN_TABLE'
HEALTH_TABLE='$HEALTH_TABLE'
DNS_REDIRECT='$DNS_REDIRECT'
UPSTREAM_DNS='$UPSTREAM_DNS'
HEALTH_INTERVAL='$HEALTH_INTERVAL'
HANDSHAKE_MAX_AGE='$HANDSHAKE_MAX_AGE'
LOG_DIR='$LOG_DIR'
EOF
chmod 600 "$ENV_FILE"
touch "$VPN_DOMAINS" "$DIRECT_DOMAINS" "$CLIENTS_FILE"
chmod 600 "$VPN_DOMAINS" "$DIRECT_DOMAINS" "$CLIENTS_FILE"
echo 1 >"$VPN_ENABLED_FILE"
chmod 600 "$VPN_ENABLED_FILE"
fi

# -----------------------------------------------------------------------------
# 7. sysctl, watchdog, nftables base setup
# -----------------------------------------------------------------------------
STAGE="настройка маршрутизации и firewall"
log "[7/12] IPv4 forwarding, nftables, watchdog"
cat >"$SYSCTL_FILE" <<EOF
net.ipv4.ip_forward=1
net.ipv4.conf.all.src_valid_mark=1
net.ipv4.conf.all.rp_filter=2
net.ipv4.conf.default.rp_filter=2
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0
net.ipv4.conf.$LAN_IF.send_redirects=0
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.default.accept_redirects=0
EOF
sysctl --system >/dev/null
[[ "$(sysctl -n net.ipv4.ip_forward)" == "1" ]] || die "Не удалось включить net.ipv4.ip_forward"
ok "IPv4 forwarding включён"

if (( UPGRADE_EXISTING == 1 )); then
  if [[ -f "$WATCHDOG_DROPIN" ]]; then
    ok "Watchdog: сохраняем существующую настройку"
  else
    warn "Watchdog ранее не был настроен; при обновлении состояние не меняется"
  fi
elif confirm "Включить аппаратный/systemd watchdog Raspberry Pi?" "Y"; then
  mkdir -p "$(dirname "$WATCHDOG_DROPIN")"
  cat >"$WATCHDOG_DROPIN" <<'EOF'
[Manager]
RuntimeWatchdogSec=20s
RebootWatchdogSec=10min
EOF
  systemctl daemon-reexec
  sleep 1
  WD="$(systemctl show -p RuntimeWatchdogUSec --value 2>/dev/null || true)"
  [[ -n "$WD" && "$WD" != "0" ]] && ok "Watchdog включён: $WD" || warn "systemd не подтвердил RuntimeWatchdog; система продолжит работу без гарантии hardware watchdog"
fi

cat >"$SETUP_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC1091
source /etc/awg-pbr/env
CLIENTS=/etc/awg-pbr/clients.txt
NFT=/etc/nftables.d/99-awg-pbr.nft

nft delete table inet awg_pbr 2>/dev/null || true
CLIENT_FILTER=""
if grep -Ev '^\s*(#|$)' "$CLIENTS" 2>/dev/null | grep -q .; then
  CLIENT_FILTER='ip saddr @clients4 '
fi

{
cat <<NFT
# Managed by awg-pbr-setup. This script owns only table inet awg_pbr.
table inet awg_pbr {
  set vpn4 {
    type ipv4_addr
    flags timeout
    timeout 15m
  }
  set direct4 {
    type ipv4_addr
    flags timeout
    timeout 15m
  }
  set clients4 {
    type ipv4_addr
  }
  set source4 {
    type ipv4_addr
    flags interval
  }

  chain prerouting_mark {
    type filter hook prerouting priority mangle; policy accept;
    iifname "$LAN_IF" ${CLIENT_FILTER}ip daddr @source4 meta mark set $VPN_MARK
    iifname "$LAN_IF" ${CLIENT_FILTER}ip daddr @vpn4 meta mark set $VPN_MARK
    iifname "$LAN_IF" ip daddr @direct4 meta mark set 0x0
  }

  chain dns_redirect {
    type nat hook prerouting priority dstnat; policy accept;
NFT
if [[ "$DNS_REDIRECT" == 1 ]]; then
  printf '    iifname "%s" udp dport 53 redirect to :53\n' "$LAN_IF"
  printf '    iifname "%s" tcp dport 53 redirect to :53\n' "$LAN_IF"
fi
cat <<NFT
  }

  chain postrouting_nat {
    type nat hook postrouting priority srcnat; policy accept;
    ip saddr $LAN_CIDR oifname "$VPN_IF" masquerade
    ip saddr $LAN_CIDR oifname "$LAN_IF" masquerade
  }
}
NFT
} >"$NFT"

nft -c -f "$NFT"
nft -f "$NFT"

while IFS= read -r ip; do
  ip="${ip%%#*}"; ip="${ip//[[:space:]]/}"
  [[ -z "$ip" ]] && continue
  nft add element inet awg_pbr clients4 "{ $ip }"
done <"$CLIENTS"

# Policy rule itself is controlled by health monitor for fail-open behavior.
while ip -4 rule del priority 100 fwmark "$VPN_MARK" lookup "$VPN_TABLE" 2>/dev/null; do :; done
ip -4 route flush table "$VPN_TABLE" 2>/dev/null || true
EOF
chmod 755 "$SETUP_SCRIPT"

cat >"$FAILOPEN_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC1091
source /etc/awg-pbr/env
while ip -4 rule del priority 100 fwmark "$VPN_MARK" lookup "$VPN_TABLE" 2>/dev/null; do :; done
mkdir -p /run/awg-pbr
echo down >/run/awg-pbr/health.state
EOF
chmod 755 "$FAILOPEN_SCRIPT"

cat >"$SETUP_SERVICE" <<'EOF'
[Unit]
Description=AmneziaWG policy-routing base setup
Wants=network-online.target
After=network-online.target
Before=dnsmasq.service awg-quick@awg0.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/awg-pbr-setup

[Install]
WantedBy=multi-user.target
EOF

# -----------------------------------------------------------------------------
# 8. DNS and management CLI
# -----------------------------------------------------------------------------
STAGE="настройка DNS и команд управления"
log "[8/12] dnsmasq + awg-route"

cat >"$DNS_CONF" <<EOF
# Managed by amneziawg-pi-gateway-installer
interface=$LAN_IF
bind-dynamic
listen-address=$PI_IP
listen-address=127.0.0.1
port=53
domain-needed
bogus-priv
no-resolv
cache-size=4000
max-cache-ttl=300
max-ttl=300
EOF
for d in "${DNSA[@]}"; do
  d="${d//[[:space:]]/}"
  printf 'server=%s\n' "$d" >>"$DNS_CONF"
done
: >"$DNS_DOMAINS_CONF"

dnsmasq --test || die "dnsmasq не принимает подготовленную конфигурацию"

cat >"$ROUTE_CLI" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"
# shellcheck disable=SC1091
source /etc/awg-pbr/env
VD=/etc/awg-pbr/vpn-domains.txt
DD=/etc/awg-pbr/direct-domains.txt
CF=/etc/awg-pbr/clients.txt
VE=/etc/awg-pbr/vpn-enabled
DC=/etc/dnsmasq.d/99-awg-pbr-domains.conf
SETUP=/usr/local/sbin/awg-pbr-setup
FAILOPEN=/usr/local/sbin/awg-pbr-failopen
HEALTH_SERVICE=awg-pbr-health.service
LOG_DIR="${LOG_DIR:-/var/log/awg-gateway}"
mkdir -p "$LOG_DIR"; chmod 700 "$LOG_DIR"

usage(){ cat <<USAGE
Управление AmneziaWG Policy Gateway

Доменные правила:
  awg-route vpn add DOMAIN
  awg-route vpn del DOMAIN
  awg-route direct add DOMAIN
  awg-route direct del DOMAIN
  awg-route list

Клиенты (опциональная allow-list):
  awg-route client add IPv4
  awg-route client del IPv4
  awg-route client list
  Пустой список = правила VPN применяются ко всем устройствам, использующим Pi как gateway.

VPN policy:
  awg-route vpn on
  awg-route vpn off

Проверки/обслуживание:
  awg-route status
  awg-route test DOMAIN
  awg-route reload
  awg-route diagnostics
  awg-route logs [N]

DOMAIN без wildcard уже включает его поддомены в dnsmasq.
USAGE
}

valid_ipv4(){
  local IFS=. a b c d
  read -r a b c d <<<"$1" || return 1
  [[ $a =~ ^[0-9]+$ && $b =~ ^[0-9]+$ && $c =~ ^[0-9]+$ && $d =~ ^[0-9]+$ ]] || return 1
  ((a<=255 && b<=255 && c<=255 && d<=255))
}
normalize_domain(){
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -E 's#^https?://##; s#/.*$##; s/^\*\.//; s/^\.//; s/\.$//'
}
valid_domain(){
  [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]
}
prune_reports(){
  find "$LOG_DIR" -maxdepth 1 -type f -name 'diagnostics-*.txt' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | awk 'NR>10{sub(/^[^ ]+ /,""); print}' | xargs -r rm -f
}
handshake_age(){
  local hs now
  hs="$(awg show "$VPN_IF" latest-handshakes 2>/dev/null | awk '$2>m{m=$2}END{print m+0}')"
  [[ "$hs" -gt 0 ]] || { echo -1; return; }
  now="$(date +%s)"; echo $((now-hs))
}
policy_present(){ ip -4 rule show | grep -Eq '(^| )100:.*fwmark (0x100|256).*lookup (100|awgvpn)'; }
health_state(){ cat /run/awg-pbr/health.state 2>/dev/null || echo unknown; }

regen_domains(){
  : >"$DC"
  while IFS= read -r d; do
    d="${d%%#*}"; d="${d//[[:space:]]/}"
    [[ -z "$d" ]] && continue
    printf 'nftset=/%s/4#inet#awg_pbr#vpn4\n' "$d" >>"$DC"
  done <"$VD"
  while IFS= read -r d; do
    d="${d%%#*}"; d="${d//[[:space:]]/}"
    [[ -z "$d" ]] && continue
    printf 'nftset=/%s/4#inet#awg_pbr#direct4\n' "$d" >>"$DC"
  done <"$DD"
  dnsmasq --test >/dev/null
  nft flush set inet awg_pbr vpn4 2>/dev/null || true
  nft flush set inet awg_pbr direct4 2>/dev/null || true
  systemctl restart dnsmasq
  sleep 1
  # Warm apex entries. Subdomain/CDN entries are learned as clients query them.
  while IFS= read -r d; do
    d="${d%%#*}"; d="${d//[[:space:]]/}"; [[ -z "$d" ]] && continue
    dig +time=2 +tries=1 +short A "$d" @"$PI_IP" >/dev/null 2>&1 || true
  done <"$VD"
  while IFS= read -r d; do
    d="${d%%#*}"; d="${d//[[:space:]]/}"; [[ -z "$d" ]] && continue
    dig +time=2 +tries=1 +short A "$d" @"$PI_IP" >/dev/null 2>&1 || true
  done <"$DD"
}
reload_all(){
  "$SETUP"
  regen_domains
  systemctl restart "$HEALTH_SERVICE"
}

add_domain(){
  local kind="$1" raw="$2" d file other
  d="$(normalize_domain "$raw")"
  valid_domain "$d" || { echo "Некорректный домен: $d" >&2; exit 2; }
  if [[ "$kind" == vpn ]]; then file="$VD"; other="$DD"; else file="$DD"; other="$VD"; fi
  grep -Fxq "$d" "$file" || echo "$d" >>"$file"
  # Exact duplicate in opposite list is ambiguous; keep hierarchy exceptions, remove only exact duplicate.
  grep -Fxv "$d" "$other" >"$other.tmp" || true; mv "$other.tmp" "$other"
  sort -u -o "$file" "$file"; sort -u -o "$other" "$other"
  regen_domains
  echo "OK: $kind add $d"
}
del_domain(){
  local kind="$1" raw="$2" d file
  d="$(normalize_domain "$raw")"
  file="$VD"; [[ "$kind" == direct ]] && file="$DD"
  grep -Fxv "$d" "$file" >"$file.tmp" || true; mv "$file.tmp" "$file"
  regen_domains
  echo "OK: $kind del $d"
}

client_cmd(){
  local action="${1:-}" ip="${2:-}"
  case "$action" in
    list)
      echo "=== PBR client allow-list ==="
      if grep -Ev '^\s*(#|$)' "$CF" | grep -q .; then cat "$CF"; else echo "(пусто: все устройства с gateway=Pi участвуют в PBR)"; fi
      ;;
    add)
      valid_ipv4 "$ip" || { echo "Некорректный IPv4: $ip" >&2; exit 2; }
      grep -Fxq "$ip" "$CF" || echo "$ip" >>"$CF"; sort -u -o "$CF" "$CF"
      reload_all; echo "OK: client add $ip"
      ;;
    del)
      valid_ipv4 "$ip" || { echo "Некорректный IPv4: $ip" >&2; exit 2; }
      grep -Fxv "$ip" "$CF" >"$CF.tmp" || true; mv "$CF.tmp" "$CF"
      reload_all; echo "OK: client del $ip"
      ;;
    *) usage; exit 2 ;;
  esac
}

vpn_switch(){
  local state="$1"
  case "$state" in
    on)
      echo 1 >"$VE"
      systemctl restart "$HEALTH_SERVICE"
      sleep 2
      echo "VPN policy разрешён. Он включится только если health-check успешен."
      ;;
    off)
      echo 0 >"$VE"
      "$FAILOPEN"
      systemctl restart "$HEALTH_SERVICE"
      echo "VPN policy выключен; все маршруты DIRECT. Сам туннель awg0 не удалён."
      ;;
    *) usage; exit 2 ;;
  esac
}

show_status(){
  local age enabled
  enabled="$(cat "$VE" 2>/dev/null || echo 1)"
  age="$(handshake_age)"
  echo "=== Gateway ==="
  printf 'LAN: %s  Pi: %s  Router: %s  Network: %s\n' "$LAN_IF" "$PI_IP" "$ROUTER_IP" "$LAN_CIDR"
  printf 'VPN policy requested: %s\n' "$([[ "$enabled" == 1 ]] && echo ON || echo OFF)"
  printf 'Health state: %s\n' "$(health_state)"
  printf 'Policy rule: %s\n' "$(policy_present && echo ACTIVE || echo FAIL-OPEN/DIRECT)"
  if (( age >= 0 )); then printf 'Latest handshake age: %ss\n' "$age"; else echo 'Latest handshake: отсутствует'; fi
  echo
  echo "=== Services ==="
  for s in awg-pbr-setup.service dnsmasq.service "awg-quick@$VPN_IF.service" awg-pbr-health.service; do
    printf '%-28s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || true)"
  done
  echo
  echo "=== Rules ==="
  printf 'VPN domains: %s\n' "$(grep -Evc '^\s*(#|$)' "$VD" 2>/dev/null || true)"
  printf 'DIRECT exceptions: %s\n' "$(grep -Evc '^\s*(#|$)' "$DD" 2>/dev/null || true)"
  printf 'Client allow-list: %s\n' "$(grep -Evc '^\s*(#|$)' "$CF" 2>/dev/null || true)"
  echo
  echo "=== AWG ==="
  awg show "$VPN_IF" 2>/dev/null || echo "awg0 недоступен"
}

test_domain(){
  local raw="$1" d ips ip in_vpn in_direct mark route
  d="$(normalize_domain "$raw")"; valid_domain "$d" || { echo "Некорректный домен: $d" >&2; exit 2; }
  echo "=== Test: $d ==="
  ips="$(dig +time=4 +tries=1 +short A "$d" @"$PI_IP" | grep -E '^[0-9]+(\.[0-9]+){3}$' || true)"
  [[ -n "$ips" ]] || { echo "DNS: A-записи не получены"; exit 1; }
  echo "DNS via Pi:"
  printf '%s\n' "$ips" | sed 's/^/  /'
  echo
  while IFS= read -r ip; do
    in_vpn=no; in_direct=no
    nft list set inet awg_pbr vpn4 2>/dev/null | grep -qw "$ip" && in_vpn=yes || true
    nft list set inet awg_pbr direct4 2>/dev/null | grep -qw "$ip" && in_direct=yes || true
    if [[ "$in_direct" == yes ]]; then mark=0; elif [[ "$in_vpn" == yes ]]; then mark="$VPN_MARK"; else mark=0; fi
    route="$(ip -4 route get "$ip" mark "$mark" 2>&1 | head -1 || true)"
    printf '%s  vpn-set=%s direct-set=%s mark=%s\n  route: %s\n' "$ip" "$in_vpn" "$in_direct" "$mark" "$route"
  done <<<"$ips"
  echo
  echo "Policy: $(policy_present && echo 'VPN rule active' || echo 'fail-open/direct')"
}

run_diagnostics(){
  local report tmpconf age direct_ip="" health_ok=no mark_test="" prev_health_active=no manual
  report="$LOG_DIR/diagnostics-$(date +%Y%m%d-%H%M%S).txt"
  tmpconf=/etc/dnsmasq.d/98-awg-diagnostics-temp.conf
  manual="$(cat "$VE" 2>/dev/null || echo 1)"
  systemctl is-active --quiet "$HEALTH_SERVICE" && prev_health_active=yes || true

  {
    echo "=== AWG Gateway diagnostics ==="
    echo "Date: $(date -Is)"
    echo "Host: $(hostname)"
    echo "Model: $(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo unknown)"
    echo "OS: $(. /etc/os-release; echo "${PRETTY_NAME:-unknown}")"
    echo "Kernel: $(uname -srmo)"
    echo "awg: $(awg --version 2>/dev/null || echo unavailable)"
    echo "amneziawg-go: $(amneziawg-go --version 2>/dev/null || echo unavailable)"
    echo "dnsmasq: $(dnsmasq --version 2>/dev/null | head -1 || true)"
    echo
    echo "--- Network ---"
    ip -br -4 addr show
    ip -4 route show
    echo
    echo "Router ping:"
    if ping -4 -c1 -W2 "$ROUTER_IP" >/dev/null 2>&1; then echo "OK $ROUTER_IP"; else echo "FAIL $ROUTER_IP"; fi
    echo
    echo "--- Direct internet/DNS ---"
    direct_dns_ok=no
    IFS=',' read -ra _dns_diag <<<"${UPSTREAM_DNS:-1.1.1.1,9.9.9.9}"
    for _d in "${_dns_diag[@]}"; do
      _d="${_d//[[:space:]]/}"
      if dig +time=3 +tries=1 +short A example.com @"$_d" | grep -qE '^[0-9]+\.'; then direct_dns_ok=yes; break; fi
    done
    echo "Direct DNS: $direct_dns_ok"
    for u in https://api.ipify.org https://icanhazip.com https://ifconfig.me/ip; do
      direct_ip="$(curl -4fsS --interface "$LAN_IF" --max-time 6 "$u" 2>/dev/null | tr -d '\r\n ' || true)"
      [[ "$direct_ip" =~ ^[0-9]+(\.[0-9]+){3}$ ]] && break
    done
    echo "Direct public IPv4: ${direct_ip:-unavailable}"
    echo
    echo "--- DNS via Pi ---"
    if dig +time=3 +tries=1 +short A example.com @"$PI_IP" | grep -qE '^[0-9]+\.'; then echo "dnsmasq query: OK"; else echo "dnsmasq query: FAIL"; fi
    echo
    echo "--- Services ---"
    for s in awg-pbr-setup.service dnsmasq.service "awg-quick@$VPN_IF.service" awg-pbr-health.service; do
      echo "$s: $(systemctl is-active "$s" 2>/dev/null || true) / enabled=$(systemctl is-enabled "$s" 2>/dev/null || true)"
    done
    echo
    echo "--- AWG ---"
    awg show "$VPN_IF" 2>/dev/null || true
    age="$(handshake_age)"
    echo "Handshake age: $age"
    echo "Health state: $(health_state)"
    echo "Policy present: $(policy_present && echo yes || echo no)"
    echo
    echo "--- Policy routing ---"
    ip -4 rule show
    ip -4 route show table "$VPN_TABLE" 2>/dev/null || true
    mark_test="$(ip -4 route get 1.1.1.1 mark "$VPN_MARK" 2>&1 | head -1 || true)"
    echo "Route with VPN mark: $mark_test"
    echo
    echo "--- nftables owned table ---"
    nft list table inet awg_pbr 2>/dev/null || true
    echo
    echo "--- Domain lists ---"
    echo "VPN domains:"; sed 's/^/  /' "$VD" 2>/dev/null || true
    echo "DIRECT domains:"; sed 's/^/  /' "$DD" 2>/dev/null || true
    echo "Clients:"; sed 's/^/  /' "$CF" 2>/dev/null || true
    echo
    echo "--- VPN transport health ---"
    if ip link show "$VPN_IF" >/dev/null 2>&1; then
      ip -4 route replace default dev "$VPN_IF" table "$HEALTH_TABLE" 2>/dev/null || true
      if ! ip -4 rule show | grep -Eq '(^| )90:.*fwmark (0x101|257).*lookup (101|awghealth)'; then
        ip -4 rule add priority 90 fwmark "$HEALTH_MARK" lookup "$HEALTH_TABLE" 2>/dev/null || true
      fi
      if ping -4 -n -m "$HEALTH_MARK" -c1 -W3 1.1.1.1 >/dev/null 2>&1 || ping -4 -n -m "$HEALTH_MARK" -c1 -W3 9.9.9.9 >/dev/null 2>&1; then health_ok=yes; fi
    fi
    echo "VPN transport ping: $health_ok"
    echo
    echo "--- dnsmasq -> nftset functional test ---"
  } | tee "$report"

  # Functional nftset test: temporary set + temporary dnsmasq rule, then cleanup.
  local nftset_result=FAIL
  nft delete set inet awg_pbr diag4 2>/dev/null || true
  if nft add set inet awg_pbr diag4 '{ type ipv4_addr; flags timeout; timeout 5m; }' 2>/dev/null; then
    echo 'nftset=/example.com/4#inet#awg_pbr#diag4' >"$tmpconf"
    if dnsmasq --test >/dev/null 2>&1 && systemctl restart dnsmasq && sleep 1; then
      dig +time=3 +tries=1 +short A example.com @"$PI_IP" >/dev/null 2>&1 || true
      if nft list set inet awg_pbr diag4 2>/dev/null | grep -q 'elements'; then nftset_result=OK; fi
    fi
  fi
  echo "dnsmasq nftset insertion: $nftset_result" | tee -a "$report"
  rm -f "$tmpconf"
  nft delete set inet awg_pbr diag4 2>/dev/null || true
  systemctl restart dnsmasq >/dev/null 2>&1 || true

  # Fail-open simulation. Short controlled interruption of policy rule only.
  echo | tee -a "$report"
  echo "--- FAIL-OPEN simulation ---" | tee -a "$report"
  if [[ "$prev_health_active" == yes ]]; then systemctl stop "$HEALTH_SERVICE" >/dev/null 2>&1 || true; fi
  "$FAILOPEN" >/dev/null 2>&1 || true
  local failroute
  failroute="$(ip -4 route get 1.1.1.1 mark "$VPN_MARK" 2>&1 | head -1 || true)"
  echo "Route after policy removal: $failroute" | tee -a "$report"
  if grep -q "dev $LAN_IF" <<<"$failroute"; then
    echo "FAIL-OPEN: OK (falls back to LAN/main route)" | tee -a "$report"
  else
    echo "FAIL-OPEN: FAIL" | tee -a "$report"
  fi
  if [[ "$prev_health_active" == yes ]]; then systemctl start "$HEALTH_SERVICE" >/dev/null 2>&1 || true; fi
  if [[ "$manual" == 0 ]]; then "$FAILOPEN" >/dev/null 2>&1 || true; fi

  echo | tee -a "$report"
  echo "Report: $report" | tee -a "$report"
  chmod 600 "$report"
  prune_reports
}

cmd="${1:-}"; action="${2:-}"; val="${3:-}"
case "$cmd" in
  vpn)
    case "$action" in
      add) [[ -n "$val" ]] || { usage; exit 2; }; add_domain vpn "$val" ;;
      del) [[ -n "$val" ]] || { usage; exit 2; }; del_domain vpn "$val" ;;
      on|off) vpn_switch "$action" ;;
      *) usage; exit 2 ;;
    esac
    ;;
  direct)
    case "$action" in
      add) [[ -n "$val" ]] || { usage; exit 2; }; add_domain direct "$val" ;;
      del) [[ -n "$val" ]] || { usage; exit 2; }; del_domain direct "$val" ;;
      *) usage; exit 2 ;;
    esac
    ;;
  client) client_cmd "$action" "$val" ;;
  list)
    echo "=== VPN domains ==="; cat "$VD" 2>/dev/null || true
    echo; echo "=== DIRECT exceptions ==="; cat "$DD" 2>/dev/null || true
    echo; echo "=== Client allow-list ==="; if grep -Ev '^\s*(#|$)' "$CF" 2>/dev/null | grep -q .; then cat "$CF"; else echo "(пусто = все Pi-gateway clients)"; fi
    ;;
  status) show_status ;;
  test) [[ -n "$action" ]] || { usage; exit 2; }; test_domain "$action" ;;
  reload) reload_all; echo "OK: configuration reloaded" ;;
  diagnostics) run_diagnostics ;;
  logs)
    n="${action:-150}"; [[ "$n" =~ ^[0-9]+$ ]] || n=150
    journalctl --no-pager -n "$n" -u "awg-quick@$VPN_IF.service" -u awg-pbr-health.service -u dnsmasq.service -u awg-pbr-setup.service
    ;;
  *) usage; exit 2 ;;
esac
EOF
chmod 755 "$ROUTE_CLI"

# v1.1.0 helpers are maintained as standalone repository files so the TUI and
# source manager can be audited independently of this installer.
STAGE="установка компонентов v1.1.0"
log "[8b/12] CLI v1.1.0 + OpenCCK + SSH TUI"
install_project_helper(){
  local remote="$1" target="$2" tmp
  tmp="$(mktemp)"
  curl -4fLsS --retry 3 --connect-timeout 8 --max-time 45 "$PROJECT_RAW_BASE/$remote" -o "$tmp" \
    || die "Не удалось загрузить $remote из проекта ($PROJECT_REF)"
  bash -n "$tmp" || die "Синтаксическая проверка $remote не пройдена"
  install -m 755 "$tmp" "$target"
  rm -f "$tmp"
}
mkdir -p /usr/local/lib/awg-pi
install_project_helper src/awg-common /usr/local/lib/awg-pi/common.sh
chmod 644 /usr/local/lib/awg-pi/common.sh
install_project_helper src/awg-route "$ROUTE_CLI"
install_project_helper src/awg-opencck-update /usr/local/sbin/awg-opencck-update
install_project_helper src/awg-core-update /usr/local/sbin/awg-core-update
install_project_helper src/awg-update "$UPDATE_SCRIPT"
install_project_helper src/awg-menu /usr/local/sbin/awg-menu

mkdir -p /etc/awg-pbr/sources/opencck/metadata
chmod 700 /etc/awg-pbr/sources /etc/awg-pbr/sources/opencck /etc/awg-pbr/sources/opencck/metadata
cat >/etc/systemd/system/awg-opencck-update.service <<'EOF'
[Unit]
Description=AWG Pi Gateway OpenCCK source updater
Wants=network-online.target
After=network-online.target dnsmasq.service awg-pbr-setup.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/awg-opencck-update
EOF

cat >/etc/systemd/system/awg-opencck-update.timer <<'EOF'
[Unit]
Description=Periodic OpenCCK source update for AWG Pi Gateway

[Timer]
OnBootSec=10min
OnUnitActiveSec=12h
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat >/etc/profile.d/awg-menu.sh <<'EOF'
# AWG Pi Gateway: open TUI only for an interactive SSH login.
# Set AWG_MENU_DISABLE=1 before login command execution to bypass it.
if [ -n "${SSH_CONNECTION:-}" ] && [ -t 0 ] && [ -t 1 ] && [ "${AWG_MENU_DISABLE:-0}" != 1 ] && [ ! -e "${HOME:-/nonexistent}/.no-awg-menu" ] && [ -x /usr/local/sbin/awg-menu ]; then
  if [ "${AWG_MENU_ACTIVE:-0}" != 1 ]; then
    export AWG_MENU_ACTIVE=1
    sudo /usr/local/sbin/awg-menu
    _awg_menu_rc=$?
    if [ "$_awg_menu_rc" -eq 20 ]; then
      exit
    fi
    unset _awg_menu_rc
  fi
fi
EOF
chmod 644 /etc/profile.d/awg-menu.sh

# -----------------------------------------------------------------------------
# 9. Fail-open health monitor
# -----------------------------------------------------------------------------
STAGE="настройка health-check и fail-open"
log "[9/12] Health monitor + FAIL-OPEN"
cat >"$HEALTH_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC1091
source /etc/awg-pbr/env
VE=/etc/awg-pbr/vpn-enabled
STATE_DIR=/run/awg-pbr
STATE="$STATE_DIR/health.state"
mkdir -p "$STATE_DIR"

rule_on(){
  ip -4 route replace default dev "$VPN_IF" table "$VPN_TABLE"
  if ! ip -4 rule show | grep -Eq '(^| )100:.*fwmark (0x100|256).*lookup (100|awgvpn)'; then
    ip -4 rule add priority 100 fwmark "$VPN_MARK" lookup "$VPN_TABLE"
  fi
  if [[ "$(cat "$STATE" 2>/dev/null || true)" != up ]]; then
    echo up >"$STATE"
    logger -t awg-pbr "VPN healthy: policy route enabled"
  fi
}
rule_off(){
  while ip -4 rule del priority 100 fwmark "$VPN_MARK" lookup "$VPN_TABLE" 2>/dev/null; do :; done
  if [[ "$(cat "$STATE" 2>/dev/null || true)" != down ]]; then
    echo down >"$STATE"
    logger -t awg-pbr "VPN unavailable/disabled: FAIL-OPEN to normal Internet"
  fi
}
health_prepare(){
  ip -4 route replace default dev "$VPN_IF" table "$HEALTH_TABLE" 2>/dev/null || true
  if ! ip -4 rule show | grep -Eq '(^| )90:.*fwmark (0x101|257).*lookup (101|awghealth)'; then
    ip -4 rule add priority 90 fwmark "$HEALTH_MARK" lookup "$HEALTH_TABLE" 2>/dev/null || true
  fi
}
handshake_fresh(){
  local hs now
  hs="$(awg show "$VPN_IF" latest-handshakes 2>/dev/null | awk '$2>m{m=$2}END{print m+0}')"
  [[ "$hs" -gt 0 ]] || return 1
  now="$(date +%s)"
  (( now - hs <= HANDSHAKE_MAX_AGE ))
}
transport_ok(){
  # Ping itself stimulates a handshake when needed.
  ping -4 -n -m "$HEALTH_MARK" -c1 -W2 1.1.1.1 >/dev/null 2>&1 || \
  ping -4 -n -m "$HEALTH_MARK" -c1 -W2 9.9.9.9 >/dev/null 2>&1
}

trap 'rule_off' EXIT INT TERM
rule_off
while true; do
  if [[ "$(cat "$VE" 2>/dev/null || echo 1)" != 1 ]]; then
    rule_off
    sleep "$HEALTH_INTERVAL"
    continue
  fi
  if ip link show "$VPN_IF" >/dev/null 2>&1; then
    health_prepare
    if transport_ok && handshake_fresh; then rule_on; else rule_off; fi
  else
    rule_off
  fi
  sleep "$HEALTH_INTERVAL"
done
EOF
chmod 755 "$HEALTH_SCRIPT"

cat >"$HEALTH_SERVICE" <<'EOF'
[Unit]
Description=AmneziaWG fail-open health monitor
After=network-online.target awg-quick@awg0.service awg-pbr-setup.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/awg-pbr-health
ExecStopPost=/usr/local/sbin/awg-pbr-failopen
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

# -----------------------------------------------------------------------------
# 10. Updater with rollback
# -----------------------------------------------------------------------------
STAGE="создание обновлятора"
log "[10/12] awg-update"
cat >"$UPDATE_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"
export PATH=/usr/local/go/bin:$PATH
SRC_ROOT=/opt/amneziawg-src
VPN_IF=awg0
BACKUP_ROOT=/var/backups/awg-gateway
VE=/etc/awg-pbr/vpn-enabled
MANUAL_VPN="$(cat "$VE" 2>/dev/null || echo 1)"
GO_REPO=https://github.com/amnezia-vpn/amneziawg-go.git
TOOLS_REPO=https://github.com/amnezia-vpn/amneziawg-tools.git
mkdir -p "$BACKUP_ROOT"

latest(){ git ls-remote --tags --refs "$1" 'refs/tags/v*' | awk -F/ '{print $3}' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+' | sort -V | tail -1; }
install_go(){
  local arch j f s t
  case "$(uname -m)" in aarch64|arm64) arch=arm64;; *) echo "Unsupported arch" >&2; return 1;; esac
  j="$(curl -fsSL --max-time 30 https://go.dev/dl/?mode=json)"
  f="$(jq -r --arg a "$arch" '.[0].files[]|select(.os=="linux" and .arch==$a and .kind=="archive")|.filename' <<<"$j" | head -1)"
  s="$(jq -r --arg a "$arch" '.[0].files[]|select(.os=="linux" and .arch==$a and .kind=="archive")|.sha256' <<<"$j" | head -1)"
  [[ -n "$f" && "$f" != null && -n "$s" && "$s" != null ]] || return 1
  t="/tmp/$f"; curl -fL --retry 3 "https://go.dev/dl/$f" -o "$t"; echo "$s  $t" | sha256sum -c -
  rm -rf /usr/local/go; tar -C /usr/local -xzf "$t"; rm -f "$t"
}
sync_repo(){
  local repo="$1" dir="$2" tag="$3"
  if [[ -d "$dir/.git" ]]; then git -C "$dir" fetch --tags --prune origin; else git clone "$repo" "$dir"; fi
  git -C "$dir" checkout -f "$tag"; git -C "$dir" reset --hard "$tag"
}

curl -4fsSI --max-time 8 https://github.com >/dev/null || { echo "GitHub недоступен" >&2; exit 1; }
GT="$(latest "$GO_REPO")"; TT="$(latest "$TOOLS_REPO")"
[[ -n "$GT" && -n "$TT" ]] || { echo "Не удалось определить стабильные теги" >&2; exit 1; }
CURG="$(git -C "$SRC_ROOT/amneziawg-go" describe --tags --exact-match 2>/dev/null || echo unknown)"
CURT="$(git -C "$SRC_ROOT/amneziawg-tools" describe --tags --exact-match 2>/dev/null || echo unknown)"
echo "Installed: go=$CURG tools=$CURT"
echo "Latest:    go=$GT tools=$TT"
if [[ "$CURG" == "$GT" && "$CURT" == "$TT" ]]; then echo "Уже установлены последние стабильные теги."; exit 0; fi
read -r -p "Обновить? [Y/n]: " ans </dev/tty; ans="${ans:-Y}"; [[ "$ans" =~ ^[YyДд] ]] || exit 0

# Update Go first so future AWG module requirements do not break the build.
install_go
export PATH=/usr/local/go/bin:$PATH

OLD_GO_REF="$(git -C "$SRC_ROOT/amneziawg-go" rev-parse HEAD 2>/dev/null || true)"
OLD_TOOLS_REF="$(git -C "$SRC_ROOT/amneziawg-tools" rev-parse HEAD 2>/dev/null || true)"
sync_repo "$GO_REPO" "$SRC_ROOT/amneziawg-go" "$GT"
sync_repo "$TOOLS_REPO" "$SRC_ROOT/amneziawg-tools" "$TT"

make -C "$SRC_ROOT/amneziawg-go" clean >/dev/null 2>&1 || true
make -C "$SRC_ROOT/amneziawg-go"
make -C "$SRC_ROOT/amneziawg-tools/src" clean >/dev/null 2>&1 || true
make -C "$SRC_ROOT/amneziawg-tools/src"

BK="$BACKUP_ROOT/update-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"; chmod 700 "$BK"
for f in /usr/bin/amneziawg-go /usr/bin/awg /usr/bin/awg-quick; do [[ -f "$f" ]] && cp -a "$f" "$BK/"; done
UNIT="$(systemctl show -p FragmentPath --value awg-quick@awg0.service 2>/dev/null || true)"
[[ -f "$UNIT" ]] && { cp -a "$UNIT" "$BK/awg-quick@.service"; echo "$UNIT" >"$BK/unit-path"; }

echo "Fail-open before replacing binaries..."
systemctl stop awg-pbr-health.service || true
/usr/local/sbin/awg-pbr-failopen || true
systemctl stop "awg-quick@$VPN_IF.service" || true
# Temporarily enable policy only for update health verification; restore user state afterwards.
echo 1 >"$VE"

rollback(){
  echo "UPDATE FAILED -> rollback" >&2
  systemctl stop "awg-quick@$VPN_IF.service" >/dev/null 2>&1 || true
  for f in amneziawg-go awg awg-quick; do [[ -f "$BK/$f" ]] && install -m755 "$BK/$f" "/usr/bin/$f"; done
  if [[ -f "$BK/awg-quick@.service" && -f "$BK/unit-path" ]]; then cp -a "$BK/awg-quick@.service" "$(cat "$BK/unit-path")"; fi
  [[ -n "$OLD_GO_REF" ]] && git -C "$SRC_ROOT/amneziawg-go" checkout -f "$OLD_GO_REF" >/dev/null 2>&1 || true
  [[ -n "$OLD_TOOLS_REF" ]] && git -C "$SRC_ROOT/amneziawg-tools" checkout -f "$OLD_TOOLS_REF" >/dev/null 2>&1 || true
  systemctl daemon-reload
  echo "$MANUAL_VPN" >"$VE"
  systemctl start "awg-quick@$VPN_IF.service" || true
  systemctl start awg-pbr-health.service || true
  [[ "$MANUAL_VPN" == 1 ]] || /usr/local/sbin/awg-pbr-failopen || true
  exit 1
}
trap rollback ERR

make -C "$SRC_ROOT/amneziawg-go" PREFIX=/usr install
make -C "$SRC_ROOT/amneziawg-tools/src" install PREFIX=/usr WITH_WGQUICK=yes WITH_SYSTEMDUNITS=yes
systemctl daemon-reload
systemctl start "awg-quick@$VPN_IF.service"
systemctl start awg-pbr-health.service

ok=0
for _ in $(seq 1 12); do
  sleep 3
  if [[ "$(cat /run/awg-pbr/health.state 2>/dev/null || true)" == up ]]; then ok=1; break; fi
done
(( ok == 1 )) || { echo "Новый AWG не прошёл health-check" >&2; false; }
trap - ERR
echo "$MANUAL_VPN" >"$VE"
systemctl restart awg-pbr-health.service || true
[[ "$MANUAL_VPN" == 1 ]] || /usr/local/sbin/awg-pbr-failopen || true

echo "Update OK"
awg --version || true
amneziawg-go --version || true
/usr/local/sbin/awg-route diagnostics || true
find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d -name 'update-*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR>5{sub(/^[^ ]+ /,""); print}' | xargs -r rm -rf
EOF
chmod 755 "$UPDATE_SCRIPT"

# -----------------------------------------------------------------------------
# 11. Start services and critical tests
# -----------------------------------------------------------------------------
STAGE="первый запуск и критические проверки"
log "[11/12] Первый запуск"
systemctl daemon-reload
systemctl enable awg-pbr-setup.service dnsmasq.service "awg-quick@$VPN_IF.service" awg-pbr-health.service awg-opencck-update.timer >/dev/null

systemctl restart awg-pbr-setup.service
nft list table inet awg_pbr >/dev/null 2>&1 || die "Не создана nftables table inet awg_pbr"
ok "nftables PBR table создана"

systemctl restart dnsmasq.service
systemctl is-active --quiet dnsmasq.service || {
  systemctl status dnsmasq.service --no-pager || true
  die "dnsmasq не запустился. Частая причина: порт 53 уже занят"
}
if ! dig +time=3 +tries=1 +short A example.com @"$PI_IP" | grep -qE '^[0-9]+\.'; then
  die "DNS через Raspberry Pi ($PI_IP:53) не работает"
fi
ok "DNS Raspberry Pi работает"

systemctl restart "awg-quick@$VPN_IF.service"
systemctl is-active --quiet "awg-quick@$VPN_IF.service" || {
  systemctl status "awg-quick@$VPN_IF.service" --no-pager || true
  journalctl -u "awg-quick@$VPN_IF.service" -n 80 --no-pager || true
  die "awg0 не поднялся"
}
ip link show "$VPN_IF" >/dev/null 2>&1 || die "Сервис AWG активен, но интерфейс $VPN_IF отсутствует"
ok "$VPN_IF поднят"

systemctl restart awg-pbr-health.service
systemctl is-active --quiet awg-pbr-health.service || die "health monitor не запустился"
systemctl start awg-opencck-update.timer
systemctl is-active --quiet awg-opencck-update.timer || warn "OpenCCK timer не активен; ручное обновление останется доступно"

printf "Ожидание handshake/проверки VPN"
VPN_HEALTH=0
for _ in $(seq 1 15); do
  sleep 2
  printf "."
  if [[ "$(cat /run/awg-pbr/health.state 2>/dev/null || true)" == "up" ]]; then VPN_HEALTH=1; break; fi
done
printf "\n"
if (( VPN_HEALTH == 0 )); then
  awg show "$VPN_IF" || true
  journalctl -u awg-pbr-health.service -n 50 --no-pager || true
  die "VPN не прошёл health-check: нет рабочего транспорта и/или свежего handshake. PBR не активирован"
fi
ok "AmneziaWG: handshake + интернет через туннель работают"

if ! ip -4 rule show | grep -Eq '(^| )100:.*fwmark (0x100|256).*lookup (100|awgvpn)'; then
  die "Health успешен, но policy rule не активировался"
fi
if ! ip -4 route get 1.1.1.1 mark "$VPN_MARK" | grep -q "dev $VPN_IF"; then
  die "Маркированный трафик не маршрутизируется в $VPN_IF"
fi
ok "Policy routing работает"

# -----------------------------------------------------------------------------
# 12. Deep diagnostics + summary
# -----------------------------------------------------------------------------
STAGE="финальная диагностика"
log "[12/12] Полная диагностика"
"$ROUTE_CLI" reload
"$ROUTE_CLI" diagnostics

printf '%s\n' "$VERSION" >/etc/awg-pbr/version
chmod 600 /etc/awg-pbr/version
ok "Версия AWG Pi Gateway зафиксирована: $VERSION"

LATEST_DIAG="$(find "$LOG_DIR" -maxdepth 1 -type f -name 'diagnostics-*.txt' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"

printf "\n%b=== УСТАНОВКА ЗАВЕРШЕНА ===%b\n" "$G$B" "$R"
printf "Raspberry Pi:    %s\n" "$PI_IP"
printf "MAC (%s):       %s\n" "$LAN_IF" "$LAN_MAC"
printf "Archer C64:      %s\n" "$ROUTER_IP"
printf "LAN:             %s\n" "$LAN_CIDR"
printf "VPN interface:   %s\n" "$VPN_IF"
printf "AWG tags:        go=%s tools=%s\n" "$GO_TAG" "$TOOLS_TAG"
printf "Install report:  %s\n" "$INSTALL_REPORT"
printf "Diagnostics:     %s\n" "${LATEST_DIAG:-см. $LOG_DIR}"

printf "\nЛогика:\n"
printf "  обычный трафик = DIRECT через Archer C64\n"
printf "  VPN-list = через AmneziaWG\n"
printf "  VPN упал = автоматический FAIL-OPEN DIRECT\n"
printf "  DHCP остаётся на Archer C64\n"
printf "  DNS клиентов PBR = %s (dnsmasq -> независимые upstream DNS)\n" "$PI_IP"

printf "\nОсновные команды:\n"
printf "  sudo awg-route status\n"
printf "  sudo awg-route vpn add youtube.com\n"
printf "  sudo awg-route vpn del youtube.com\n"
printf "  sudo awg-route direct add example.com\n"
printf "  sudo awg-route client add 192.168.0.50\n"
printf "  sudo awg-route client list\n"
printf "  sudo awg-route vpn on\n"
printf "  sudo awg-route vpn off\n"
printf "  sudo awg-route test youtube.com\n"
printf "  sudo awg-route diagnostics\n"
printf "  sudo awg-route logs\n"
printf "  sudo awg-route reload\n"
printf "  sudo awg-route vpn import FILE\n"
printf "  sudo awg-route source add opencck youtube\n"
printf "  sudo awg-route source list\n"
printf "  sudo awg-menu\n"
printf "  sudo awg-update status\n"
printf "  sudo awg-update gateway\n"
printf "  sudo awg-update core\n"

printf "\nДля первого тестового устройства (LG TV):\n"
printf "  IPv4:    свободный фиксированный адрес в %s\n" "$LAN_CIDR"
printf "  Gateway: %s\n" "$PI_IP"
printf "  DNS:     %s\n" "$PI_IP"
printf "  IPv6:    не использовать\n"

printf "\n%bВАЖНО:%b IP телевизора выбирайте вне конфликтов с DHCP либо закрепите его на Archer C64.\n" "$Y" "$R"
printf "После настройки LG сначала проверьте DIRECT, затем добавьте один тестовый домен в VPN-list.\n"
 \
    | sort -V | tail -1
}
sync_repo(){
  local repo="$1" dir="$2" tag="$3"
  mkdir -p "$SRC_ROOT"
  if [[ -d "$dir/.git" ]]; then
    git -C "$dir" fetch --tags --prune origin
    git -C "$dir" checkout -f "$tag"
    git -C "$dir" reset --hard "$tag"
  else
    rm -rf "$dir"
    git clone --depth 1 --branch "$tag" "$repo" "$dir"
  fi
}

GO_TAG="$(latest_tag "$GO_REPO")"
TOOLS_TAG="$(latest_tag "$TOOLS_REPO")"
[[ -n "$GO_TAG" && -n "$TOOLS_TAG" ]] || die "Не удалось получить стабильные теги AmneziaWG"
printf "Найдены стабильные теги: amneziawg-go=%s, tools=%s\n" "$GO_TAG" "$TOOLS_TAG"
confirm "Установить эти стабильные версии?" "Y" || die "Установка отменена пользователем"

sync_repo "$GO_REPO" "$SRC_ROOT/amneziawg-go" "$GO_TAG"
make -C "$SRC_ROOT/amneziawg-go" clean >/dev/null 2>&1 || true
make -C "$SRC_ROOT/amneziawg-go"
make -C "$SRC_ROOT/amneziawg-go" PREFIX=/usr install

sync_repo "$TOOLS_REPO" "$SRC_ROOT/amneziawg-tools" "$TOOLS_TAG"
make -C "$SRC_ROOT/amneziawg-tools/src" clean >/dev/null 2>&1 || true
make -C "$SRC_ROOT/amneziawg-tools/src"
make -C "$SRC_ROOT/amneziawg-tools/src" install PREFIX=/usr WITH_WGQUICK=yes WITH_SYSTEMDUNITS=yes
systemctl daemon-reload

command -v awg >/dev/null || die "awg не установлен"
command -v awg-quick >/dev/null || die "awg-quick не установлен"
command -v amneziawg-go >/dev/null || die "amneziawg-go не установлен"
ok "$(awg --version 2>/dev/null || echo 'awg установлен')"
ok "$(amneziawg-go --version 2>/dev/null || echo 'amneziawg-go установлен')"

# -----------------------------------------------------------------------------
# 5. Import and validate AWG config
# -----------------------------------------------------------------------------
STAGE="импорт конфигурации AmneziaWG"
log "[5/12] Конфигурация AmneziaWG"
mkdir -p "$CONF_DIR" "$PBR_DIR" /etc/nftables.d
chmod 700 "$CONF_DIR" "$PBR_DIR"

if [[ -f "$CONF_FILE" ]]; then
  cp -a "$CONF_FILE" "$CONF_FILE.bak.$(date +%Y%m%d-%H%M%S)"
fi

if (( UPGRADE_EXISTING == 0 )); then
printf "1) указать путь к .conf\n2) вставить конфиг в терминал\n"
ask "Способ импорта" "2"
mode="$REPLY"
tmp="$(mktemp --suffix=.conf)"
cleanup_tmp(){ rm -f "$tmp" "${tmp}.new" 2>/dev/null || true; }
trap cleanup_tmp EXIT
case "$mode" in
  1)
    ask "Полный путь к .conf"
    [[ -f "$REPLY" ]] || die "Файл не найден: $REPLY"
    cp "$REPLY" "$tmp"
    ;;
  2)
    printf "Вставьте конфиг. Завершите отдельной строкой __END__\n"
    : >"$tmp"
    while IFS= read -r line <"$TTY"; do
      [[ "$line" == "__END__" ]] && break
      printf '%s\n' "$line" >>"$tmp"
    done
    ;;
  *) die "Неверный способ импорта" ;;
esac
sed -i 's/\r$//' "$tmp"

[[ "$(grep -Ec '^\s*\[Interface\]\s*$' "$tmp")" -eq 1 ]] || die "Конфиг должен содержать ровно один [Interface]"
[[ "$(grep -Ec '^\s*\[Peer\]\s*$' "$tmp")" -ge 1 ]] || die "В конфиге нет [Peer]"
grep -qE '^\s*PrivateKey\s*=' "$tmp" || die "В [Interface] нет PrivateKey"
grep -qE '^\s*Address\s*=' "$tmp" || die "В [Interface] нет Address"
grep -qE '^\s*PublicKey\s*=' "$tmp" || die "В [Peer] нет PublicKey"
grep -qE '^\s*Endpoint\s*=' "$tmp" || die "В [Peer] нет Endpoint"
grep -qE '^\s*AllowedIPs\s*=.*0\.0\.0\.0/0' "$tmp" || die "Для PBR peer должен разрешать 0.0.0.0/0 в AllowedIPs"

if grep -qE '^\s*(Jc|Jmin|Jmax|S1|H1)\s*=' "$tmp"; then
  ok "Обнаружены параметры AmneziaWG"
else
  warn "Специфические параметры AWG не обнаружены; убедитесь, что экспортирован именно профиль AmneziaWG"
fi

if grep -qE '^\s*PersistentKeepalive\s*=' "$tmp"; then
  ok "PersistentKeepalive уже задан"
else
  warn "PersistentKeepalive отсутствует"
  if confirm "Добавить PersistentKeepalive = 25 в первый [Peer]?" "Y"; then
    awk '
      BEGIN{inp=0; done=0}
      /^[[:space:]]*\[Peer\][[:space:]]*$/ { if(!done){inp=1}; print; next }
      /^[[:space:]]*\[/ { if(inp && !done){print "PersistentKeepalive = 25"; done=1; inp=0}; print; next }
      {print}
      END{if(inp && !done) print "PersistentKeepalive = 25"}
    ' "$tmp" >"${tmp}.new"
    mv "${tmp}.new" "$tmp"
    ok "Добавлен PersistentKeepalive = 25"
  fi
fi

# We own routing and DNS. Remove DNS/Table from imported Interface and force Table=off.
awk '
  BEGIN{inif=0; inserted=0}
  /^[[:space:]]*\[Interface\][[:space:]]*$/ {print; inif=1; next}
  /^[[:space:]]*\[/ && $0 !~ /^[[:space:]]*\[Interface\][[:space:]]*$/ {
    if(inif && !inserted){print "Table = off"; inserted=1}
    inif=0
  }
  inif && /^[[:space:]]*Table[[:space:]]*=/ {next}
  inif && /^[[:space:]]*DNS[[:space:]]*=/ {next}
  {print}
  END{if(inif && !inserted) print "Table = off"}
' "$tmp" >"${tmp}.new"
mv "${tmp}.new" "$tmp"
install -m 600 "$tmp" "$CONF_FILE"
cleanup_tmp
trap - EXIT
else
  ok "Существующий AWG-конфиг сохранён: $CONF_FILE"
fi

# Parser-level validation without bringing the tunnel up yet.
if ! awg-quick strip "$CONF_FILE" >/dev/null 2>&1; then
  die "awg-quick не смог разобрать импортированный конфиг. Проверьте синтаксис и параметры версии AWG"
fi
ok "Конфиг валиден для awg-quick; Table=off включён; DNS управляется отдельно"

# -----------------------------------------------------------------------------
# 6. LAN/Archer parameters
# -----------------------------------------------------------------------------
STAGE="проверка локальной сети"
log "[6/12] Archer C64 и локальная сеть"
if (( UPGRADE_EXISTING == 1 )); then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  : "${LAN_IF:?В существующем env отсутствует LAN_IF}"
  : "${LAN_CIDR:?В существующем env отсутствует LAN_CIDR}"
  : "${PI_IP:?В существующем env отсутствует PI_IP}"
  : "${ROUTER_IP:?В существующем env отсутствует ROUTER_IP}"
  : "${UPSTREAM_DNS:?В существующем env отсутствует UPSTREAM_DNS}"
  DNS_REDIRECT="${DNS_REDIRECT:-1}"
  HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"
  HANDSHAKE_MAX_AGE="${HANDSHAKE_MAX_AGE:-180}"
  LAN_MAC="$(cat "/sys/class/net/$LAN_IF/address" 2>/dev/null || true)"
  ip link show "$LAN_IF" >/dev/null 2>&1 || die "Сохранённый LAN интерфейс $LAN_IF отсутствует"
  ip -o -4 addr show dev "$LAN_IF" | grep -qE "[[:space:]]${PI_IP}/" || die "Сохранённый IP Raspberry Pi $PI_IP сейчас не назначен $LAN_IF"
  [[ "$(in_cidr "$PI_IP" "$LAN_CIDR")" == "yes" ]] || die "Сохранённый IP $PI_IP не принадлежит $LAN_CIDR"
  if ! ping -4 -c 2 -W 2 "$ROUTER_IP" >/dev/null 2>&1; then
    die "Сохранённый роутер $ROUTER_IP не отвечает"
  fi
  IFS=',' read -ra DNSA <<<"$UPSTREAM_DNS"
  DNS_OK=0
  for d in "${DNSA[@]}"; do
    d="${d//[[:space:]]/}"
    valid_ipv4 "$d" || die "В существующем env неверный DNS: $d"
    if dig +time=3 +tries=1 +short A example.com @"$d" | grep -qE '^[0-9]+\.'; then DNS_OK=$((DNS_OK+1)); fi
  done
  (( DNS_OK > 0 )) || die "Upstream DNS из существующей конфигурации не отвечает"
  touch "$VPN_DOMAINS" "$DIRECT_DOMAINS" "$CLIENTS_FILE"
  chmod 600 "$VPN_DOMAINS" "$DIRECT_DOMAINS" "$CLIENTS_FILE"
  [[ -f "$VPN_ENABLED_FILE" ]] || echo 1 >"$VPN_ENABLED_FILE"
  chmod 600 "$VPN_ENABLED_FILE"
  ok "Сетевая конфигурация сохранена: Pi=$PI_IP, Router=$ROUTER_IP, LAN=$LAN_CIDR"
else
printf "\nIPv4 интерфейсы:\n"
ip -br -4 addr show | sed 's/^/  /'
printf "Default route:\n"
ip -4 route show default | sed 's/^/  /'

UPLINK_IF="$(ip -4 route show default | awk 'NR==1{for(i=1;i<=NF;i++)if($i=="dev"){print $(i+1);exit}}')"
UPLINK_GW="$(ip -4 route show default | awk 'NR==1{for(i=1;i<=NF;i++)if($i=="via"){print $(i+1);exit}}')"
[[ -n "$UPLINK_IF" && -n "$UPLINK_GW" ]] || die "Не найден обычный IPv4 default route через Archer C64"

ask "LAN/uplink интерфейс Raspberry Pi" "$UPLINK_IF"
LAN_IF="$REPLY"
ip link show "$LAN_IF" >/dev/null 2>&1 || die "Нет интерфейса $LAN_IF"
[[ "$LAN_IF" == "eth0" ]] || warn "Для Raspberry Pi 4 рекомендуется проводной eth0; выбран $LAN_IF"

PI_CIDR="$(ip -o -4 addr show dev "$LAN_IF" scope global | awk 'NR==1{print $4}')"
[[ -n "$PI_CIDR" ]] || die "На $LAN_IF нет IPv4 адреса"
PI_IP="${PI_CIDR%/*}"
LAN_CIDR="$(ip -4 route show dev "$LAN_IF" proto kernel scope link | awk -v ip="$PI_IP" 'index($0,"src "ip){print $1;exit}')"
[[ -n "$LAN_CIDR" ]] || LAN_CIDR="$PI_CIDR"
LAN_MAC="$(cat "/sys/class/net/$LAN_IF/address")"

printf "\nMAC Raspberry Pi (%s): %s\n" "$LAN_IF" "$LAN_MAC"
printf "Текущий адрес: %s\n" "$PI_CIDR"
printf "Текущий роутер: %s\n" "$UPLINK_GW"

ask "Постоянный IPv4 Raspberry Pi (должен быть зарезервирован на Archer C64)" "$PI_IP"
PI_IP="$REPLY"
valid_ipv4 "$PI_IP" || die "Неверный IPv4 Raspberry Pi"
ip -o -4 addr show dev "$LAN_IF" | grep -qE "[[:space:]]${PI_IP}/" || die "$PI_IP сейчас не назначен $LAN_IF. Сначала создайте DHCP reservation на Archer C64 и обновите lease/перезагрузите Pi"

ask "Домашняя IPv4 подсеть" "$LAN_CIDR"
LAN_CIDR="$REPLY"
valid_cidr4 "$LAN_CIDR" || die "Неверная подсеть: $LAN_CIDR"
[[ "$(in_cidr "$PI_IP" "$LAN_CIDR")" == "yes" ]] || die "IP Raspberry Pi $PI_IP не принадлежит $LAN_CIDR"

ask "IP Archer C64" "$UPLINK_GW"
ROUTER_IP="$REPLY"
valid_ipv4 "$ROUTER_IP" || die "Неверный IP роутера"
[[ "$(in_cidr "$ROUTER_IP" "$LAN_CIDR")" == "yes" ]] || die "IP Archer $ROUTER_IP не принадлежит $LAN_CIDR"

if ! ping -4 -c 2 -W 2 "$ROUTER_IP" >/dev/null 2>&1; then
  die "Archer C64 ($ROUTER_IP) не отвечает с Raspberry Pi"
fi
ok "Archer C64 доступен: $ROUTER_IP"

printf "\nНа Archer C64 должна быть DHCP Reservation:\n  MAC: %s\n  IP:  %s\n" "$LAN_MAC" "$PI_IP"
confirm "Вы уже закрепили этот IP за MAC Raspberry Pi на Archer C64?" "N" || die "Сначала настройте DHCP Reservation на Archer C64, затем повторите установку"

ask "Upstream DNS для Raspberry Pi через запятую" "1.1.1.1,9.9.9.9"
UPSTREAM_DNS="$REPLY"
IFS=',' read -ra DNSA <<<"$UPSTREAM_DNS"
DNS_OK=0
for d in "${DNSA[@]}"; do
  d="${d//[[:space:]]/}"
  valid_ipv4 "$d" || die "Неверный DNS: $d"
  if dig +time=3 +tries=1 +short A example.com "@$d" | grep -qE '^[0-9]+\.'; then
    ok "Upstream DNS отвечает: $d"
    DNS_OK=$((DNS_OK+1))
  else
    warn "Upstream DNS не ответил: $d"
  fi
done
(( DNS_OK > 0 )) || die "Ни один выбранный upstream DNS не работает напрямую"

if confirm "Перехватывать обычный DNS TCP/UDP 53 у клиентов, использующих Pi как gateway?" "Y"; then
  DNS_REDIRECT=1
else
  DNS_REDIRECT=0
fi

cat >"$ENV_FILE" <<EOF
LAN_IF='$LAN_IF'
LAN_CIDR='$LAN_CIDR'
PI_IP='$PI_IP'
ROUTER_IP='$ROUTER_IP'
VPN_IF='$VPN_IF'
VPN_MARK='$VPN_MARK'
HEALTH_MARK='$HEALTH_MARK'
VPN_TABLE='$VPN_TABLE'
HEALTH_TABLE='$HEALTH_TABLE'
DNS_REDIRECT='$DNS_REDIRECT'
UPSTREAM_DNS='$UPSTREAM_DNS'
HEALTH_INTERVAL='$HEALTH_INTERVAL'
HANDSHAKE_MAX_AGE='$HANDSHAKE_MAX_AGE'
LOG_DIR='$LOG_DIR'
EOF
chmod 600 "$ENV_FILE"
touch "$VPN_DOMAINS" "$DIRECT_DOMAINS" "$CLIENTS_FILE"
chmod 600 "$VPN_DOMAINS" "$DIRECT_DOMAINS" "$CLIENTS_FILE"
echo 1 >"$VPN_ENABLED_FILE"
chmod 600 "$VPN_ENABLED_FILE"
fi

# -----------------------------------------------------------------------------
# 7. sysctl, watchdog, nftables base setup
# -----------------------------------------------------------------------------
STAGE="настройка маршрутизации и firewall"
log "[7/12] IPv4 forwarding, nftables, watchdog"
cat >"$SYSCTL_FILE" <<EOF
net.ipv4.ip_forward=1
net.ipv4.conf.all.src_valid_mark=1
net.ipv4.conf.all.rp_filter=2
net.ipv4.conf.default.rp_filter=2
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0
net.ipv4.conf.$LAN_IF.send_redirects=0
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.default.accept_redirects=0
EOF
sysctl --system >/dev/null
[[ "$(sysctl -n net.ipv4.ip_forward)" == "1" ]] || die "Не удалось включить net.ipv4.ip_forward"
ok "IPv4 forwarding включён"

if confirm "Включить аппаратный/systemd watchdog Raspberry Pi?" "Y"; then
  mkdir -p "$(dirname "$WATCHDOG_DROPIN")"
  cat >"$WATCHDOG_DROPIN" <<'EOF'
[Manager]
RuntimeWatchdogSec=20s
RebootWatchdogSec=10min
EOF
  systemctl daemon-reexec
  sleep 1
  WD="$(systemctl show -p RuntimeWatchdogUSec --value 2>/dev/null || true)"
  [[ -n "$WD" && "$WD" != "0" ]] && ok "Watchdog включён: $WD" || warn "systemd не подтвердил RuntimeWatchdog; система продолжит работу без гарантии hardware watchdog"
fi

cat >"$SETUP_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC1091
source /etc/awg-pbr/env
CLIENTS=/etc/awg-pbr/clients.txt
NFT=/etc/nftables.d/99-awg-pbr.nft

nft delete table inet awg_pbr 2>/dev/null || true
CLIENT_FILTER=""
if grep -Ev '^\s*(#|$)' "$CLIENTS" 2>/dev/null | grep -q .; then
  CLIENT_FILTER='ip saddr @clients4 '
fi

{
cat <<NFT
# Managed by awg-pbr-setup. This script owns only table inet awg_pbr.
table inet awg_pbr {
  set vpn4 {
    type ipv4_addr
    flags timeout
    timeout 15m
  }
  set direct4 {
    type ipv4_addr
    flags timeout
    timeout 15m
  }
  set clients4 {
    type ipv4_addr
  }
  set source4 {
    type ipv4_addr
    flags interval
  }

  chain prerouting_mark {
    type filter hook prerouting priority mangle; policy accept;
    iifname "$LAN_IF" ${CLIENT_FILTER}ip daddr @source4 meta mark set $VPN_MARK
    iifname "$LAN_IF" ${CLIENT_FILTER}ip daddr @vpn4 meta mark set $VPN_MARK
    iifname "$LAN_IF" ip daddr @direct4 meta mark set 0x0
  }

  chain dns_redirect {
    type nat hook prerouting priority dstnat; policy accept;
NFT
if [[ "$DNS_REDIRECT" == 1 ]]; then
  printf '    iifname "%s" udp dport 53 redirect to :53\n' "$LAN_IF"
  printf '    iifname "%s" tcp dport 53 redirect to :53\n' "$LAN_IF"
fi
cat <<NFT
  }

  chain postrouting_nat {
    type nat hook postrouting priority srcnat; policy accept;
    ip saddr $LAN_CIDR oifname "$VPN_IF" masquerade
    ip saddr $LAN_CIDR oifname "$LAN_IF" masquerade
  }
}
NFT
} >"$NFT"

nft -c -f "$NFT"
nft -f "$NFT"

while IFS= read -r ip; do
  ip="${ip%%#*}"; ip="${ip//[[:space:]]/}"
  [[ -z "$ip" ]] && continue
  nft add element inet awg_pbr clients4 "{ $ip }"
done <"$CLIENTS"

# Policy rule itself is controlled by health monitor for fail-open behavior.
while ip -4 rule del priority 100 fwmark "$VPN_MARK" lookup "$VPN_TABLE" 2>/dev/null; do :; done
ip -4 route flush table "$VPN_TABLE" 2>/dev/null || true
EOF
chmod 755 "$SETUP_SCRIPT"

cat >"$FAILOPEN_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC1091
source /etc/awg-pbr/env
while ip -4 rule del priority 100 fwmark "$VPN_MARK" lookup "$VPN_TABLE" 2>/dev/null; do :; done
mkdir -p /run/awg-pbr
echo down >/run/awg-pbr/health.state
EOF
chmod 755 "$FAILOPEN_SCRIPT"

cat >"$SETUP_SERVICE" <<'EOF'
[Unit]
Description=AmneziaWG policy-routing base setup
Wants=network-online.target
After=network-online.target
Before=dnsmasq.service awg-quick@awg0.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/awg-pbr-setup

[Install]
WantedBy=multi-user.target
EOF

# -----------------------------------------------------------------------------
# 8. DNS and management CLI
# -----------------------------------------------------------------------------
STAGE="настройка DNS и команд управления"
log "[8/12] dnsmasq + awg-route"

cat >"$DNS_CONF" <<EOF
# Managed by amneziawg-pi-gateway-installer
interface=$LAN_IF
bind-dynamic
listen-address=$PI_IP
listen-address=127.0.0.1
port=53
domain-needed
bogus-priv
no-resolv
cache-size=4000
max-cache-ttl=300
max-ttl=300
EOF
for d in "${DNSA[@]}"; do
  d="${d//[[:space:]]/}"
  printf 'server=%s\n' "$d" >>"$DNS_CONF"
done
: >"$DNS_DOMAINS_CONF"

dnsmasq --test || die "dnsmasq не принимает подготовленную конфигурацию"

cat >"$ROUTE_CLI" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"
# shellcheck disable=SC1091
source /etc/awg-pbr/env
VD=/etc/awg-pbr/vpn-domains.txt
DD=/etc/awg-pbr/direct-domains.txt
CF=/etc/awg-pbr/clients.txt
VE=/etc/awg-pbr/vpn-enabled
DC=/etc/dnsmasq.d/99-awg-pbr-domains.conf
SETUP=/usr/local/sbin/awg-pbr-setup
FAILOPEN=/usr/local/sbin/awg-pbr-failopen
HEALTH_SERVICE=awg-pbr-health.service
LOG_DIR="${LOG_DIR:-/var/log/awg-gateway}"
mkdir -p "$LOG_DIR"; chmod 700 "$LOG_DIR"

usage(){ cat <<USAGE
Управление AmneziaWG Policy Gateway

Доменные правила:
  awg-route vpn add DOMAIN
  awg-route vpn del DOMAIN
  awg-route direct add DOMAIN
  awg-route direct del DOMAIN
  awg-route list

Клиенты (опциональная allow-list):
  awg-route client add IPv4
  awg-route client del IPv4
  awg-route client list
  Пустой список = правила VPN применяются ко всем устройствам, использующим Pi как gateway.

VPN policy:
  awg-route vpn on
  awg-route vpn off

Проверки/обслуживание:
  awg-route status
  awg-route test DOMAIN
  awg-route reload
  awg-route diagnostics
  awg-route logs [N]

DOMAIN без wildcard уже включает его поддомены в dnsmasq.
USAGE
}

valid_ipv4(){
  local IFS=. a b c d
  read -r a b c d <<<"$1" || return 1
  [[ $a =~ ^[0-9]+$ && $b =~ ^[0-9]+$ && $c =~ ^[0-9]+$ && $d =~ ^[0-9]+$ ]] || return 1
  ((a<=255 && b<=255 && c<=255 && d<=255))
}
normalize_domain(){
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -E 's#^https?://##; s#/.*$##; s/^\*\.//; s/^\.//; s/\.$//'
}
valid_domain(){
  [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]
}
prune_reports(){
  find "$LOG_DIR" -maxdepth 1 -type f -name 'diagnostics-*.txt' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | awk 'NR>10{sub(/^[^ ]+ /,""); print}' | xargs -r rm -f
}
handshake_age(){
  local hs now
  hs="$(awg show "$VPN_IF" latest-handshakes 2>/dev/null | awk '$2>m{m=$2}END{print m+0}')"
  [[ "$hs" -gt 0 ]] || { echo -1; return; }
  now="$(date +%s)"; echo $((now-hs))
}
policy_present(){ ip -4 rule show | grep -Eq '(^| )100:.*fwmark (0x100|256).*lookup (100|awgvpn)'; }
health_state(){ cat /run/awg-pbr/health.state 2>/dev/null || echo unknown; }

regen_domains(){
  : >"$DC"
  while IFS= read -r d; do
    d="${d%%#*}"; d="${d//[[:space:]]/}"
    [[ -z "$d" ]] && continue
    printf 'nftset=/%s/4#inet#awg_pbr#vpn4\n' "$d" >>"$DC"
  done <"$VD"
  while IFS= read -r d; do
    d="${d%%#*}"; d="${d//[[:space:]]/}"
    [[ -z "$d" ]] && continue
    printf 'nftset=/%s/4#inet#awg_pbr#direct4\n' "$d" >>"$DC"
  done <"$DD"
  dnsmasq --test >/dev/null
  nft flush set inet awg_pbr vpn4 2>/dev/null || true
  nft flush set inet awg_pbr direct4 2>/dev/null || true
  systemctl restart dnsmasq
  sleep 1
  # Warm apex entries. Subdomain/CDN entries are learned as clients query them.
  while IFS= read -r d; do
    d="${d%%#*}"; d="${d//[[:space:]]/}"; [[ -z "$d" ]] && continue
    dig +time=2 +tries=1 +short A "$d" @"$PI_IP" >/dev/null 2>&1 || true
  done <"$VD"
  while IFS= read -r d; do
    d="${d%%#*}"; d="${d//[[:space:]]/}"; [[ -z "$d" ]] && continue
    dig +time=2 +tries=1 +short A "$d" @"$PI_IP" >/dev/null 2>&1 || true
  done <"$DD"
}
reload_all(){
  "$SETUP"
  regen_domains
  systemctl restart "$HEALTH_SERVICE"
}

add_domain(){
  local kind="$1" raw="$2" d file other
  d="$(normalize_domain "$raw")"
  valid_domain "$d" || { echo "Некорректный домен: $d" >&2; exit 2; }
  if [[ "$kind" == vpn ]]; then file="$VD"; other="$DD"; else file="$DD"; other="$VD"; fi
  grep -Fxq "$d" "$file" || echo "$d" >>"$file"
  # Exact duplicate in opposite list is ambiguous; keep hierarchy exceptions, remove only exact duplicate.
  grep -Fxv "$d" "$other" >"$other.tmp" || true; mv "$other.tmp" "$other"
  sort -u -o "$file" "$file"; sort -u -o "$other" "$other"
  regen_domains
  echo "OK: $kind add $d"
}
del_domain(){
  local kind="$1" raw="$2" d file
  d="$(normalize_domain "$raw")"
  file="$VD"; [[ "$kind" == direct ]] && file="$DD"
  grep -Fxv "$d" "$file" >"$file.tmp" || true; mv "$file.tmp" "$file"
  regen_domains
  echo "OK: $kind del $d"
}

client_cmd(){
  local action="${1:-}" ip="${2:-}"
  case "$action" in
    list)
      echo "=== PBR client allow-list ==="
      if grep -Ev '^\s*(#|$)' "$CF" | grep -q .; then cat "$CF"; else echo "(пусто: все устройства с gateway=Pi участвуют в PBR)"; fi
      ;;
    add)
      valid_ipv4 "$ip" || { echo "Некорректный IPv4: $ip" >&2; exit 2; }
      grep -Fxq "$ip" "$CF" || echo "$ip" >>"$CF"; sort -u -o "$CF" "$CF"
      reload_all; echo "OK: client add $ip"
      ;;
    del)
      valid_ipv4 "$ip" || { echo "Некорректный IPv4: $ip" >&2; exit 2; }
      grep -Fxv "$ip" "$CF" >"$CF.tmp" || true; mv "$CF.tmp" "$CF"
      reload_all; echo "OK: client del $ip"
      ;;
    *) usage; exit 2 ;;
  esac
}

vpn_switch(){
  local state="$1"
  case "$state" in
    on)
      echo 1 >"$VE"
      systemctl restart "$HEALTH_SERVICE"
      sleep 2
      echo "VPN policy разрешён. Он включится только если health-check успешен."
      ;;
    off)
      echo 0 >"$VE"
      "$FAILOPEN"
      systemctl restart "$HEALTH_SERVICE"
      echo "VPN policy выключен; все маршруты DIRECT. Сам туннель awg0 не удалён."
      ;;
    *) usage; exit 2 ;;
  esac
}

show_status(){
  local age enabled
  enabled="$(cat "$VE" 2>/dev/null || echo 1)"
  age="$(handshake_age)"
  echo "=== Gateway ==="
  printf 'LAN: %s  Pi: %s  Router: %s  Network: %s\n' "$LAN_IF" "$PI_IP" "$ROUTER_IP" "$LAN_CIDR"
  printf 'VPN policy requested: %s\n' "$([[ "$enabled" == 1 ]] && echo ON || echo OFF)"
  printf 'Health state: %s\n' "$(health_state)"
  printf 'Policy rule: %s\n' "$(policy_present && echo ACTIVE || echo FAIL-OPEN/DIRECT)"
  if (( age >= 0 )); then printf 'Latest handshake age: %ss\n' "$age"; else echo 'Latest handshake: отсутствует'; fi
  echo
  echo "=== Services ==="
  for s in awg-pbr-setup.service dnsmasq.service "awg-quick@$VPN_IF.service" awg-pbr-health.service; do
    printf '%-28s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || true)"
  done
  echo
  echo "=== Rules ==="
  printf 'VPN domains: %s\n' "$(grep -Evc '^\s*(#|$)' "$VD" 2>/dev/null || true)"
  printf 'DIRECT exceptions: %s\n' "$(grep -Evc '^\s*(#|$)' "$DD" 2>/dev/null || true)"
  printf 'Client allow-list: %s\n' "$(grep -Evc '^\s*(#|$)' "$CF" 2>/dev/null || true)"
  echo
  echo "=== AWG ==="
  awg show "$VPN_IF" 2>/dev/null || echo "awg0 недоступен"
}

test_domain(){
  local raw="$1" d ips ip in_vpn in_direct mark route
  d="$(normalize_domain "$raw")"; valid_domain "$d" || { echo "Некорректный домен: $d" >&2; exit 2; }
  echo "=== Test: $d ==="
  ips="$(dig +time=4 +tries=1 +short A "$d" @"$PI_IP" | grep -E '^[0-9]+(\.[0-9]+){3}$' || true)"
  [[ -n "$ips" ]] || { echo "DNS: A-записи не получены"; exit 1; }
  echo "DNS via Pi:"
  printf '%s\n' "$ips" | sed 's/^/  /'
  echo
  while IFS= read -r ip; do
    in_vpn=no; in_direct=no
    nft list set inet awg_pbr vpn4 2>/dev/null | grep -qw "$ip" && in_vpn=yes || true
    nft list set inet awg_pbr direct4 2>/dev/null | grep -qw "$ip" && in_direct=yes || true
    if [[ "$in_direct" == yes ]]; then mark=0; elif [[ "$in_vpn" == yes ]]; then mark="$VPN_MARK"; else mark=0; fi
    route="$(ip -4 route get "$ip" mark "$mark" 2>&1 | head -1 || true)"
    printf '%s  vpn-set=%s direct-set=%s mark=%s\n  route: %s\n' "$ip" "$in_vpn" "$in_direct" "$mark" "$route"
  done <<<"$ips"
  echo
  echo "Policy: $(policy_present && echo 'VPN rule active' || echo 'fail-open/direct')"
}

run_diagnostics(){
  local report tmpconf age direct_ip="" health_ok=no mark_test="" prev_health_active=no manual
  report="$LOG_DIR/diagnostics-$(date +%Y%m%d-%H%M%S).txt"
  tmpconf=/etc/dnsmasq.d/98-awg-diagnostics-temp.conf
  manual="$(cat "$VE" 2>/dev/null || echo 1)"
  systemctl is-active --quiet "$HEALTH_SERVICE" && prev_health_active=yes || true

  {
    echo "=== AWG Gateway diagnostics ==="
    echo "Date: $(date -Is)"
    echo "Host: $(hostname)"
    echo "Model: $(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo unknown)"
    echo "OS: $(. /etc/os-release; echo "${PRETTY_NAME:-unknown}")"
    echo "Kernel: $(uname -srmo)"
    echo "awg: $(awg --version 2>/dev/null || echo unavailable)"
    echo "amneziawg-go: $(amneziawg-go --version 2>/dev/null || echo unavailable)"
    echo "dnsmasq: $(dnsmasq --version 2>/dev/null | head -1 || true)"
    echo
    echo "--- Network ---"
    ip -br -4 addr show
    ip -4 route show
    echo
    echo "Router ping:"
    if ping -4 -c1 -W2 "$ROUTER_IP" >/dev/null 2>&1; then echo "OK $ROUTER_IP"; else echo "FAIL $ROUTER_IP"; fi
    echo
    echo "--- Direct internet/DNS ---"
    direct_dns_ok=no
    IFS=',' read -ra _dns_diag <<<"${UPSTREAM_DNS:-1.1.1.1,9.9.9.9}"
    for _d in "${_dns_diag[@]}"; do
      _d="${_d//[[:space:]]/}"
      if dig +time=3 +tries=1 +short A example.com @"$_d" | grep -qE '^[0-9]+\.'; then direct_dns_ok=yes; break; fi
    done
    echo "Direct DNS: $direct_dns_ok"
    for u in https://api.ipify.org https://icanhazip.com https://ifconfig.me/ip; do
      direct_ip="$(curl -4fsS --interface "$LAN_IF" --max-time 6 "$u" 2>/dev/null | tr -d '\r\n ' || true)"
      [[ "$direct_ip" =~ ^[0-9]+(\.[0-9]+){3}$ ]] && break
    done
    echo "Direct public IPv4: ${direct_ip:-unavailable}"
    echo
    echo "--- DNS via Pi ---"
    if dig +time=3 +tries=1 +short A example.com @"$PI_IP" | grep -qE '^[0-9]+\.'; then echo "dnsmasq query: OK"; else echo "dnsmasq query: FAIL"; fi
    echo
    echo "--- Services ---"
    for s in awg-pbr-setup.service dnsmasq.service "awg-quick@$VPN_IF.service" awg-pbr-health.service; do
      echo "$s: $(systemctl is-active "$s" 2>/dev/null || true) / enabled=$(systemctl is-enabled "$s" 2>/dev/null || true)"
    done
    echo
    echo "--- AWG ---"
    awg show "$VPN_IF" 2>/dev/null || true
    age="$(handshake_age)"
    echo "Handshake age: $age"
    echo "Health state: $(health_state)"
    echo "Policy present: $(policy_present && echo yes || echo no)"
    echo
    echo "--- Policy routing ---"
    ip -4 rule show
    ip -4 route show table "$VPN_TABLE" 2>/dev/null || true
    mark_test="$(ip -4 route get 1.1.1.1 mark "$VPN_MARK" 2>&1 | head -1 || true)"
    echo "Route with VPN mark: $mark_test"
    echo
    echo "--- nftables owned table ---"
    nft list table inet awg_pbr 2>/dev/null || true
    echo
    echo "--- Domain lists ---"
    echo "VPN domains:"; sed 's/^/  /' "$VD" 2>/dev/null || true
    echo "DIRECT domains:"; sed 's/^/  /' "$DD" 2>/dev/null || true
    echo "Clients:"; sed 's/^/  /' "$CF" 2>/dev/null || true
    echo
    echo "--- VPN transport health ---"
    if ip link show "$VPN_IF" >/dev/null 2>&1; then
      ip -4 route replace default dev "$VPN_IF" table "$HEALTH_TABLE" 2>/dev/null || true
      if ! ip -4 rule show | grep -Eq '(^| )90:.*fwmark (0x101|257).*lookup (101|awghealth)'; then
        ip -4 rule add priority 90 fwmark "$HEALTH_MARK" lookup "$HEALTH_TABLE" 2>/dev/null || true
      fi
      if ping -4 -n -m "$HEALTH_MARK" -c1 -W3 1.1.1.1 >/dev/null 2>&1 || ping -4 -n -m "$HEALTH_MARK" -c1 -W3 9.9.9.9 >/dev/null 2>&1; then health_ok=yes; fi
    fi
    echo "VPN transport ping: $health_ok"
    echo
    echo "--- dnsmasq -> nftset functional test ---"
  } | tee "$report"

  # Functional nftset test: temporary set + temporary dnsmasq rule, then cleanup.
  local nftset_result=FAIL
  nft delete set inet awg_pbr diag4 2>/dev/null || true
  if nft add set inet awg_pbr diag4 '{ type ipv4_addr; flags timeout; timeout 5m; }' 2>/dev/null; then
    echo 'nftset=/example.com/4#inet#awg_pbr#diag4' >"$tmpconf"
    if dnsmasq --test >/dev/null 2>&1 && systemctl restart dnsmasq && sleep 1; then
      dig +time=3 +tries=1 +short A example.com @"$PI_IP" >/dev/null 2>&1 || true
      if nft list set inet awg_pbr diag4 2>/dev/null | grep -q 'elements'; then nftset_result=OK; fi
    fi
  fi
  echo "dnsmasq nftset insertion: $nftset_result" | tee -a "$report"
  rm -f "$tmpconf"
  nft delete set inet awg_pbr diag4 2>/dev/null || true
  systemctl restart dnsmasq >/dev/null 2>&1 || true

  # Fail-open simulation. Short controlled interruption of policy rule only.
  echo | tee -a "$report"
  echo "--- FAIL-OPEN simulation ---" | tee -a "$report"
  if [[ "$prev_health_active" == yes ]]; then systemctl stop "$HEALTH_SERVICE" >/dev/null 2>&1 || true; fi
  "$FAILOPEN" >/dev/null 2>&1 || true
  local failroute
  failroute="$(ip -4 route get 1.1.1.1 mark "$VPN_MARK" 2>&1 | head -1 || true)"
  echo "Route after policy removal: $failroute" | tee -a "$report"
  if grep -q "dev $LAN_IF" <<<"$failroute"; then
    echo "FAIL-OPEN: OK (falls back to LAN/main route)" | tee -a "$report"
  else
    echo "FAIL-OPEN: FAIL" | tee -a "$report"
  fi
  if [[ "$prev_health_active" == yes ]]; then systemctl start "$HEALTH_SERVICE" >/dev/null 2>&1 || true; fi
  if [[ "$manual" == 0 ]]; then "$FAILOPEN" >/dev/null 2>&1 || true; fi

  echo | tee -a "$report"
  echo "Report: $report" | tee -a "$report"
  chmod 600 "$report"
  prune_reports
}

cmd="${1:-}"; action="${2:-}"; val="${3:-}"
case "$cmd" in
  vpn)
    case "$action" in
      add) [[ -n "$val" ]] || { usage; exit 2; }; add_domain vpn "$val" ;;
      del) [[ -n "$val" ]] || { usage; exit 2; }; del_domain vpn "$val" ;;
      on|off) vpn_switch "$action" ;;
      *) usage; exit 2 ;;
    esac
    ;;
  direct)
    case "$action" in
      add) [[ -n "$val" ]] || { usage; exit 2; }; add_domain direct "$val" ;;
      del) [[ -n "$val" ]] || { usage; exit 2; }; del_domain direct "$val" ;;
      *) usage; exit 2 ;;
    esac
    ;;
  client) client_cmd "$action" "$val" ;;
  list)
    echo "=== VPN domains ==="; cat "$VD" 2>/dev/null || true
    echo; echo "=== DIRECT exceptions ==="; cat "$DD" 2>/dev/null || true
    echo; echo "=== Client allow-list ==="; if grep -Ev '^\s*(#|$)' "$CF" 2>/dev/null | grep -q .; then cat "$CF"; else echo "(пусто = все Pi-gateway clients)"; fi
    ;;
  status) show_status ;;
  test) [[ -n "$action" ]] || { usage; exit 2; }; test_domain "$action" ;;
  reload) reload_all; echo "OK: configuration reloaded" ;;
  diagnostics) run_diagnostics ;;
  logs)
    n="${action:-150}"; [[ "$n" =~ ^[0-9]+$ ]] || n=150
    journalctl --no-pager -n "$n" -u "awg-quick@$VPN_IF.service" -u awg-pbr-health.service -u dnsmasq.service -u awg-pbr-setup.service
    ;;
  *) usage; exit 2 ;;
esac
EOF
chmod 755 "$ROUTE_CLI"

# v1.1.0 helpers are maintained as standalone repository files so the TUI and
# source manager can be audited independently of this installer.
STAGE="установка компонентов v1.1.0"
log "[8b/12] CLI v1.1.0 + OpenCCK + SSH TUI"
install_project_helper(){
  local remote="$1" target="$2" tmp
  tmp="$(mktemp)"
  curl -4fLsS --retry 3 --connect-timeout 8 --max-time 45 "$PROJECT_RAW_BASE/$remote" -o "$tmp" \
    || die "Не удалось загрузить $remote из проекта ($PROJECT_REF)"
  bash -n "$tmp" || die "Синтаксическая проверка $remote не пройдена"
  install -m 755 "$tmp" "$target"
  rm -f "$tmp"
}
mkdir -p /usr/local/lib/awg-pi
install_project_helper src/awg-common /usr/local/lib/awg-pi/common.sh
chmod 644 /usr/local/lib/awg-pi/common.sh
install_project_helper src/awg-route "$ROUTE_CLI"
install_project_helper src/awg-opencck-update /usr/local/sbin/awg-opencck-update
install_project_helper src/awg-core-update /usr/local/sbin/awg-core-update
install_project_helper src/awg-update "$UPDATE_SCRIPT"
install_project_helper src/awg-menu /usr/local/sbin/awg-menu

mkdir -p /etc/awg-pbr/sources/opencck/metadata
chmod 700 /etc/awg-pbr/sources /etc/awg-pbr/sources/opencck /etc/awg-pbr/sources/opencck/metadata
printf '%s\n' "$VERSION" >/etc/awg-pbr/version
chmod 600 /etc/awg-pbr/version

cat >/etc/systemd/system/awg-opencck-update.service <<'EOF'
[Unit]
Description=AWG Pi Gateway OpenCCK source updater
Wants=network-online.target
After=network-online.target dnsmasq.service awg-pbr-setup.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/awg-opencck-update
EOF

cat >/etc/systemd/system/awg-opencck-update.timer <<'EOF'
[Unit]
Description=Periodic OpenCCK source update for AWG Pi Gateway

[Timer]
OnBootSec=10min
OnUnitActiveSec=12h
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat >/etc/profile.d/awg-menu.sh <<'EOF'
# AWG Pi Gateway: open TUI only for an interactive SSH login.
# Set AWG_MENU_DISABLE=1 before login command execution to bypass it.
if [ -n "${SSH_CONNECTION:-}" ] && [ -t 0 ] && [ -t 1 ] && [ "${AWG_MENU_DISABLE:-0}" != 1 ] && [ ! -e "${HOME:-/nonexistent}/.no-awg-menu" ] && [ -x /usr/local/sbin/awg-menu ]; then
  if [ "${AWG_MENU_ACTIVE:-0}" != 1 ]; then
    export AWG_MENU_ACTIVE=1
    sudo /usr/local/sbin/awg-menu
    _awg_menu_rc=$?
    if [ "$_awg_menu_rc" -eq 20 ]; then
      exit
    fi
    unset _awg_menu_rc
  fi
fi
EOF
chmod 644 /etc/profile.d/awg-menu.sh

# -----------------------------------------------------------------------------
# 9. Fail-open health monitor
# -----------------------------------------------------------------------------
STAGE="настройка health-check и fail-open"
log "[9/12] Health monitor + FAIL-OPEN"
cat >"$HEALTH_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC1091
source /etc/awg-pbr/env
VE=/etc/awg-pbr/vpn-enabled
STATE_DIR=/run/awg-pbr
STATE="$STATE_DIR/health.state"
mkdir -p "$STATE_DIR"

rule_on(){
  ip -4 route replace default dev "$VPN_IF" table "$VPN_TABLE"
  if ! ip -4 rule show | grep -Eq '(^| )100:.*fwmark (0x100|256).*lookup (100|awgvpn)'; then
    ip -4 rule add priority 100 fwmark "$VPN_MARK" lookup "$VPN_TABLE"
  fi
  if [[ "$(cat "$STATE" 2>/dev/null || true)" != up ]]; then
    echo up >"$STATE"
    logger -t awg-pbr "VPN healthy: policy route enabled"
  fi
}
rule_off(){
  while ip -4 rule del priority 100 fwmark "$VPN_MARK" lookup "$VPN_TABLE" 2>/dev/null; do :; done
  if [[ "$(cat "$STATE" 2>/dev/null || true)" != down ]]; then
    echo down >"$STATE"
    logger -t awg-pbr "VPN unavailable/disabled: FAIL-OPEN to normal Internet"
  fi
}
health_prepare(){
  ip -4 route replace default dev "$VPN_IF" table "$HEALTH_TABLE" 2>/dev/null || true
  if ! ip -4 rule show | grep -Eq '(^| )90:.*fwmark (0x101|257).*lookup (101|awghealth)'; then
    ip -4 rule add priority 90 fwmark "$HEALTH_MARK" lookup "$HEALTH_TABLE" 2>/dev/null || true
  fi
}
handshake_fresh(){
  local hs now
  hs="$(awg show "$VPN_IF" latest-handshakes 2>/dev/null | awk '$2>m{m=$2}END{print m+0}')"
  [[ "$hs" -gt 0 ]] || return 1
  now="$(date +%s)"
  (( now - hs <= HANDSHAKE_MAX_AGE ))
}
transport_ok(){
  # Ping itself stimulates a handshake when needed.
  ping -4 -n -m "$HEALTH_MARK" -c1 -W2 1.1.1.1 >/dev/null 2>&1 || \
  ping -4 -n -m "$HEALTH_MARK" -c1 -W2 9.9.9.9 >/dev/null 2>&1
}

trap 'rule_off' EXIT INT TERM
rule_off
while true; do
  if [[ "$(cat "$VE" 2>/dev/null || echo 1)" != 1 ]]; then
    rule_off
    sleep "$HEALTH_INTERVAL"
    continue
  fi
  if ip link show "$VPN_IF" >/dev/null 2>&1; then
    health_prepare
    if transport_ok && handshake_fresh; then rule_on; else rule_off; fi
  else
    rule_off
  fi
  sleep "$HEALTH_INTERVAL"
done
EOF
chmod 755 "$HEALTH_SCRIPT"

cat >"$HEALTH_SERVICE" <<'EOF'
[Unit]
Description=AmneziaWG fail-open health monitor
After=network-online.target awg-quick@awg0.service awg-pbr-setup.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/awg-pbr-health
ExecStopPost=/usr/local/sbin/awg-pbr-failopen
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

# -----------------------------------------------------------------------------
# 10. Updater with rollback
# -----------------------------------------------------------------------------
STAGE="создание обновлятора"
log "[10/12] awg-update"
cat >"$UPDATE_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"
export PATH=/usr/local/go/bin:$PATH
SRC_ROOT=/opt/amneziawg-src
VPN_IF=awg0
BACKUP_ROOT=/var/backups/awg-gateway
VE=/etc/awg-pbr/vpn-enabled
MANUAL_VPN="$(cat "$VE" 2>/dev/null || echo 1)"
GO_REPO=https://github.com/amnezia-vpn/amneziawg-go.git
TOOLS_REPO=https://github.com/amnezia-vpn/amneziawg-tools.git
mkdir -p "$BACKUP_ROOT"

latest(){ git ls-remote --tags --refs "$1" 'refs/tags/v*' | awk -F/ '{print $3}' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+' | sort -V | tail -1; }
install_go(){
  local arch j f s t
  case "$(uname -m)" in aarch64|arm64) arch=arm64;; *) echo "Unsupported arch" >&2; return 1;; esac
  j="$(curl -fsSL --max-time 30 https://go.dev/dl/?mode=json)"
  f="$(jq -r --arg a "$arch" '.[0].files[]|select(.os=="linux" and .arch==$a and .kind=="archive")|.filename' <<<"$j" | head -1)"
  s="$(jq -r --arg a "$arch" '.[0].files[]|select(.os=="linux" and .arch==$a and .kind=="archive")|.sha256' <<<"$j" | head -1)"
  [[ -n "$f" && "$f" != null && -n "$s" && "$s" != null ]] || return 1
  t="/tmp/$f"; curl -fL --retry 3 "https://go.dev/dl/$f" -o "$t"; echo "$s  $t" | sha256sum -c -
  rm -rf /usr/local/go; tar -C /usr/local -xzf "$t"; rm -f "$t"
}
sync_repo(){
  local repo="$1" dir="$2" tag="$3"
  if [[ -d "$dir/.git" ]]; then git -C "$dir" fetch --tags --prune origin; else git clone "$repo" "$dir"; fi
  git -C "$dir" checkout -f "$tag"; git -C "$dir" reset --hard "$tag"
}

curl -4fsSI --max-time 8 https://github.com >/dev/null || { echo "GitHub недоступен" >&2; exit 1; }
GT="$(latest "$GO_REPO")"; TT="$(latest "$TOOLS_REPO")"
[[ -n "$GT" && -n "$TT" ]] || { echo "Не удалось определить стабильные теги" >&2; exit 1; }
CURG="$(git -C "$SRC_ROOT/amneziawg-go" describe --tags --exact-match 2>/dev/null || echo unknown)"
CURT="$(git -C "$SRC_ROOT/amneziawg-tools" describe --tags --exact-match 2>/dev/null || echo unknown)"
echo "Installed: go=$CURG tools=$CURT"
echo "Latest:    go=$GT tools=$TT"
if [[ "$CURG" == "$GT" && "$CURT" == "$TT" ]]; then echo "Уже установлены последние стабильные теги."; exit 0; fi
read -r -p "Обновить? [Y/n]: " ans </dev/tty; ans="${ans:-Y}"; [[ "$ans" =~ ^[YyДд] ]] || exit 0

# Update Go first so future AWG module requirements do not break the build.
install_go
export PATH=/usr/local/go/bin:$PATH

OLD_GO_REF="$(git -C "$SRC_ROOT/amneziawg-go" rev-parse HEAD 2>/dev/null || true)"
OLD_TOOLS_REF="$(git -C "$SRC_ROOT/amneziawg-tools" rev-parse HEAD 2>/dev/null || true)"
sync_repo "$GO_REPO" "$SRC_ROOT/amneziawg-go" "$GT"
sync_repo "$TOOLS_REPO" "$SRC_ROOT/amneziawg-tools" "$TT"

make -C "$SRC_ROOT/amneziawg-go" clean >/dev/null 2>&1 || true
make -C "$SRC_ROOT/amneziawg-go"
make -C "$SRC_ROOT/amneziawg-tools/src" clean >/dev/null 2>&1 || true
make -C "$SRC_ROOT/amneziawg-tools/src"

BK="$BACKUP_ROOT/update-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"; chmod 700 "$BK"
for f in /usr/bin/amneziawg-go /usr/bin/awg /usr/bin/awg-quick; do [[ -f "$f" ]] && cp -a "$f" "$BK/"; done
UNIT="$(systemctl show -p FragmentPath --value awg-quick@awg0.service 2>/dev/null || true)"
[[ -f "$UNIT" ]] && { cp -a "$UNIT" "$BK/awg-quick@.service"; echo "$UNIT" >"$BK/unit-path"; }

echo "Fail-open before replacing binaries..."
systemctl stop awg-pbr-health.service || true
/usr/local/sbin/awg-pbr-failopen || true
systemctl stop "awg-quick@$VPN_IF.service" || true
# Temporarily enable policy only for update health verification; restore user state afterwards.
echo 1 >"$VE"

rollback(){
  echo "UPDATE FAILED -> rollback" >&2
  systemctl stop "awg-quick@$VPN_IF.service" >/dev/null 2>&1 || true
  for f in amneziawg-go awg awg-quick; do [[ -f "$BK/$f" ]] && install -m755 "$BK/$f" "/usr/bin/$f"; done
  if [[ -f "$BK/awg-quick@.service" && -f "$BK/unit-path" ]]; then cp -a "$BK/awg-quick@.service" "$(cat "$BK/unit-path")"; fi
  [[ -n "$OLD_GO_REF" ]] && git -C "$SRC_ROOT/amneziawg-go" checkout -f "$OLD_GO_REF" >/dev/null 2>&1 || true
  [[ -n "$OLD_TOOLS_REF" ]] && git -C "$SRC_ROOT/amneziawg-tools" checkout -f "$OLD_TOOLS_REF" >/dev/null 2>&1 || true
  systemctl daemon-reload
  echo "$MANUAL_VPN" >"$VE"
  systemctl start "awg-quick@$VPN_IF.service" || true
  systemctl start awg-pbr-health.service || true
  [[ "$MANUAL_VPN" == 1 ]] || /usr/local/sbin/awg-pbr-failopen || true
  exit 1
}
trap rollback ERR

make -C "$SRC_ROOT/amneziawg-go" PREFIX=/usr install
make -C "$SRC_ROOT/amneziawg-tools/src" install PREFIX=/usr WITH_WGQUICK=yes WITH_SYSTEMDUNITS=yes
systemctl daemon-reload
systemctl start "awg-quick@$VPN_IF.service"
systemctl start awg-pbr-health.service

ok=0
for _ in $(seq 1 12); do
  sleep 3
  if [[ "$(cat /run/awg-pbr/health.state 2>/dev/null || true)" == up ]]; then ok=1; break; fi
done
(( ok == 1 )) || { echo "Новый AWG не прошёл health-check" >&2; false; }
trap - ERR
echo "$MANUAL_VPN" >"$VE"
systemctl restart awg-pbr-health.service || true
[[ "$MANUAL_VPN" == 1 ]] || /usr/local/sbin/awg-pbr-failopen || true

echo "Update OK"
awg --version || true
amneziawg-go --version || true
/usr/local/sbin/awg-route diagnostics || true
find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d -name 'update-*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR>5{sub(/^[^ ]+ /,""); print}' | xargs -r rm -rf
EOF
chmod 755 "$UPDATE_SCRIPT"

# -----------------------------------------------------------------------------
# 11. Start services and critical tests
# -----------------------------------------------------------------------------
STAGE="первый запуск и критические проверки"
log "[11/12] Первый запуск"
systemctl daemon-reload
systemctl enable awg-pbr-setup.service dnsmasq.service "awg-quick@$VPN_IF.service" awg-pbr-health.service awg-opencck-update.timer >/dev/null

systemctl restart awg-pbr-setup.service
nft list table inet awg_pbr >/dev/null 2>&1 || die "Не создана nftables table inet awg_pbr"
ok "nftables PBR table создана"

systemctl restart dnsmasq.service
systemctl is-active --quiet dnsmasq.service || {
  systemctl status dnsmasq.service --no-pager || true
  die "dnsmasq не запустился. Частая причина: порт 53 уже занят"
}
if ! dig +time=3 +tries=1 +short A example.com @"$PI_IP" | grep -qE '^[0-9]+\.'; then
  die "DNS через Raspberry Pi ($PI_IP:53) не работает"
fi
ok "DNS Raspberry Pi работает"

systemctl restart "awg-quick@$VPN_IF.service"
systemctl is-active --quiet "awg-quick@$VPN_IF.service" || {
  systemctl status "awg-quick@$VPN_IF.service" --no-pager || true
  journalctl -u "awg-quick@$VPN_IF.service" -n 80 --no-pager || true
  die "awg0 не поднялся"
}
ip link show "$VPN_IF" >/dev/null 2>&1 || die "Сервис AWG активен, но интерфейс $VPN_IF отсутствует"
ok "$VPN_IF поднят"

systemctl restart awg-pbr-health.service
systemctl is-active --quiet awg-pbr-health.service || die "health monitor не запустился"
systemctl start awg-opencck-update.timer
systemctl is-active --quiet awg-opencck-update.timer || warn "OpenCCK timer не активен; ручное обновление останется доступно"

printf "Ожидание handshake/проверки VPN"
VPN_HEALTH=0
for _ in $(seq 1 15); do
  sleep 2
  printf "."
  if [[ "$(cat /run/awg-pbr/health.state 2>/dev/null || true)" == "up" ]]; then VPN_HEALTH=1; break; fi
done
printf "\n"
if (( VPN_HEALTH == 0 )); then
  awg show "$VPN_IF" || true
  journalctl -u awg-pbr-health.service -n 50 --no-pager || true
  die "VPN не прошёл health-check: нет рабочего транспорта и/или свежего handshake. PBR не активирован"
fi
ok "AmneziaWG: handshake + интернет через туннель работают"

if ! ip -4 rule show | grep -Eq '(^| )100:.*fwmark (0x100|256).*lookup (100|awgvpn)'; then
  die "Health успешен, но policy rule не активировался"
fi
if ! ip -4 route get 1.1.1.1 mark "$VPN_MARK" | grep -q "dev $VPN_IF"; then
  die "Маркированный трафик не маршрутизируется в $VPN_IF"
fi
ok "Policy routing работает"

# -----------------------------------------------------------------------------
# 12. Deep diagnostics + summary
# -----------------------------------------------------------------------------
STAGE="финальная диагностика"
log "[12/12] Полная диагностика"
"$ROUTE_CLI" reload
"$ROUTE_CLI" diagnostics

LATEST_DIAG="$(find "$LOG_DIR" -maxdepth 1 -type f -name 'diagnostics-*.txt' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"

printf "\n%b=== УСТАНОВКА ЗАВЕРШЕНА ===%b\n" "$G$B" "$R"
printf "Raspberry Pi:    %s\n" "$PI_IP"
printf "MAC (%s):       %s\n" "$LAN_IF" "$LAN_MAC"
printf "Archer C64:      %s\n" "$ROUTER_IP"
printf "LAN:             %s\n" "$LAN_CIDR"
printf "VPN interface:   %s\n" "$VPN_IF"
printf "AWG tags:        go=%s tools=%s\n" "$GO_TAG" "$TOOLS_TAG"
printf "Install report:  %s\n" "$INSTALL_REPORT"
printf "Diagnostics:     %s\n" "${LATEST_DIAG:-см. $LOG_DIR}"

printf "\nЛогика:\n"
printf "  обычный трафик = DIRECT через Archer C64\n"
printf "  VPN-list = через AmneziaWG\n"
printf "  VPN упал = автоматический FAIL-OPEN DIRECT\n"
printf "  DHCP остаётся на Archer C64\n"
printf "  DNS клиентов PBR = %s (dnsmasq -> независимые upstream DNS)\n" "$PI_IP"

printf "\nОсновные команды:\n"
printf "  sudo awg-route status\n"
printf "  sudo awg-route vpn add youtube.com\n"
printf "  sudo awg-route vpn del youtube.com\n"
printf "  sudo awg-route direct add example.com\n"
printf "  sudo awg-route client add 192.168.0.50\n"
printf "  sudo awg-route client list\n"
printf "  sudo awg-route vpn on\n"
printf "  sudo awg-route vpn off\n"
printf "  sudo awg-route test youtube.com\n"
printf "  sudo awg-route diagnostics\n"
printf "  sudo awg-route logs\n"
printf "  sudo awg-route reload\n"
printf "  sudo awg-route vpn import FILE\n"
printf "  sudo awg-route source add opencck youtube\n"
printf "  sudo awg-route source list\n"
printf "  sudo awg-menu\n"
printf "  sudo awg-update status\n"
printf "  sudo awg-update gateway\n"
printf "  sudo awg-update core\n"

printf "\nДля первого тестового устройства (LG TV):\n"
printf "  IPv4:    свободный фиксированный адрес в %s\n" "$LAN_CIDR"
printf "  Gateway: %s\n" "$PI_IP"
printf "  DNS:     %s\n" "$PI_IP"
printf "  IPv6:    не использовать\n"

printf "\n%bВАЖНО:%b IP телевизора выбирайте вне конфликтов с DHCP либо закрепите его на Archer C64.\n" "$Y" "$R"
printf "После настройки LG сначала проверьте DIRECT, затем добавьте один тестовый домен в VPN-list.\n"
