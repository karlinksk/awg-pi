#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

AWG_PI_VERSION="1.3.0"
PROJECT_REF="${AWG_PI_REF:-v${AWG_PI_VERSION}}"
PROJECT_RAW_BASE="https://raw.githubusercontent.com/karlinksk/awg-pi/${PROJECT_REF}"
TTY=/dev/tty
STAGE="preflight"

VPN_IF="awg0"
CONF_DIR="/etc/amnezia/amneziawg"
CONF_FILE="$CONF_DIR/$VPN_IF.conf"
SRC_ROOT="/opt/amneziawg-src"
PBR_DIR="/etc/awg-pbr"
VERSION_FILE="$PBR_DIR/version"
PUBLIC_VERSION_DIR="/usr/share/awg-pbr"
PUBLIC_VERSION_FILE="$PUBLIC_VERSION_DIR/version"
ENV_FILE="$PBR_DIR/env"
VPN_DOMAINS="$PBR_DIR/vpn-domains.txt"
DIRECT_DOMAINS="$PBR_DIR/direct-domains.txt"
CLIENTS_FILE="$PBR_DIR/clients.txt"
VPN_ENABLED_FILE="$PBR_DIR/vpn-enabled"
MODE_FILE="$PBR_DIR/mode"
TRANSPORT_FILE="$PBR_DIR/transport"
DNS_CONF="/etc/dnsmasq.d/99-awg-pbr.conf"
DNS_DOMAINS_CONF="/etc/dnsmasq.d/99-awg-pbr-domains.conf"
NFT_FILE="/etc/nftables.d/99-awg-pbr.nft"
SETUP_SCRIPT="/usr/local/sbin/awg-pbr-setup"
FAILOPEN_SCRIPT="/usr/local/sbin/awg-pbr-failopen"
HEALTH_SCRIPT="/usr/local/sbin/awg-pbr-health"
ROUTE_CLI="/usr/local/sbin/awg-route"
TRANSPORT_CLI="/usr/local/sbin/awg-transport"
FETCH_CLI="/usr/local/sbin/awg-fetch"
MIHOMO_CONFIG_SCRIPT="/usr/local/sbin/awg-mihomo-config"
MIHOMO_UPDATE_SCRIPT="/usr/local/sbin/awg-mihomo-update"
MIHOMO_INSTALL_SCRIPT="/usr/local/sbin/awg-mihomo-install"
MIHOMO_PREPARE_SCRIPT="/usr/local/sbin/awg-mihomo-prepare"
MIHOMO_CONFIGURE_SCRIPT="/usr/local/sbin/awg-mihomo-configure"
MIHOMO_POOL_CLI="/usr/local/sbin/awg-mihomo-pool"
FIRST_RUN_CLI="/usr/local/sbin/awg-first-run"
SELECTION_CLI="/usr/local/sbin/awg-selection"
SELECTION_MONITOR="/usr/local/sbin/awg-selection-monitor"
MIHOMO_NODE_POLICY_CLI="/usr/local/sbin/awg-mihomo-node-policy"
UPDATE_SCRIPT="/usr/local/sbin/awg-update"
TRAFFIC_CLI="/usr/local/sbin/awg-traffic"
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
confirm_yes(){
  local v="$1"
  v="$(printf '%s' "$v" | tr -d '\\015' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  case "$v" in
    Y|y|YES|Yes|yes|Д|д|ДА|Да|да) return 0 ;;
    *) return 1 ;;
  esac
}
confirm(){
  local p="$1" d="${2:-N}" v s
  [[ "$d" =~ ^[YyДд]$ ]] && s="Y/n" || s="y/N"
  read -r -p "$p [$s]: " v <"$TTY"
  v="${v:-$d}"
  confirm_yes "$v"
}
valid_ipv4(){
  local IFS=. a b c d
  read -r a b c d <<<"$1" || return 1
  [[ $a =~ ^[0-9]+$ && $b =~ ^[0-9]+$ && $c =~ ^[0-9]+$ && $d =~ ^[0-9]+$ ]] || return 1
  ((a<=255 && b<=255 && c<=255 && d<=255))
}
valid_cidr4(){
  local x="$1" ip p
  ip="${x%/*}"; p="${x#*/}"
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

printf "%b=== AmneziaWG Raspberry Pi 4 Policy Gateway Installer v%s ===%b\n" "$B" "$AWG_PI_VERSION" "$R"
printf "Архитектура: Selective Gateway + MikroTik Transit / Backup VPN.\n"
printf "Fresh install начинается с безопасного transport=unconfigured. Selective: FAIL-OPEN; Transit: FAIL-CLOSED при недоступном active transport.\n"
printf "IPv6 в этой версии не маршрутизируется.\n\n"
printf "Журнал установки: %s\n\n" "$INSTALL_REPORT"

UPGRADE_EXISTING=0
# Fresh v1.3 installs stage safely in Selective + transport=unconfigured.
# The user chooses Operating Mode only after the first transport/recovery step.
ACTIVATE_TRANSIT_AFTER_INSTALL=0
AUTO_UPGRADE="${AWG_PI_UPGRADE_AUTO:-0}"
AUTO_TRANSIT="${AWG_PI_UPGRADE_TRANSIT:-}"
EXISTING_VERSION="$(cat "$PUBLIC_VERSION_FILE" 2>/dev/null || cat "$VERSION_FILE" 2>/dev/null || true)"
MODE_PREEXISTED=0
[[ -f "$MODE_FILE" ]] && MODE_PREEXISTED=1
if [[ -f "$ENV_FILE" ]]; then
  printf "Обнаружена существующая AWG Pi Gateway: %s\n" "${EXISTING_VERSION:-версия до v1.1.0}"
  if [[ "$AUTO_UPGRADE" == 1 ]] || confirm "Выполнить безопасное обновление существующей установки до v$AWG_PI_VERSION с сохранением AWG-конфига, доменов и клиентов?" "Y"; then
    UPGRADE_EXISTING=1
    ACTIVATE_TRANSIT_AFTER_INSTALL=0
    ok "Режим обновления: пользовательские списки и $CONF_FILE будут сохранены"
    if [[ "$EXISTING_VERSION" == 1.1.0 && "$MODE_PREEXISTED" == 0 ]]; then
      if [[ "$AUTO_UPGRADE" == 1 ]]; then
        case "$AUTO_TRANSIT" in
          1)
            ACTIVATE_TRANSIT_AFTER_INSTALL=1
            warn "Legacy v1.1.0 -> v1.3.0: подтверждена попытка включить MikroTik Transit / Backup VPN."
            ;;
          0)
            warn "Legacy v1.1.0 -> v1.3.0: подтверждено сохранение Selective Gateway."
            ;;
          *)
            warn "Unattended upgrade не получил явного AWG_PI_UPGRADE_TRANSIT=0|1; безопасно остаёмся в Selective Gateway."
            ;;
        esac
      elif confirm "После обновления включить новый режим MikroTik Transit / Backup VPN? Перед переключением будет выполнен preflight; при ошибке останется Selective Gateway." "Y"; then
        ACTIVATE_TRANSIT_AFTER_INSTALL=1
      else
        warn "Обновление продолжится в Selective Gateway."
      fi
    fi
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
  die "Отключите IPv6/RA на LAN router для этой схемы либо вернитесь к установке после отключения IPv6"
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
  iproute2 iputils-ping iputils-arping dnsutils nftables dnsmasq procps \
  python3-minimal python3-yaml openssl dialog

