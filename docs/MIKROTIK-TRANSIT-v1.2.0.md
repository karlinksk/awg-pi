# MikroTik Transit / Backup VPN for AWG Pi Gateway v1.2.0

This document is a RouterOS v7 implementation template. Replace the placeholders
with the actual interface names, Pi address and existing policy selectors before
applying it.

The Pi does not read RouterOS marks. MikroTik classifies traffic and changes the
next hop; the packet reaches the Pi as an ordinary routed Ethernet frame.

## Variables used in the examples

```text
<PI_IP>            Raspberry Pi LAN IPv4
<ROUTER_LAN_IP>    MikroTik LAN IPv4 used as the Netwatch source
<SSTP_IF>          existing SSTP client interface
<LAN_IF>           LAN bridge/interface
<TEST_CLIENT>      one test client IPv4
vpn_backup         dedicated routing table
```

Start with one test client. Do not move the full production policy until the
failover test passes.

The current Pi Transit rules accept source addresses from its configured
`LAN_CIDR` and require the Ethernet source MAC to be the MikroTik. For the
first RC test, use a client from that subnet. Routed client subnets outside that
CIDR require an explicit source-range extension in a later revision (or a
carefully designed MikroTik source-NAT policy); do not silently broaden the Pi
firewall.

## Routing table

Create a FIB table if it does not already exist:

```routeros
/routing/table/add name=vpn_backup fib
```

The policy table needs a primary SSTP default and a secondary Pi next hop.
Use comments so the health logic can address the routes without depending on
internal numeric IDs:

```routeros
/ip/route/add dst-address=0.0.0.0/0 gateway=<SSTP_IF> routing-table=vpn_backup distance=1 comment="AWG-Pi primary SSTP"
/ip/route/add dst-address=0.0.0.0/0 gateway=<PI_IP>@main routing-table=vpn_backup distance=2 comment="AWG-Pi backup Pi"
```

The `@main` suffix is intentional: it resolves the directly reachable Pi next
hop through the normal LAN/main table instead of recursively trying to resolve
the Pi through `vpn_backup`. The Pi address itself must remain reachable
through the normal LAN/main table.

If an existing production table already has the equivalent primary/backup
routes, keep that table and its existing distances. The hardware validation used
an existing policy table with SSTP at a lower distance than the Pi backup.

## Initial single-client classifier

A simple first hardware test can use:

```routeros
/ip/firewall/mangle/add chain=prerouting in-interface=<LAN_IF> src-address=<TEST_CLIENT> dst-address-type=!local action=mark-routing new-routing-mark=vpn_backup passthrough=no comment="AWG-Pi v1.2 test client"
```

Exclude local/LAN destinations before the routing-mark rule if equivalent rules
do not already exist in the production firewall.

Do not mark traffic sourced by the Pi itself. Pi management and the AWG endpoint
must stay on the normal main route.

## FastTrack

RouterOS FastTrack can bypass policy-routing/mangle processing for established
flows. The selected VPN-policy connections must be excluded from FastTrack, or
FastTrack must be disabled for the initial validation.

Adapt the existing firewall rather than blindly adding a duplicate FastTrack
rule.

## SSTP health: two independent Internet probes

Do not use only `running=yes` as the definition of a healthy primary VPN. An
SSTP client can remain RUNNING while Internet forwarding behind the tunnel is
broken.

The v1.2 hardware validation used two independent ICMP probes. Both must fail
before the primary route is disabled, and both must recover before it is
re-enabled.

The important detail is that health probes must never fall through to the Pi
backup or the normal WAN. Otherwise Netwatch can report the SSTP path as healthy
while it is actually testing another path.

Create an address list for the probes:

```routeros
/ip/firewall/address-list/add list=AWG-SSTP-PROBES address=1.1.1.1 comment="AWG-SSTP-PROBE-1"
/ip/firewall/address-list/add list=AWG-SSTP-PROBES address=8.8.8.8 comment="AWG-SSTP-PROBE-2"
```

Pin each probe to SSTP in the policy table and add a high-distance blackhole for
the same /32. The blackhole becomes active when the SSTP-specific route is
unavailable, preventing the probe from escaping through the Pi backup:

```routeros
/ip/route/add dst-address=1.1.1.1/32 routing-table=vpn_backup gateway=<SSTP_IF> distance=1 scope=10 comment="AWG-SSTP-PROBE-1"
/ip/route/add dst-address=1.1.1.1/32 routing-table=vpn_backup distance=254 blackhole comment="AWG-SSTP-PROBE-1-BH"

/ip/route/add dst-address=8.8.8.8/32 routing-table=vpn_backup gateway=<SSTP_IF> distance=1 scope=10 comment="AWG-SSTP-PROBE-2"
/ip/route/add dst-address=8.8.8.8/32 routing-table=vpn_backup distance=254 blackhole comment="AWG-SSTP-PROBE-2-BH"
```

Mark only router-originated ICMP probes into the policy table:

