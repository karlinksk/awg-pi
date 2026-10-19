# Unified Mihomo/Xray subscription catalogue — experimental phase 1

## Agreed behavior

A provider URL is entered **once** through the existing
**Mihomo → Subscription / source** menu. The provider URL is a replaceable
input, not a permanent identifier. The contents may grow or shrink; nodes
may be removed, renamed, reordered, moved to different servers or rekeyed.

The current active subscription YAML is the **only** source for a shared
catalogue. Nodes are discovered afresh on every invocation, without any
fixed count or assumption about their list index. The transport mapping is:

- Mihomo: normal Hysteria2, Shadowsocks, Trojan, VMess, and other compatible
  protocols.
- Xray: VLESS/Reality **XHTTP** or **gRPC** recognised by the strict
  Xray VLESS adapter (if installed). Other unsupported profiles are never
  labelled working.
- Only one active gateway node will eventually serve TUN/LAN traffic; the
  extra Xray core is not a second TUN.

To list the actual current provider, once imported and committed:

    sudo awg-mihomo-unified-nodes list

To run a network-only HTTPS check through an isolated Xray process (no live
routing change), first see current indices and then run:

    sudo awg-mihomo-unified-nodes probe 1

For large subscriptions, an explicitly requested bounded batch is also
available:

    sudo awg-mihomo-unified-nodes probe-vless-all

Each invocation checks **at most 10 previously untested/stale Xray VLESS
profiles**; subsequent invocations process remaining profiles. There is no
hardcoded maximum subscription node count. There are no automatically
running probes introduced by this first phase. This is not Hot Pool READY.

## Subscription changes and existing FIXED safeguards

The catalogue compares exact transport fingerprints, excluding display name
and transient ordinal position. Unmodified, recently tested VLESS profiles
can keep their BASIC_NETWORK result after a link/name/order/count change.
If the endpoint, UUID or Reality settings change, they become UNTESTED;
deleted profiles and expired results are discarded. A new item starts as
UNTESTED. Duplicate display names cannot be silently selected.

Existing Mihomo network pool results are trusted only if their recorded
provider SHA256 still matches the **current** live provider and the scan is
fresh. Staged subscriptions are never misrepresented as live results.

Changing URL through the subscription menu downloads/stages the candidate
for review. With FIXED, the current gateway intentionally **does not**
promote a changed feed unattended; until the operator confirms the candidate,
the unified catalogue continues to reflect the safe active subscription.
If a named FIXED node disappears or is redefined in a new provider, no
random different VLESS node is chosen. The follow-on transactional
engine-aware MANUAL/AUTO/FIXED selector must reconcile or skip entries
without weakening Selective FAIL-OPEN / Transit FAIL-CLOSED or AWG fallback.

## Strict status definitions

- NETWORK_OK — a recent basic network check through the correct engine.
  For Xray this is real HTTPS to OpenAI API (HTTP 401 without credentials).
- NETWORK_FAIL — basic network check failed.
- UNKNOWN_HTTP / UNKNOWN_ERROR / UNAVAILABLE — indeterminate, not healthy.
- UNTESTED — no current proof.
- UNSUPPORTED or UNUSABLE_DUPLICATE_OR_MISSING_NAME — cannot be admitted.

None of these states is Hot Pool READY, service eligibility, authenticated
ChatGPT, YouTube24, true Mihomo TUN, forwarded LAN, or automatic failover
PASS. Hot Pool can remain disabled. No obsolete HTTP YouTube probe is used.

## Implementation / lifecycle

The versioned installer and existing-install upgrade install
\`src/awg-mihomo-unified-nodes.py\`. The existing menu provides a shared
catalogue and an opt-in single-node Xray probe; backup/rollback includes
the helper and the existing root-only Xray adapter state. On a blank fresh
install there is no profile and no automatic Xray scanner activity. Once
a provider is configured, listing/verification works without reinstalling.

This stage is a **separate experimental PR built on PR #135**, not merged,
not a stable release and not a replacement for v1.3.0 release gates. The
next stage adds the guarded live TUN switch/rollback for MANUAL, AUTO and
FIXED across engine changes. Only after real TUN, LAN, failover and reboot
tests may it be enabled in the main node-policy path.


## 2026-10-19: isolated real TUN three-leg validation

An independent root-owned test with no live service restart used an extra
\`awgxtun0\` Mihomo TUN interface, separate controller and ports, temporary
Xray on loopback, and private RAM-only credentials from the current HoneyVPN
provider:

| Selection via isolated Mihomo controller | Local proxy HTTPS | Real test TUN HTTPS |
| --- | --- | --- |
| Native Mihomo / Hysteria2 | OpenAI 401 | OpenAI 401; interface bytes increased |
| Xray / VLESS Reality XHTTP | OpenAI 401 | OpenAI 401; interface bytes increased |
| Native Mihomo / Hysteria2 restored | OpenAI 401 | OpenAI 401; interface bytes increased |

The system's real \`awg-mihomo.service\`, FIXED policy, current Transit
forwarding guards, tables 100/101, SSH/SSTP/MikroTik were untouched.
\`awgxtun0\` was deleted on exit. This proves an independent **test TUN**,
not a forwarded LAN-client test, nor production Mihomo engine-aware
MANUAL/AUTO/FIXED selection.

The versioned manual-only test is available after install/update as
\`awg-mihomo-xray-isolated-tun-canary\`. It requires both an explicit
\`--confirm-isolated\` argument and \`AWG_ISOLATED_EXPECT_HOST\` exactly
matching the chosen test Pi. It cannot be triggered by timers or the
automatic gateway selector. Run only on an authorized test Pi, not the
production microSD. No browser/obsolete HTTP YouTube tests are used; actual
YouTube24 and LAN remain separate release gates.
