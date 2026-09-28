#!/usr/bin/env bash
set -Eeuo pipefail

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

LAN_IF=eth0
LAN_CIDR=192.168.0.0/24
VPN_IF=awg0
VPN_MARK=0x100
HEALTH_MARK=0x101
VPN_TABLE=100

cat >"$tmp" <<NFT
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

  chain input_guard {
    type filter hook input priority filter; policy drop;
    iifname "lo" accept
    ct state established,related accept
    iifname "$LAN_IF" tcp dport 22 accept
    iifname "$LAN_IF" udp dport 53 accept
    iifname "$LAN_IF" tcp dport 53 accept
    iifname "$LAN_IF" ip protocol icmp accept
    iifname "$LAN_IF" meta l4proto ipv6-icmp accept
    iifname "$LAN_IF" udp sport 67 udp dport 68 accept
  }

  chain forward_guard {
    type filter hook forward priority filter; policy drop;
    ct state established,related accept
    iifname "$LAN_IF" ip saddr $LAN_CIDR oifname "$LAN_IF" accept
    iifname "$LAN_IF" ip saddr $LAN_CIDR oifname "$VPN_IF" accept
  }

  chain prerouting_mark {
    type filter hook prerouting priority mangle; policy accept;
    iifname "$LAN_IF" ip daddr @source4 meta mark set $VPN_MARK
    iifname "$LAN_IF" ip daddr @vpn4 meta mark set $VPN_MARK
    iifname "$LAN_IF" ip daddr @direct4 meta mark set 0x0
  }

  chain dns_redirect {
    type nat hook prerouting priority dstnat; policy accept;
    iifname "$LAN_IF" udp dport 53 redirect to :53
    iifname "$LAN_IF" tcp dport 53 redirect to :53
  }

  chain postrouting_nat {
    type nat hook postrouting priority srcnat; policy accept;
    ip saddr $LAN_CIDR oifname "$VPN_IF" masquerade
    ip saddr $LAN_CIDR oifname "$LAN_IF" masquerade
  }
}
NFT

sudo nft -c -f "$tmp"
echo "nftables template: OK"