```routeros
/ip/firewall/mangle/add chain=output action=mark-routing new-routing-mark=vpn_backup passthrough=no protocol=icmp dst-address-list=AWG-SSTP-PROBES comment="AWG-SSTP-PROBE-MARK"
```

Verify both probes before adding automation:

```routeros
/ping 1.1.1.1 src-address=<ROUTER_LAN_IP> count=3
/ping 8.8.8.8 src-address=<ROUTER_LAN_IP> count=3
/ip/firewall/mangle/print stats detail where comment="AWG-SSTP-PROBE-MARK"
```

The mangle counter must increase.

## Netwatch failover / failback

Use simple Netwatch probes so latency thresholds do not create false failures on
higher-latency SSTP links:

```routeros
/tool/netwatch/add host=1.1.1.1 type=simple src-address=<ROUTER_LAN_IP> interval=10s timeout=2s startup-delay=30s comment="AWG-SSTP-NW-1"
/tool/netwatch/add host=8.8.8.8 type=simple src-address=<ROUTER_LAN_IP> interval=10s timeout=2s startup-delay=30s comment="AWG-SSTP-NW-2"
```

Attach the same guarded scripts to both Netwatch entries. Replace the primary
route comment below if the existing RouterOS configuration uses another name:

```routeros
/tool/netwatch/set [find where comment="AWG-SSTP-NW-1"] \
down-script=":local r [/ip/route/find where comment=\"AWG-Pi primary SSTP\"]; :if (([/tool/netwatch/get [find where comment=\"AWG-SSTP-NW-1\"] status] = \"down\") && ([/tool/netwatch/get [find where comment=\"AWG-SSTP-NW-2\"] status] = \"down\") && ([/ip/route/get \$r disabled] = false)) do={/ip/route/disable \$r; :log warning \"AWG failover: SSTP health DOWN - Pi/AWG backup activated\"}" \
up-script=":local r [/ip/route/find where comment=\"AWG-Pi primary SSTP\"]; :if (([/tool/netwatch/get [find where comment=\"AWG-SSTP-NW-1\"] status] = \"up\") && ([/tool/netwatch/get [find where comment=\"AWG-SSTP-NW-2\"] status] = \"up\") && ([/ip/route/get \$r disabled] = true)) do={/ip/route/enable \$r; :log info \"AWG failback: SSTP health UP - primary restored\"}"

/tool/netwatch/set [find where comment="AWG-SSTP-NW-2"] \
down-script=":local r [/ip/route/find where comment=\"AWG-Pi primary SSTP\"]; :if (([/tool/netwatch/get [find where comment=\"AWG-SSTP-NW-1\"] status] = \"down\") && ([/tool/netwatch/get [find where comment=\"AWG-SSTP-NW-2\"] status] = \"down\") && ([/ip/route/get \$r disabled] = false)) do={/ip/route/disable \$r; :log warning \"AWG failover: SSTP health DOWN - Pi/AWG backup activated\"}" \
up-script=":local r [/ip/route/find where comment=\"AWG-Pi primary SSTP\"]; :if (([/tool/netwatch/get [find where comment=\"AWG-SSTP-NW-1\"] status] = \"up\") && ([/tool/netwatch/get [find where comment=\"AWG-SSTP-NW-2\"] status] = \"up\") && ([/ip/route/get \$r disabled] = true)) do={/ip/route/enable \$r; :log info \"AWG failback: SSTP health UP - primary restored\"}"
```

This gives the intended hysteresis:

- one probe DOWN and one UP: keep SSTP primary;
- both probes DOWN: disable only the SSTP default route, so the Pi backup becomes
  active by distance;
- one probe recovers: remain on the Pi backup;
- both probes UP: re-enable the SSTP default route and fail back.

The SSTP interface itself is not administratively disabled by this logic. This
matters for remote systems where the tunnel is also needed for management or
other traffic.

### Safe validation sequence

When validating remotely, use RouterOS Safe Mode and first test only the probe
routes:

1. Disable one probe /32 and confirm one Netwatch entry becomes DOWN while the
   SSTP default remains active.
2. Disable the second probe /32 and confirm both entries become DOWN, the SSTP
   default route is disabled automatically, and the Pi backup becomes active.
3. Keep the SSTP interface itself RUNNING.
4. Re-enable both probe /32 routes and confirm both Netwatch entries become UP,
   the SSTP default is re-enabled, and the Pi returns to standby.
5. Exit Safe Mode only after the recovered state is verified.

## Required failover sequence

```text
SSTP healthy:
selected client -> MikroTik -> SSTP

SSTP unhealthy, AWG healthy:
selected client -> MikroTik -> Pi -> awg0

SSTP unhealthy, AWG unhealthy:
selected client -> MikroTik -> Pi -> DROP (FAIL-CLOSED)
```

The third state is deliberate. The Pi does not send selected Transit traffic
back to MikroTik's normal Internet route.

## Recovery

When both SSTP health probes return UP, Netwatch re-enables the primary policy
route. New selected flows should again use SSTP.

After validation, migrate the existing production classifier to
`routing-table=vpn_backup` in small steps. Keep a rollback/export of the current
RouterOS configuration before modifying the production policy.
