# MikroTik Transit / Backup VPN for AWG Pi Gateway v1.2.0

This document is a RouterOS v7 implementation template. Replace the placeholders
with the actual interface names, Pi address and existing policy selectors before
applying it.

The Pi does not read RouterOS marks. MikroTik classifies traffic and changes the
next hop; the packet reaches the Pi as an ordinary routed Ethernet frame.

## Variables used in the examples

```text
<PI_IP>            Raspberry Pi LAN IPv4
<SSTP_IF>          existing SSTP client interface
<LAN_IF>           LAN bridge/interface
<TEST_CLIENT>      one test client IPv4
vpn_backup         dedicated routing table
```

Start with one test client. Do not move the full production policy until the
failover test passes.

## Routing table

Create a FIB table if it does not already exist:

```routeros
/routing/table/add name=vpn_backup fib
```

The policy table needs a primary SSTP default and a secondary Pi next hop.
Use comments so health scripts can address the routes without depending on
internal numeric IDs:

```routeros
/ip/route/add dst-address=0.0.0.0/0 gateway=<SSTP_IF> routing-table=vpn_backup distance=1 comment="AWG-Pi primary SSTP"
/ip/route/add dst-address=0.0.0.0/0 gateway=<PI_IP> routing-table=vpn_backup distance=2 comment="AWG-Pi backup Pi"
```

The Pi address itself must remain reachable through the normal LAN/main table.

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

## SSTP health

Do not use only `running=yes` as the definition of a healthy primary VPN. Test
an Internet probe through the SSTP interface.

A conservative RouterOS scheduler script can keep a short failure counter and
enable/disable only the route carrying comment `AWG-Pi primary SSTP`. The
exact script depends on the existing SSTP/interface/firewall configuration, so
validate the following manually first:

```routeros
/ping 1.1.1.1 interface=<SSTP_IF> count=3
```

When that probe reliably represents SSTP Internet health, automate it with a
threshold (for example several consecutive failures before disabling primary,
and several successes before re-enabling it). The backup Pi route should then
become active naturally by distance.

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

When SSTP health returns, re-enable the primary route. New selected flows should
again use SSTP.

After validation, migrate the existing production classifier to
`routing-table=vpn_backup` in small steps. Keep a rollback/export of the current
RouterOS configuration before modifying the production policy.
