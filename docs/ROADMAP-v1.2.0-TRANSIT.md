# v1.2.0 design note: MikroTik Transit / Backup VPN mode

This document records the v1.2.0 Transit design and implementation contract.
v1.1.0 remains the frozen Selective-only release line.

## Goal

Keep the existing selective-gateway behavior and add a second independent
operating mode in which MikroTik performs traffic classification and failover,
while the Raspberry Pi acts only as an AmneziaWG transit gateway.

The intended backup path is:

```text
normal:
client -> MikroTik -> SSTP -> VPN server

SSTP unavailable:
client -> MikroTik -> Raspberry Pi -> awg0 -> AmneziaWG server
```

MikroTik remains the normal client default gateway. Client devices do not need
to switch their gateway/DNS to the Pi for Transit mode.

## Important routing fact

RouterOS packet/connection/routing marks are local MikroTik metadata and are not
carried to the Raspberry Pi inside an ordinary IP packet.

Therefore the Pi will not attempt to read a MikroTik mark. MikroTik will use
its existing classification/policy rules and, when the backup route is selected,
forward the chosen traffic to the Pi as the next hop.

## Operating modes

v1.2.0 should preserve two independent, persistent operating modes.

### 1. Selective Gateway

This is the existing v1.1.0 behavior:

- selected clients use the Pi as gateway/DNS;
- the Pi performs DNS/OpenCCK/manual-domain/IP classification;
- the Pi applies its own nftables/PBR marking;
- selected traffic is routed through `awg0`;
- current OpenCCK sources, VPN/DIRECT lists and client allow-list remain usable.

### 2. MikroTik Transit / Backup VPN

In this mode:

- MikroTik performs all traffic classification;
- MikroTik decides when SSTP is primary and when the Pi is the backup next hop;
- the Pi does not use OpenCCK/domain/DNS/client rules to decide whether forwarded
  traffic should use AWG;
- eligible transit traffic intentionally sent by MikroTik to the Pi is forwarded
  through `awg0`;
- the Pi's own management traffic and the AWG endpoint transport must continue
  DIRECT through MikroTik to avoid routing recursion;
- OpenCCK sources, VPN/DIRECT lists and client settings are preserved on disk but
  inactive for Transit classification;
- returning to Selective Gateway restores the existing selective behavior without
  requiring those settings to be recreated.

The Pi does not modify MikroTik configuration automatically.

## Mode selection

The mode should be selectable manually from the SSH TUI:

```text
System
  -> Operating mode
       -> Selective Gateway
       -> MikroTik Transit / Backup VPN
```

The screen should clearly show the current mode and what will change.

A matching CLI is planned conceptually:

```text
awg-route mode status
awg-route mode selective
awg-route mode transit
```

Exact command/UI wording may be adjusted during implementation.

## Persistence and upgrade behavior

The last explicitly selected operating mode should persist across reboot.

Agreed default for an upgrade from v1.1.0 to v1.2.0:

- after a successful v1.1.0 -> v1.2.0 upgrade, the initial operating mode is
  **MikroTik Transit / Backup VPN**;
- all existing Selective Gateway state (OpenCCK, VPN/DIRECT lists, client
  allow-list and DNS/LAN settings) is preserved but inactive for Transit
  classification;
- the user can switch back to **Selective Gateway** at any time from
  `System -> Operating mode`;
- once the user changes the mode manually, that selected mode persists across
  reboot until changed again.

The upgrade must make this mode change explicit in its summary/confirmation.
Before activating Transit it should run the normal mode-switch preflight. If
Transit cannot be applied safely, the upgrade must not leave a partial Transit
configuration; it should retain/restore the previous Selective Gateway runtime
state and report the failure.

Transit is the default target mode for both fresh v1.2.0 installs and the
v1.1.0 -> v1.2.0 upgrade path. A fresh install stages **Selective Gateway**
during installation so AWG can be brought up and validated safely, then performs
the normal transactional Transit preflight/switch before installation completes.
If that activation fails, the installation remains in Selective Gateway rather
than leaving a partial Transit datapath.

## Transactional switching

Changing modes must be transactional and require explicit confirmation.

