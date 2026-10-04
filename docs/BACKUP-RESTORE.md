# Full-media backup and bare-metal recovery

This document describes a **full storage-device image** backup for an AWG Pi Gateway host and the corresponding bare-metal restore procedure.

It is intentionally separate from the gateway's built-in transactional backups under
`/var/backups/awg-gateway/{network,config,dns}-*`. Those backups protect selected
AWG Pi Gateway configuration changes. A full-media image protects the complete host:
Debian, boot files, installed packages, systemd units, AWG Pi Gateway state, AmneziaWG
profile, SSH configuration, and any other files present on the storage device.

## Security warning

A raw image of the system disk is sensitive. It can contain AmneziaWG private and
preshared keys, SSH material, local credentials, logs, application state, and other
host-specific secrets.

Treat the image and its checksum file as private backup material. Do not commit them
to this repository or upload them to public file sharing.

## When to create an image

Create a full-media image before high-risk maintenance, major gateway upgrades, storage
migration, or other changes where a complete rollback point is useful.

For normal AWG Pi Gateway configuration changes, the application's transactional
backup/rollback mechanisms remain the first recovery option. A raw disk image is the
last-resort bare-metal recovery point.

## Preferred offline backup procedure

The safest image is created while the Raspberry Pi is shut down and the storage device
is not mounted by the Pi.

1. Record the current gateway state before shutdown:

   ```bash
   sudo awg-route mode status
   sudo awg-route status
   sudo systemctl --failed --no-pager
   sudo awg-route diagnostics
   ```

2. Shut the host down cleanly:

   ```bash
   sudo poweroff
   ```

3. Wait until disk activity has stopped, disconnect power, and remove the microSD/SSD.

4. Attach the storage device to another computer and create a **raw, whole-device
   image**. On Windows, a disk-imaging tool such as Win32 Disk Imager can read the
   entire card into an `.img` file. On Linux, an equivalent whole-device imaging
   workflow may be used.

5. Keep a descriptive filename, for example:

   ```text
   awg-gateway-golden-YYYY-MM-DD.img
   ```

6. Record the exact image size and calculate a SHA-256 checksum. On Windows
   PowerShell:

   ```powershell
   Get-Item .\awg-gateway-golden-YYYY-MM-DD.img | Select-Object Name,Length
   Get-FileHash .\awg-gateway-golden-YYYY-MM-DD.img -Algorithm SHA256
   ```

   On Linux:

   ```bash
   stat -c '%n %s bytes' awg-gateway-golden-YYYY-MM-DD.img
   sha256sum awg-gateway-golden-YYYY-MM-DD.img
   ```

7. Store the checksum beside the image and, ideally, keep another copy on separate
   storage.

## Verify a stored image

Before relying on an old recovery image, recalculate its SHA-256 and compare it with
the saved value. A checksum mismatch means the image must not be trusted for recovery.

The checksum proves that the file has not changed since the checksum was recorded; it
does not prove that the source filesystem was logically healthy when the image was
created. That is why the pre-shutdown gateway checks matter.

## Bare-metal restore

1. Use a target microSD/SSD whose capacity is at least as large as the source device
   represented by the image. Cards sold with the same nominal capacity can differ
   slightly in exact sector count, so equal-or-larger *actual* capacity is required.

2. Write the entire raw image to the target device with a disk-imaging tool.

3. Safely eject the restored storage device and install it in the Raspberry Pi.

4. Boot with the normal Ethernet connection available. Do not immediately change
   routing/firewall state until the restored baseline is verified.

5. Confirm the restored version and service state:

   ```bash
   sudo cat /etc/awg-pbr/version
   sudo awg-route mode status
   sudo awg-route status
   sudo systemctl --failed --no-pager
   sudo systemctl is-active \
     awg-pbr-setup.service \
     dnsmasq.service \
     awg-quick@awg0.service \
     awg-pbr-health.service \
     awg-opencck-update.timer
   ```

6. Verify the datapath and policy state:

   ```bash
   sudo ip -4 rule show
   sudo ip -4 route show table 100
   sudo nft list table inet awg_pbr
   sudo awg-route diagnostics
   ```

7. Run the mode-specific checks below before returning the gateway to normal use.

## Mode-specific recovery checks

### Selective Gateway

Confirm that:

- normal Internet traffic remains DIRECT;
- a known VPN-selected destination uses `awg0`;
- DIRECT exceptions still override VPN/OpenCCK classification;
- DNS/OpenCCK state is present;
- stopping the VPN path causes Selective to remain FAIL-OPEN as designed.

Use the current release validation guide for the full regression sequence.

### MikroTik Transit / Backup VPN

Confirm that:

- the Pi reports Transit mode;
- Transit guard is SAFE;
- healthy AWG reports active policy / ready VPN table;
- the AWG endpoint itself remains DIRECT through the LAN router;
- selected MikroTik backup traffic exits only through the VPN path;
- an unhealthy AWG path produces FAIL-CLOSED rather than WAN leakage.

Also verify the corresponding MikroTik primary/backup routing state before declaring
the restored system production-ready.

See:

- [TESTING-v1.2.0.md](TESTING-v1.2.0.md)
- [MIKROTIK-TRANSIT-v1.2.0.md](MIKROTIK-TRANSIT-v1.2.0.md)

## Restoring to a larger device

A raw image recreates the original partition layout. If the replacement device is
larger, the extra capacity may initially remain unused. Expanding the partition and
filesystem is an operating-system/storage administration task and is not performed by
AWG Pi Gateway automatically.

Do not resize the restored root filesystem until the gateway has booted successfully
and the recovery baseline has been verified.

## Host-specific post-restore notes

Keep host-specific recovery notes outside this public repository. They should record
at least:

- image filename, date, exact byte size, and SHA-256;
- where the image is stored;
- gateway release and important local services present at capture time;
- any changes made **after** the image was created that must be re-applied after a
  restore;
- any host-specific remote-access or time-synchronization requirements.

This separation keeps the public project documentation reproducible without publishing
machine-specific backup metadata or credentials.
