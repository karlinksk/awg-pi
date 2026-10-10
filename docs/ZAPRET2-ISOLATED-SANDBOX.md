# AWG Pi Gateway: research sandbox before any zapret2 experiments

**Status: research only.** This phase does NOT download, install, configure,
or run zapret2. No changes to working SSTP, AWG, Mihomo, nftables,
policy-routing, NetworkManager or MikroTik configuration.

## Design

Use Linux network namespace awg-dpi-test with a temporary macvlan interface
awdpi0, attached to Pi eth0. This provides separate L3 routing and nftables.
It requires no veth, host NAT, host nftables or host route changes.

An optional short-lived BusyBox udhcpc request uses a randomly generated
locally administered MAC to get a *separate* DHCP lease from MikroTik at
192.168.112.1. The known LAN is 192.168.112.0/24. The utility rejects
the real Pi address 192.168.112.34, out-of-range leases and foreign DHCP
server addresses. It sets the acquired address and default route **inside
the namespace only**.

The DHCP utility uses a no-op event hook and parses its successful lease
message, which is checked against independently verified LAN configuration.
Custom BusyBox DHCP hooks did not run on this Pi although the lease itself
was obtained; no working host DHCP settings were changed.

For the HTTPS smoke test the utility resolves the host on the parent Pi
and pins the IPv4 destination with curl --resolve in the namespace.
It never edits host /etc/resolv.conf. Host and namespace public IPv4
addresses are compared to ensure the test is not routed through a
foreign proxy. A dynamic DHCP lease may remain on MikroTik for its normal
lifetime after the test; this is not a persistent configuration change.

## Confirmed checks (Raspberry Pi 4 / Debian 13 ARM64, 2026-10-11)

1. Macvlan supported; busybox udhcpc installed; no naming conflict.
2. Lifecycle test: create and delete temporary namespace/interface.
   Main-table route, ip rule and nft table listing checksums unchanged.
3. Injected Python exception: the finally block removed everything;
   expected script exit code 2.
4. DHCP smoke: test MAC received its own LAN lease from MikroTik, isolated
   HTTPS succeeded with **the same WAN public IP as Pi DIRECT**; cleanup passed.
5. A fresh test namespace had **no nftables tables and no IPv4 routes**
   until the isolated address was configured.
6. SIGTERM test: external timeout sent a signal; the finally block
   removed the namespace and interface.
7. Live transport Mihomo healthy, Transit guard SAFE, Transit policy
   ACTIVE and VPN table READY after testing.

No zapret2 code or processes were involved. No VLESS proxy was tested in
this sandbox phase.

## Commands (after reviewing source)

~~~bash
sudo python3 research/awg-dpi-netns-sandbox.py status
sudo python3 research/awg-dpi-netns-sandbox.py lifecycle
sudo python3 research/awg-dpi-netns-sandbox.py rollback
sudo python3 research/awg-dpi-netns-sandbox.py dhcp-smoke
sudo timeout --signal TERM --kill-after=2s 2s \
  python3 research/awg-dpi-netns-sandbox.py hold
sudo python3 research/awg-dpi-netns-sandbox.py status
~~~

The rollback subcommand exits 2 intentionally. The tested copy is at
/home/karlinks/awg-dpi-netns-sandbox.py (mode 700). Root privileges
are required only for the isolated namespace and interface.

## Cleanup and hard-failure limitations

Normal completion, injected exceptions and SIGTERM invoke automatic
cleanup. However, SIGKILL, kernel panic and power loss cannot be trapped
by a Python process. The owner marker is kept in
/run/awg-dpi-test-owner/owner for possible recovery:

~~~bash
sudo python3 /home/karlinks/awg-dpi-netns-sandbox.py status
sudo python3 /home/karlinks/awg-dpi-netns-sandbox.py cleanup
~~~

The cleanup action refuses to delete objects without the correct ownership
marker, or while processes still own the namespace. During reboot the
namespace and /run marker disappear automatically. **Do not promise
automatic rollback after SIGKILL** without an independent watchdog.
Future zapret2 tests should add a supervisor/timeout and postflight audit.

## Next stage, not implemented

A future experiment would run a single isolated VLESS+REALITY+Vision
profile for 159.89.87.21:28190 in this namespace using the independent
direct IPv4 path. First reproduce baseline failure WITHOUT zapret2. Then
apply a very limited set of test nft/NFQUEUE rules and a zapret2 process
**inside this namespace only**. Do not change host awg_pbr, MSTP/SSTP,
MikroTik or production transport services.

The source stays in a research branch and must not be included in a
stable release without review.