command -v nft >/dev/null || die "nft не установлен"
command -v dnsmasq >/dev/null || die "dnsmasq не установлен"
command -v dig >/dev/null || die "dig не установлен"
dnsmasq --version | grep -qi nftset || die "Установленный dnsmasq собран без поддержки nftset"
ok "dnsmasq поддерживает nftset"

# -----------------------------------------------------------------------------
# 3. Go
# -----------------------------------------------------------------------------
if (( UPGRADE_EXISTING == 1 )); then
  STAGE="проверка существующего AmneziaWG"
  log "[3-4/12] Сохраняем существующий AmneziaWG core"
  command -v awg >/dev/null || die "При обновлении не найден awg"
  command -v awg-quick >/dev/null || die "При обновлении не найден awg-quick"
  command -v amneziawg-go >/dev/null || die "При обновлении не найден amneziawg-go"
  GO_TAG="$(git -C "$SRC_ROOT/amneziawg-go" describe --tags --exact-match 2>/dev/null || echo installed)"
  TOOLS_TAG="$(git -C "$SRC_ROOT/amneziawg-tools" describe --tags --exact-match 2>/dev/null || echo installed)"
  ok "AmneziaWG core не изменяется при обновлении Gateway (go=$GO_TAG tools=$TOOLS_TAG)"
else
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
  git ls-remote --tags --refs "$1" 'refs/tags/v*' | awk -F/ '{print $3}' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1
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
fi