Before applying a switch, the Pi should verify at least:

- `awg0` profile is valid;
- AWG endpoint remains reachable through the normal LAN/default route;
- LAN forwarding prerequisites are present;
- the requested mode can be applied without deleting the inactive mode's state.

If the switch fails, the previous operating mode and its routing/firewall state
must be restored.

Mode switching must never erase:

- AWG native profile;
- OpenCCK metadata/cache;
- VPN/DIRECT lists;
- client allow-list;
- LAN/DNS settings.

## MikroTik responsibilities

MikroTik remains the failover decision point.

Conceptually its VPN policy table will have:

```text
primary: selected traffic -> SSTP
backup:  selected traffic -> Raspberry Pi LAN address
```

When SSTP is considered unavailable, MikroTik selects the Pi as the backup next
hop. When SSTP is healthy again, MikroTik returns to SSTP.

The exact RouterOS health/failover mechanism will be designed and tested during
v1.2.0 work. It should detect useful VPN-path health, not merely assume that an
interface-up state proves end-to-end connectivity.

## Raspberry Pi responsibilities in Transit mode

The Pi should be deliberately simple:

- accept only intended LAN transit traffic according to the final security
  policy;
- forward that transit traffic through `awg0`;
- NAT it as required by the existing AWG topology;
- keep the AWG endpoint route outside the tunnel;
- expose status/diagnostics that clearly identify Transit mode and tunnel health;
- preserve SSH/DNS/management reachability as designed.

The existing v1.1.0 domain-marking pipeline must not accidentally mark or
reclassify Transit traffic.

## Failure behavior

The Transit failure policy is **FAIL-CLOSED**.

If MikroTik has already selected the Raspberry Pi as the backup next hop and AWG
is unavailable, the Pi must not leak that selected traffic back to the normal LAN
default route. The Transit firewall therefore accepts trusted MikroTik ingress
only when the actual egress is `awg0`. The health monitor removes the Transit
policy rule when AWG is unhealthy; the remaining forward guard then drops the
traffic instead of forwarding it DIRECT.

The Pi's own management traffic and the AWG endpoint remain DIRECT through the
normal MikroTik/main route. Selective Gateway keeps its existing v1.1.x
FAIL-OPEN behavior.

## Project sequencing

1. Finish all remaining v1.1.0 hardware tests.
2. Freeze/release the validated v1.1.0 line without mixing in Transit changes.
3. Start v1.2.0 work on a separate feature/development branch.
4. Implement mode storage, transactional switching, Transit forwarding and
   diagnostics.
5. Build and test the corresponding MikroTik SSTP -> Pi failover configuration.
6. Verify Selective -> Transit -> Selective switching preserves all state.

The current v1.1.0 tested executable snapshot remains separate from this future
design.

## v1.2.0 implementation invariants

The implementation must preserve these invariants:

- `/etc/awg-pbr/mode` contains only `selective` or `transit`;
- a missing mode file is interpreted as `selective` for v1.1.x compatibility;
- mode switching is transactional and restores the previous runtime mode on
  failure;
- Transit activation requires a healthy AWG transport and a DIRECT route to the
  runtime AWG endpoint;
- Transit ingress is restricted to frames arriving from the MikroTik router MAC
  and source addresses inside the configured LAN;
- Transit does not redirect client DNS and does not use OpenCCK/domain/client
  classification;
- Selective state remains stored and is restored when switching back;
- boot/reload setup is mode-aware;
- the health monitor is FAIL-OPEN in Selective and FAIL-CLOSED in Transit.

### Boot/setup lockdown

Transit boot/reload first installs a minimal **LOCKDOWN** nftables state with a
drop-policy forward chain and no Transit mark/NAT rule. Only after the normal
router is reachable and its Ethernet MAC has been resolved is the full
MAC-restricted Transit ruleset installed. If router-dependent setup fails, the
lockdown remains active, preventing a LAN/main-route forwarding loop while Pi
management input stays reachable.

### Inactive Selective data in Transit

OpenCCK may continue refreshing its persistent cached lists while Transit is
active, but those cache updates do not reload the live Transit datapath. The
latest cache is applied when Selective mode is restored.
