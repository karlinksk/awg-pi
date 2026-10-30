# Engine maintenance (v1.3.1 candidate)

The Gateway release owns the supported versions. `awg-update status` compares
installed versions for AWG, Mihomo and Xray. A version match is **not** a hash
attestation of an already installed executable. It does not mean the newest
upstream release has been qualified.

`awg-update [--yes] core|mihomo|xray` installs only the release-pinned engine.
AWG pins the same Git revisions as `install.sh` and the real source-build CI;
Mihomo/Xray verify the literal release archive SHA256 before extraction and
check the executable version. Environment variables cannot override the
Mihomo version or expected SHA256. A mirror URL still needs the pinned SHA.
No new upstream version is added by this maintenance change.

`awg-xray-install reinstall` explicitly reinstalls that same pinned build,
even when the version matches. It uses the complete normal fetch/SHA256/backup/
publish/postcheck path and retains every running/selected-engine refusal.
It does not accept arbitrary versions or disable safety checks. Ordinary
`ensure` and `awg-update all` remain no-ops on matching versions.

`awg-core-update --yes reinstall` explicitly rebuilds and reinstalls the
release-pinned AWG sources. It retains the running/selected-engine refusals,
maintenance lock, backups and postchecks; transport switching and standby
shutdown are separate guarded maintenance actions. Normal `--yes` remains a
no-op on matching versions. No Go toolchain replacement is performed.

## No interruption of the incumbent

- Matching versions are a no-op, including on a running engine.
- Replacement holds `/run/awg-maintenance.lock`, shared with transport/node
  selection. Running, starting, stopping or unknown service state is refused.
- Selected AWG or Mihomo cannot be replaced even if its service is down.
  Xray replacement is also refused whenever the Mihomo transport is selected,
  because Xray shares that TUN. No automatic transport/node switch is made.
- TRANSIT requires a readable, recognized SAFE or LOCKDOWN guard before
  replacement. The updater never invokes FAIL-OPEN, stops a service, removes
  a policy rule, or writes mode, vpn-enabled, DNS, provider or node state.
  This applies to recovery too. SELECTIVE routing is also left unchanged.
- Consequently a running standby must be taken out of service separately
  under an explicitly reviewed maintenance procedure. The updater refuses
  that operation rather than doing it implicitly. Do not stop your incumbent
  to work around a refusal. A background service start performed outside the
  shared lock or a concurrent unrelated root operation is outside this contract.

`awg-update --yes all` checks Gateway availability and attempts **all three
engines once**, continuing after a refusal/failure and printing a result for
each. Any incomplete operation returns nonzero. Gateway installation remains
the separate `gateway` action/menu item, because its installer can restart
services. The old “all” path could run AWG twice after failure; that is removed.
Individual helpers use exit 3 for an in-use engine or busy maintenance lock;
`all` labels those operations DEFERRED separately from failures and shows a
Russian result summary. A failed guard/state check is an error, not a deferral.

## Backup and recovery

Candidates are downloaded/built and checked before touching installed files.
Each replacement creates a private `engine-<name>.<random>` directory under
`/var/backups/awg-gateway`, with original bytes, SHA256SUMS, target paths and
absence markers. Staging and rename happen on the destination filesystem.
Post-install version validation must pass before commit. AWG changes only its
three executables, preserving the existing service unit and source checkout.
It requires an installed Go toolchain; it never deletes/reinstalls Go.

An error or TERM/INT restores original executable bytes/absence while holding
the maintenance lock. Restoration does not restart any service. A failed
restore retains PENDING and reports the backup path; do not activate that
engine until an operator has verified/recovered it. SIGKILL/power loss cannot
run shell traps: PENDING plus the retained originals supports manual recovery,
but automatic crash recovery is **not claimed**. Multi-file AWG publication
is atomic per file, not across all three files. No backup is auto-pruned here.

Before manual recovery, establish the same inactive/nonselected engine and
Transit safety conditions, hold the maintenance lock, verify SHA256SUMS, and
restore only the listed engine files (or prior absence). Do not apply a whole
Gateway snapshot or change private configuration to repair an engine binary.

## Engines versus subscriptions

Mihomo subscription refresh (`awg-mihomo-update` and its timer) and the Xray
subscription inventory scan are separate existing operations. Engine repair
does not fetch providers, change active nodes or alter timer preferences.
The Updates menu explains this boundary and offers Xray explicitly.

## Acceptance boundaries

This is a source candidate based on draft PR #170; not a released v1.3.1.
Disposable tests cover service/selection refusal, shared lock, pinned hashes,
TRANSIT guard admission, atomic publication, postcheck failure and signal
recovery, and all-engine failure reporting. Installer delivery uses the
existing `src/awg-common`, engine helpers, updater and menu installation paths
for both fresh installs and upgrades; no Pi-only helper is required.

Real binary replacement/rollback, clean install/upgrade of this candidate and
LAN no-leak observations are separate hardware gates. Do not infer them from
mocked tests, version output, existing v1.3.0 acceptance or an earlier UI CI.