# -----------------------------------------------------------------------------
# 5. Preserve existing transport configuration; fresh choice happens later
# -----------------------------------------------------------------------------
STAGE="подготовка transport state"
log "[5/12] Transport state / existing backend preservation"
mkdir -p "$CONF_DIR" "$PBR_DIR" /etc/nftables.d
chmod 700 "$CONF_DIR" "$PBR_DIR"

AWG_CONFIG_PRESENT=0
if [[ -f "$CONF_FILE" ]]; then
  AWG_CONFIG_PRESENT=1
  if (( UPGRADE_EXISTING == 1 )); then
    cp -a "$CONF_FILE" "$CONF_FILE.bak.$(date +%Y%m%d-%H%M%S)"
    if ! awg-quick strip "$CONF_FILE" >/dev/null 2>&1; then
      die "Существующий AWG-конфиг не разбирается awg-quick; upgrade остановлен без изменения профиля"
    fi
    ok "Существующий AWG backend сохранён"
  else
    warn "На fresh install найден существующий $CONF_FILE; он не будет автоматически выбран. First-run wizard попросит явный выбор."
  fi
else
  if (( UPGRADE_EXISTING == 1 )); then
    warn "AWG-конфиг отсутствует; обновление продолжится без зависимости от AWG."
  else
    ok "Fresh install: transport пока не выбран"
  fi
fi

# -----------------------------------------------------------------------------
# 6. LAN/router parameters
# -----------------------------------------------------------------------------
STAGE="проверка локальной сети"
log "[6/12] LAN router и локальная сеть"
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
  # Mode framework stage: preserve any explicit mode; v1.1.x systems without
  # a mode file remain Selective until Transit datapath + preflight are implemented.
  [[ -f "$MODE_FILE" ]] || printf '%s\n' selective >"$MODE_FILE"
  chmod 600 "$MODE_FILE"
  if [[ ! -f "$TRANSPORT_FILE" ]]; then
    if (( AWG_CONFIG_PRESENT == 1 )); then
      printf '%s\n' awg >"$TRANSPORT_FILE"
      warn "Миграция legacy state: существующий AWG backend принят как active transport."
    else
      printf '%s\n' unconfigured >"$TRANSPORT_FILE"
    fi
  fi
  chmod 600 "$TRANSPORT_FILE"
  ok "Сетевая конфигурация сохранена: Pi=$PI_IP, Router=$ROUTER_IP, LAN=$LAN_CIDR"
else
printf "\nIPv4 интерфейсы:\n"
ip -br -4 addr show | sed 's/^/  /'
printf "Default route:\n"
ip -4 route show default | sed 's/^/  /'

UPLINK_IF="$(ip -4 route show default | awk 'NR==1{for(i=1;i<=NF;i++)if($i=="dev"){print $(i+1);exit}}')"
UPLINK_GW="$(ip -4 route show default | awk 'NR==1{for(i=1;i<=NF;i++)if($i=="via"){print $(i+1);exit}}')"
[[ -n "$UPLINK_IF" && -n "$UPLINK_GW" ]] || die "Не найден обычный IPv4 default route через LAN router"

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

ask "Постоянный IPv4 Raspberry Pi (должен быть зарезервирован на LAN router)" "$PI_IP"
PI_IP="$REPLY"
valid_ipv4 "$PI_IP" || die "Неверный IPv4 Raspberry Pi"
ip -o -4 addr show dev "$LAN_IF" | grep -qE "[[:space:]]${PI_IP}/" || die "$PI_IP сейчас не назначен $LAN_IF. Сначала создайте DHCP reservation на LAN router и обновите lease/перезагрузите Pi"

ask "Домашняя IPv4 подсеть" "$LAN_CIDR"
LAN_CIDR="$REPLY"
valid_cidr4 "$LAN_CIDR" || die "Неверная подсеть: $LAN_CIDR"
[[ "$(in_cidr "$PI_IP" "$LAN_CIDR")" == "yes" ]] || die "IP Raspberry Pi $PI_IP не принадлежит $LAN_CIDR"

ask "IP LAN router" "$UPLINK_GW"
ROUTER_IP="$REPLY"
valid_ipv4 "$ROUTER_IP" || die "Неверный IP роутера"
[[ "$(in_cidr "$ROUTER_IP" "$LAN_CIDR")" == "yes" ]] || die "IP LAN router $ROUTER_IP не принадлежит $LAN_CIDR"

if ! ping -4 -c 2 -W 2 "$ROUTER_IP" >/dev/null 2>&1; then
  die "LAN router ($ROUTER_IP) не отвечает с Raspberry Pi"
fi
ok "LAN router доступен: $ROUTER_IP"

