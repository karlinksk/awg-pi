# Stage37 — shared AWG maintenance lock for recovery snapshots

**Status:** developed, locally tested, not installed on production Pi.

The Stage36 one-shot snapshot writer now acquires **both** its private writer lock and the same maintenance lock used by the existing Pi transport, route and selection processes.

- Real root-only mode uses fixed `/run/awg-maintenance.lock` with nonblocking `flock(LOCK_EX | LOCK_NB)`. There is no caller-controlled alternate lock path for production.
- Unprivileged fixture mode uses `<private-fixture>/.maintenance.lock` so lock conflicts, malicious symlinks and unsafe modes can be tested without touching production.
- The lock must be a regular file with the expected owner; it cannot be group/world writable or a symbolic link. A held lock returns an error **before** any snapshot or verification.
- The lock stays held while file snapshots, SHA-256 manifest, fsync and READY publication are performed, and is released by the kernel on normal exit or process death. The Stage36 writer lock additionally prevents concurrent attempts against the same recovery directory.
- The guard also covers read-only verification to avoid inspecting recovery metadata during a concurrent backup operation.

**Limits:** this is only an atomic snapshot window. It does *not* hold the shared lock across a later production configuration change, service restart and confirmation. The future privileged cutover coordinator must own that same lock for the **entire transaction** (and call the snapshot library without trying to take a second conflicting advisory lock). No root production invocation has been made.

### Validation

The snapshot focused suite now contains 18 successful tests. The three Stage37 tests cover a concurrent maintenance lock owner, malicious lock symlink and group/world-writable lock mode. The synthetic ext4 test on the Pi also passed after the lock change: snapshot and verification succeeded from separate processes, while test directories and credentials remained isolated.

The device boundary is unchanged: MikroTik and NAS are not accessed. Existing MikroTik policy directs marked traffic over SSTP when available, else to Pi, which applies Mihomo/AWG fallback and Transit FAIL-CLOSED.

### Remaining gates

- A root-owned, installed **early boot recovery** unit must safely block protected forwarding before any incomplete transaction is restored.
- Full live config/provider/transport restore must be atomic and verified, with a bounded deadline watchdog and rollback on failure.
- Real service, nftables, table100 and DIRECT route verification must precede re-enabling protected traffic.
- No production switch, restore or power-loss/reboot test until the above are available and independently reviewed.