printf "\nНа LAN router должна быть DHCP Reservation:\n  MAC: %s\n  IP:  %s\n" "$LAN_MAC" "$PI_IP"
confirm "Вы уже закрепили этот IP за MAC Raspberry Pi на LAN router?" "N" || die "Сначала настройте DHCP Reservation на LAN router, затем повторите установку"

ask "Upstream DNS для Raspberry Pi через запятую" "9.9.9.9,149.112.112.112"
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
printf '%s\n' selective >"$MODE_FILE"
chmod 600 "$MODE_FILE"
printf '%s\n' unconfigured >"$TRANSPORT_FILE"
chmod 600 "$TRANSPORT_FILE"
fi

# Duplicate-address detection. In DAD mode arping returns success when no peer
# answers for the address, so this is safe even though the Pi already owns PI_IP.
if command -v arping >/dev/null 2>&1; then
  if arping -D -I "$LAN_IF" -c 2 -w 3 "$PI_IP" >/dev/null 2>&1; then
    ok "Конфликт IPv4 не обнаружен: $PI_IP"
  else
    die "Обнаружен возможный конфликт IPv4 для $PI_IP в LAN. Проверьте DHCP reservation и занятые адреса"
  fi
else
  warn "arping не найден; проверка конфликта IPv4 пропущена"
fi

if [[ -n "${SSH_CONNECTION:-}" ]]; then
  SSH_SRC="${SSH_CONNECTION%% *}"
  ok "Текущая SSH-сессия обнаружена: source=$SSH_SRC; firewall сохранит SSH с LAN-интерфейса $LAN_IF"
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

# awg-pbr-setup is installed from src/awg-pbr-setup in section 8b.

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

# awg-route is installed from src/awg-route below.

# Runtime helpers are maintained as standalone repository files so routing,
# health, TUI and source-management behavior can be audited independently.
STAGE="установка компонентов v$AWG_PI_VERSION"
log "[8b/12] CLI v$AWG_PI_VERSION + Multi-Transport + OpenCCK + SSH TUI"
install_project_helper(){
  local remote="$1" target="$2" tmp
  tmp="$(mktemp)"
  curl -4fLsS --retry 3 --connect-timeout 8 --max-time 45 "$PROJECT_RAW_BASE/$remote" -o "$tmp" \
    || die "Не удалось загрузить $remote из проекта ($PROJECT_REF)"
  bash -n "$tmp" || die "Синтаксическая проверка $remote не пройдена"
  install -m 755 "$tmp" "$target"
  rm -f "$tmp"
}
install_project_unit(){
  local remote="$1" target="$2" tmp
  tmp="$(mktemp)"
  curl -4fLsS --retry 3 --connect-timeout 8 --max-time 45 "$PROJECT_RAW_BASE/$remote" -o "$tmp" \
    || die "Не удалось загрузить $remote из проекта ($PROJECT_REF)"
  install -m 644 "$tmp" "$target"
  rm -f "$tmp"
}
mkdir -p /usr/local/lib/awg-pi
install_project_helper src/awg-common /usr/local/lib/awg-pi/common.sh
chmod 644 /usr/local/lib/awg-pi/common.sh
_manage_tmp="$(mktemp)"
curl -4fLsS --retry 3 --connect-timeout 8 --max-time 45 "$PROJECT_RAW_BASE/src/awg-manage.py" -o "$_manage_tmp" || die "Не удалось загрузить awg-manage.py"
python3 -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' "$_manage_tmp" || die "Ошибка синтаксиса awg-manage.py"
install -m 755 "$_manage_tmp" /usr/local/lib/awg-pi/manage.py
rm -f "$_manage_tmp"

_mihomo_provider_tmp="$(mktemp)"
curl -4fLsS --retry 3 --connect-timeout 8 --max-time 45 "$PROJECT_RAW_BASE/src/awg-mihomo-provider.py" -o "$_mihomo_provider_tmp" \
  || die "Не удалось загрузить awg-mihomo-provider.py"
python3 -m py_compile "$_mihomo_provider_tmp" || die "Ошибка синтаксиса awg-mihomo-provider.py"
install -m 755 "$_mihomo_provider_tmp" /usr/local/lib/awg-pi/mihomo-provider.py
rm -f "$_mihomo_provider_tmp"

_mihomo_pool_tmp="$(mktemp)"
curl -4fLsS --retry 3 --connect-timeout 8 --max-time 45 "$PROJECT_RAW_BASE/src/awg-mihomo-pool.py" -o "$_mihomo_pool_tmp" \
  || die "Не удалось загрузить awg-mihomo-pool.py"
python3 -m py_compile "$_mihomo_pool_tmp" || die "Ошибка синтаксиса awg-mihomo-pool.py"
install -m 755 "$_mihomo_pool_tmp" "$MIHOMO_POOL_CLI"
rm -f "$_mihomo_pool_tmp"
install_project_helper src/awg-route "$ROUTE_CLI"
install_project_helper src/awg-transport "$TRANSPORT_CLI"
install_project_helper src/awg-fetch "$FETCH_CLI"
install_project_helper src/awg-mihomo-config "$MIHOMO_CONFIG_SCRIPT"
install_project_helper src/awg-mihomo-update "$MIHOMO_UPDATE_SCRIPT"
install_project_helper src/awg-mihomo-install "$MIHOMO_INSTALL_SCRIPT"
install_project_helper src/awg-mihomo-prepare "$MIHOMO_PREPARE_SCRIPT"
install_project_helper src/awg-mihomo-configure "$MIHOMO_CONFIGURE_SCRIPT"
install_project_helper src/awg-first-run "$FIRST_RUN_CLI"
install_project_helper src/awg-selection "$SELECTION_CLI"
install_project_helper src/awg-selection-monitor "$SELECTION_MONITOR"
install_project_helper src/awg-mihomo-node-policy "$MIHOMO_NODE_POLICY_CLI"
install_project_helper src/awg-pbr-setup "$SETUP_SCRIPT"
install_project_helper src/awg-transit-nft /usr/local/sbin/awg-transit-nft
install_project_helper src/awg-transit-preflight /usr/local/sbin/awg-transit-preflight
install_project_helper src/awg-transit-apply /usr/local/sbin/awg-transit-apply
install_project_helper src/awg-transit-routing /usr/local/sbin/awg-transit-routing
install_project_helper src/awg-mode-switch /usr/local/sbin/awg-mode-switch
install_project_helper src/awg-pbr-health "$HEALTH_SCRIPT"
install_project_helper src/awg-opencck-update /usr/local/sbin/awg-opencck-update
install_project_helper src/awg-core-update /usr/local/sbin/awg-core-update
install_project_helper src/awg-update "$UPDATE_SCRIPT"
install_project_helper src/awg-traffic "$TRAFFIC_CLI"
install_project_helper src/awg-menu /usr/local/sbin/awg-menu

mkdir -p /etc/awg-pbr/sources/opencck/metadata
mkdir -p /etc/awg-pbr/transports/mihomo /var/lib/awg-pbr/mihomo/providers /var/lib/awg-pbr/traffic
install -d -o root -g root -m 755 "$PUBLIC_VERSION_DIR"
chmod 700 /etc/awg-pbr/sources /etc/awg-pbr/sources/opencck /etc/awg-pbr/sources/opencck/metadata
chmod 700 /etc/awg-pbr/transports /etc/awg-pbr/transports/mihomo /var/lib/awg-pbr/mihomo /var/lib/awg-pbr/mihomo/providers /var/lib/awg-pbr/traffic

# Migrate an already-issued Citadel/Remnawave device identity out of the
# provider-specific env so switching to an ordinary subscription cannot lose it.
if [[ ! -s /etc/awg-pbr/transports/mihomo/remnawave.hwid && -r /etc/awg-pbr/transports/mihomo/provider.env ]]; then
  _existing_hwid="$(
    MIHOMO_PROVIDER_HWID=""
    # shellcheck disable=SC1091
    source /etc/awg-pbr/transports/mihomo/provider.env
    printf '%s' "${MIHOMO_PROVIDER_HWID:-}"
  )"
  if [[ "$_existing_hwid" =~ ^[A-Za-z0-9._:-]{8,128}$ ]]; then
    printf '%s\n' "$_existing_hwid" >/etc/awg-pbr/transports/mihomo/remnawave.hwid
    chmod 600 /etc/awg-pbr/transports/mihomo/remnawave.hwid
  fi
  unset _existing_hwid
fi
install_project_unit units/awg-mihomo.service /etc/systemd/system/awg-mihomo.service
install_project_unit units/awg-mihomo-update.service /etc/systemd/system/awg-mihomo-update.service
install_project_unit units/awg-mihomo-update.timer /etc/systemd/system/awg-mihomo-update.timer
install_project_unit units/awg-mihomo-pool-refresh.service /etc/systemd/system/awg-mihomo-pool-refresh.service
install_project_unit units/awg-mihomo-pool-refresh.timer /etc/systemd/system/awg-mihomo-pool-refresh.timer
install_project_unit units/awg-selection-monitor.service /etc/systemd/system/awg-selection-monitor.service
install_project_unit units/awg-traffic.service /etc/systemd/system/awg-traffic.service
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
# 9. Mode-aware health monitor
# -----------------------------------------------------------------------------
STAGE="настройка health-check"
log "[9/12] Health monitor: Selective FAIL-OPEN / Transit FAIL-CLOSED"
cat >"$HEALTH_SERVICE" <<'EOF'
[Unit]
Description=AWG Pi Gateway mode-aware health monitor
After=network-online.target awg-pbr-setup.service
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
# 10. Verify management/update components
# -----------------------------------------------------------------------------
STAGE="проверка компонентов управления"
log "[10/12] Проверка awg-route / awg-menu / awg-update"
for f in "$ROUTE_CLI" "$TRANSPORT_CLI" "$FETCH_CLI" "$MIHOMO_CONFIG_SCRIPT" "$MIHOMO_UPDATE_SCRIPT" "$MIHOMO_INSTALL_SCRIPT" "$MIHOMO_PREPARE_SCRIPT" "$MIHOMO_CONFIGURE_SCRIPT" "$FIRST_RUN_CLI" "$SELECTION_CLI" "$SELECTION_MONITOR" "$MIHOMO_NODE_POLICY_CLI" "$SETUP_SCRIPT" /usr/local/sbin/awg-menu /usr/local/sbin/awg-transit-nft /usr/local/sbin/awg-transit-preflight /usr/local/sbin/awg-transit-apply /usr/local/sbin/awg-transit-routing /usr/local/sbin/awg-mode-switch "$HEALTH_SCRIPT" /usr/local/sbin/awg-opencck-update /usr/local/sbin/awg-core-update "$UPDATE_SCRIPT" "$TRAFFIC_CLI"; do
  [[ -x "$f" ]] || die "Не установлен исполняемый компонент: $f"
  bash -n "$f" || die "Синтаксическая проверка компонента не пройдена: $f"
done
[[ -x "$MIHOMO_POOL_CLI" ]] || die "Не установлен исполняемый компонент: $MIHOMO_POOL_CLI"
python3 -m py_compile "$MIHOMO_POOL_CLI" || die "Синтаксическая проверка компонента не пройдена: $MIHOMO_POOL_CLI"
ok "Компоненты управления v$AWG_PI_VERSION установлены"

# -----------------------------------------------------------------------------
# 11. Start services and critical tests
# -----------------------------------------------------------------------------
STAGE="первый запуск и критические проверки"
log "[11/12] Первый запуск"
systemctl daemon-reload
systemctl enable awg-pbr-setup.service dnsmasq.service awg-pbr-health.service awg-selection-monitor.service awg-traffic.service awg-opencck-update.timer awg-mihomo-pool-refresh.timer >/dev/null

# Base control plane comes up before any VPN backend. This is what keeps SSH,
# TUI, DNS and recovery available even with zero working transports.
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

if (( UPGRADE_EXISTING == 0 )); then
  STAGE="выбор первого transport"
  log "[11a/12] First transport wizard"
  if "$FIRST_RUN_CLI" wizard; then
    ok "Первичная настройка transport завершена"
  else
    warn "Первичный transport не удалось настроить. Установка продолжится в recovery-state; повторите настройку через sudo awg-menu."
    printf '%s\n' unconfigured >"$TRANSPORT_FILE"
    chmod 600 "$TRANSPORT_FILE"
  fi
fi

ACTIVE_TRANSPORT="$(cat "$TRANSPORT_FILE" 2>/dev/null || echo unconfigured)"
case "$ACTIVE_TRANSPORT" in
  awg)
    if [[ -f "$CONF_FILE" ]]; then
      systemctl enable "awg-quick@$VPN_IF.service" >/dev/null
      if systemctl restart "awg-quick@$VPN_IF.service" && "$TRANSPORT_CLI" check awg >/dev/null 2>&1; then
        ok "AmneziaWG backend healthy"
      else
        warn "AWG backend сейчас unhealthy. Transport state сохранён для recovery; клиентская policy будет безопасной для выбранного режима."
      fi
    else
      warn "Transport state указывает AWG, но конфиг отсутствует; переводим state в unconfigured."
      printf '%s\n' unconfigured >"$TRANSPORT_FILE"
      chmod 600 "$TRANSPORT_FILE"
      ACTIVE_TRANSPORT=unconfigured
    fi
    ;;
  mihomo)
    if systemctl start awg-mihomo.service >/dev/null 2>&1 && "$TRANSPORT_CLI" check mihomo >/dev/null 2>&1; then
      ok "Mihomo backend healthy"
    else
      warn "Mihomo backend сейчас unhealthy. Transport state сохранён для recovery; другой backend можно настроить независимо."
    fi
    ;;
  unconfigured)
    warn "Active transport не настроен. Это допустимое recovery-состояние; SSH/TUI/DNS остаются доступны."
    ;;
  *)
    die "Некорректный transport state: $ACTIVE_TRANSPORT"
    ;;
esac

systemctl restart awg-pbr-health.service
systemctl is-active --quiet awg-pbr-health.service || die "health monitor не запустился"
systemctl restart awg-selection-monitor.service
systemctl is-active --quiet awg-selection-monitor.service || die "selection monitor не запустился"
systemctl restart awg-traffic.service
systemctl is-active --quiet awg-traffic.service || warn "traffic accounting не запустился; маршрутизация продолжит работу"
systemctl start awg-opencck-update.timer
systemctl is-active --quiet awg-opencck-update.timer || warn "OpenCCK timer не активен; ручное обновление останется доступно"
systemctl start awg-mihomo-pool-refresh.timer
systemctl is-active --quiet awg-mihomo-pool-refresh.timer || warn "Mihomo health-pool timer не активен; ручная проверка останется доступна"

ACTIVE_TRANSPORT="$(cat "$TRANSPORT_FILE" 2>/dev/null || echo unconfigured)"
if [[ "$ACTIVE_TRANSPORT" != unconfigured ]]; then
  if "$TRANSPORT_CLI" check "$ACTIVE_TRANSPORT" >/dev/null 2>&1; then
    ok "Active transport '$ACTIVE_TRANSPORT' прошёл итоговый backend health-check."
  else
    warn "Active transport '$ACTIVE_TRANSPORT' unhealthy. Control plane/recovery остаются доступны."
  fi
fi

if (( UPGRADE_EXISTING == 0 )); then
  STAGE="выбор Operating Mode"
  log "[11b/12] Operating Mode selection"
  printf "\nOperating Mode выбирается независимо от transport:\n"
  printf "1) Selective Gateway — transport DOWN/not-ready => FAIL-OPEN DIRECT\n"
  printf "2) MikroTik Transit / Backup VPN — transport DOWN/not-ready => FAIL-CLOSED/LOCKDOWN\n"
  ask "Режим работы" "1"
  case "$REPLY" in
    1)
      "$ROUTE_CLI" mode selective >/dev/null
      ok "Operating Mode: Selective Gateway"
      ;;
    2)
      if "$ROUTE_CLI" mode transit; then
        ok "Operating Mode: MikroTik Transit / Backup VPN"
      else
        warn "Transit activation failed; installer restores Selective Gateway."
        "$ROUTE_CLI" mode selective >/dev/null 2>&1 || true
      fi
      ;;
    *)
      warn "Неизвестный выбор Operating Mode; безопасно остаёмся в Selective Gateway."
      "$ROUTE_CLI" mode selective >/dev/null 2>&1 || true
      ;;
  esac
elif (( ACTIVATE_TRANSIT_AFTER_INSTALL == 1 )); then
  STAGE="активация MikroTik Transit"
  log "[11b/12] Legacy upgrade Transit request"
  if "$ROUTE_CLI" mode transit; then
    ok "MikroTik Transit / Backup VPN активирован"
  else
    warn "Transit activation не прошла. Runtime восстановлен; upgrade продолжится в Selective Gateway."
    "$ROUTE_CLI" mode selective >/dev/null 2>&1 || true
  fi
fi

# -----------------------------------------------------------------------------
# 12. Deep diagnostics + summary
# -----------------------------------------------------------------------------
STAGE="финальная диагностика"
log "[12/12] Полная диагностика"

# Publish the new installed version before diagnostics so the final report
# reflects the version whose components are actually running. Transactional
# update rollback restores both private state and public version metadata if this stage fails.
printf '%s\n' "$AWG_PI_VERSION" >"$VERSION_FILE"
chmod 644 "$VERSION_FILE"
install -o root -g root -m 644 "$VERSION_FILE" "$PUBLIC_VERSION_FILE"
ok "Версия AWG Pi Gateway зафиксирована: $AWG_PI_VERSION"

"$ROUTE_CLI" reload
"$ROUTE_CLI" diagnostics

LATEST_DIAG="$(find "$LOG_DIR" -maxdepth 1 -type f -name 'diagnostics-*.txt' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"

printf "\n%b=== УСТАНОВКА ЗАВЕРШЕНА ===%b\n" "$G$B" "$R"
printf "Raspberry Pi:    %s\n" "$PI_IP"
printf "MAC (%s):       %s\n" "$LAN_IF" "$LAN_MAC"
printf "LAN router:      %s\n" "$ROUTER_IP"
printf "LAN:             %s\n" "$LAN_CIDR"
printf "AWG interface:   %s\n" "$VPN_IF"
printf "AWG tags:        go=%s tools=%s\n" "$GO_TAG" "$TOOLS_TAG"
printf "Install report:  %s\n" "$INSTALL_REPORT"
printf "Diagnostics:     %s\n" "${LATEST_DIAG:-см. $LOG_DIR}"

FINAL_MODE="$(cat "$MODE_FILE" 2>/dev/null || echo selective)"
FINAL_TRANSPORT="$(cat "$TRANSPORT_FILE" 2>/dev/null || echo unconfigured)"
case "$FINAL_TRANSPORT" in
  awg) FINAL_TRANSPORT_LABEL="AmneziaWG" ;;
  mihomo) FINAL_TRANSPORT_LABEL="Mihomo" ;;
  unconfigured) FINAL_TRANSPORT_LABEL="Not configured / recovery" ;;
  *) FINAL_TRANSPORT_LABEL="INVALID" ;;
esac
printf "Active transport: %s (%s)\n" "$FINAL_TRANSPORT_LABEL" "$FINAL_TRANSPORT"
printf "\nЛогика:\n"
if [[ "$FINAL_MODE" == transit ]]; then
  printf "  Operating mode = MikroTik Transit / Backup VPN\n"
  printf "  MikroTik классифицирует и отправляет backup-трафик на Pi\n"
  printf "  Active transport = %s\n" "$FINAL_TRANSPORT_LABEL"
  printf "  Pi forward/NAT = только через active transport; transport down/not-ready = FAIL-CLOSED\n"
  printf "  management/control plane + transport endpoints = DIRECT через LAN router\n"
  printf "  OpenCCK/VPN/DIRECT/client state сохранён, но не классифицирует Transit\n"
else
  printf "  Operating mode = Selective Gateway\n"
  printf "  обычный трафик = DIRECT через LAN router\n"
  printf "  VPN-list = через выбранный active transport\n"
  printf "  transport down/not-ready = автоматический FAIL-OPEN DIRECT\n"
  printf "  DNS клиентов PBR = %s (dnsmasq -> независимые upstream DNS)\n" "$PI_IP"
fi
printf "  DHCP остаётся на LAN router\n"

printf "\nОсновные команды:\n"
printf "  sudo awg-route status\n"
printf "  sudo awg-transport status\n"
printf "  sudo awg-route mode status\n"
printf "  sudo awg-route mode selective\n"
printf "  sudo awg-route mode transit\n"
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
printf "  sudo awg-route dns status\n"
printf "  sudo awg-route dns set 9.9.9.9,149.112.112.112\n"
printf "  sudo awg-route vpn import FILE\n"
printf "  sudo awg-route source add opencck youtube\n"
printf "  sudo awg-route source list\n"
printf "  sudo awg-menu\n"
printf "  sudo awg-update status\n"
printf "  sudo awg-update gateway\n"
printf "  sudo awg-update core\n"

printf "\nПервичная проверка режима:\n"
if [[ "$FINAL_MODE" == transit ]]; then
  printf "  Клиентам НЕ назначать Pi как gateway/DNS для Transit.\n"
  printf "  Сначала настройте один тестовый client/prefix на MikroTik по Transit guide.\n"
  printf "  Проверка Pi: sudo awg-route mode status && sudo awg-route status\n"
  printf "  IPv6: не использовать в Transit v1.3.0.\n"
else
  printf "  IPv4:    свободный фиксированный адрес в %s\n" "$LAN_CIDR"
  printf "  Gateway: %s\n" "$PI_IP"
  printf "  DNS:     %s\n" "$PI_IP"
  printf "  IPv6:    не использовать\n"
  if [[ "$FINAL_TRANSPORT" == unconfigured ]]; then
    printf "  Сначала настройте AWG или Mihomo через sudo awg-menu; DIRECT/control plane уже доступны.\n"
  else
    printf "  Сначала проверьте DIRECT, затем добавьте один тестовый домен в VPN-list.\n"
  fi
fi

printf "\n%bВАЖНО:%b IP оборудования выбирайте вне конфликтов с DHCP либо закрепите его на LAN router.\n" "$Y" "$R"
