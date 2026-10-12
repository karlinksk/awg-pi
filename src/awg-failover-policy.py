#!/usr/bin/env python3
"""Pure decision model for Service-Aware Failover (NO runtime writes or switches).

The production selector remains the sole owner of route changes. This module
is exercised only by offline tests until the existing transport transactions,
service evidence, node allow-list and post-switch checks are integrated.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Status = Literal["PASS", "FAIL", "UNKNOWN"]
ActionName = Literal["KEEP", "SELECT_NODE", "SELECT_TRANSPORT", "RECOVERY_WAIT"]


@dataclass(frozen=True)
class Policy:
    priority: tuple[str, ...] = ("mihomo", "awg")
    auto_failback: bool = True
    required_failures: int = 2
    failback_passes: int = 2
    failback_dwell_seconds: int = 120

    def __post_init__(self):
        if len(set(self.priority)) != 2 or set(self.priority) != {"mihomo", "awg"}:
            raise ValueError("invalid transport order")
        if self.required_failures < 1 or self.failback_passes < 2:
            raise ValueError("invalid stability thresholds")
        if self.failback_dwell_seconds < 0:
            raise ValueError("invalid dwell time")


@dataclass(frozen=True)
class Observation:
    now: int  # monotonic whole seconds
    active_transport: str
    active_node: str
    selection_mode: str  # manual, fixed, auto
    node_policy: str  # manual, fixed, auto
    mihomo_status: Status
    awg_status: Status
    mihomo_sample: str
    awg_sample: str
    warm_nodes: tuple[str, ...] = ()
    allowed_nodes: tuple[str, ...] = ()  # exact names required in fixed node policy

    def __post_init__(self):
        if self.active_transport not in ("mihomo", "awg", "unconfigured"):
            raise ValueError("invalid active transport")
        if self.selection_mode not in ("manual", "fixed", "auto"):
            raise ValueError("invalid selection mode")
        if self.node_policy not in ("manual", "fixed", "auto"):
            raise ValueError("invalid node mode")
        if self.mihomo_status not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("invalid Mihomo status")
        if self.awg_status not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("invalid AWG status")


@dataclass
class Memory:
    mihomo_fails: int = 0
    awg_fails: int = 0
    mihomo_passes: int = 0
    seen_mihomo: str = ""
    seen_awg: str = ""
    last_switch_at: int = 0
    outage_since: int = 0
    mihomo_first_bad_at: int = 0
    awg_first_bad_at: int = 0
    last_detection_seconds: int = 0
    last_recovery_seconds: int = 0
    switches_total: int = 0


@dataclass(frozen=True)
class Decision:
    action: ActionName
    target: str  # node or transport name; blank when no switch
    status: str
    reason: str
    confirmed_failure: bool = False


def eligible_warm(obs: Observation) -> list[str]:
    if obs.node_policy == "manual":
        return []
    if obs.node_policy == "fixed":
        order = list(obs.allowed_nodes)
        if obs.active_transport == "mihomo" and obs.active_node in order:
            # Existing FIXED node policy is one-way: never wrap backward.
            order = order[order.index(obs.active_node) + 1:]
        return [n for n in order if n in obs.warm_nodes]
    # A saved active Mihomo node is not actually active while AWG serves users.
    return [n for n in obs.warm_nodes
            if obs.active_transport != "mihomo" or n != obs.active_node]


def consume_samples(obs: Observation, previous: Memory) -> Memory:
    # Re-reading one cached service result every 10s is NOT multiple successes.
    current = Memory(**vars(previous))
    if obs.mihomo_sample and obs.mihomo_sample != previous.seen_mihomo:
        current.seen_mihomo = obs.mihomo_sample
        if obs.mihomo_status == "PASS":
            current.mihomo_passes += 1
            current.mihomo_fails = 0
            current.mihomo_first_bad_at = 0
        elif obs.mihomo_status == "FAIL":
            if not current.mihomo_fails:
                current.mihomo_first_bad_at = obs.now
            current.mihomo_fails += 1
            current.mihomo_passes = 0
        else:
            current.mihomo_passes = 0
            current.mihomo_fails = 0
            current.mihomo_first_bad_at = 0
            # UNKNOWN breaks a consecutive failure streak.
    if obs.awg_sample and obs.awg_sample != previous.seen_awg:
        current.seen_awg = obs.awg_sample
        if obs.awg_status == "PASS":
            current.awg_fails = 0
            current.awg_first_bad_at = 0
        elif obs.awg_status == "FAIL":
            if not current.awg_fails:
                current.awg_first_bad_at = obs.now
            current.awg_fails += 1
        else:
            current.awg_fails = 0
            current.awg_first_bad_at = 0
    return current


def evaluate(obs: Observation, previous: Memory, policy: Policy = Policy()) -> tuple[Decision, Memory]:
    """Predict a command; caller must do real preflight, commit and rollback."""
    mem = consume_samples(obs, previous)
    if obs.selection_mode != "auto":
        return Decision("KEEP", "", "MANUAL_OR_FIXED", "policy_not_auto"), mem

    warm = eligible_warm(obs)
    current = obs.active_transport
    if current == "mihomo":
        if obs.mihomo_status == "PASS":
            mem.outage_since = 0
            return Decision("KEEP", "", "ACTIVE_MIHOMO", "service_healthy"), mem
        if obs.mihomo_status == "UNKNOWN":
            return Decision("KEEP", "", "PROBE_UNKNOWN", "unconfirmed_service_failure"), mem
        if mem.mihomo_fails < policy.required_failures:
            return Decision("KEEP", "", "SUSPECT_MIHOMO", "awaiting_failure_confirmation"), mem
        if not mem.outage_since:
            mem.outage_since = mem.mihomo_first_bad_at or obs.now
        mem.last_detection_seconds = max(0, obs.now - mem.outage_since)
        if warm:
            # This is a suggested node, not permission to bypass live recheck.
            return Decision("SELECT_NODE", warm[0], "RECOVERY_PENDING",
                            "service_failover_to_hot_spare", True), mem
        if obs.awg_status == "PASS":
            return Decision("SELECT_TRANSPORT", "awg", "RECOVERY_PENDING",
                            "no_warm_mihomo_node", True), mem
        if not mem.outage_since:
            mem.outage_since = obs.now
        return Decision("RECOVERY_WAIT", "", "NO_WORKING_TRANSPORT"
                        if obs.awg_status == "FAIL" else "SERVICE_DEGRADED",
                        "awg_unqualified_no_mihomo_spare", True), mem

    if current == "awg":
        if obs.awg_status == "FAIL" and mem.awg_fails >= policy.required_failures:
            if not mem.outage_since:
                mem.outage_since = mem.awg_first_bad_at or obs.now
            mem.last_detection_seconds = max(0, obs.now - mem.outage_since)
            if obs.mihomo_status == "PASS" and warm:
                # Emergency recovery ignores plan-switch dwell time.
                return Decision("SELECT_TRANSPORT", "mihomo", "RECOVERY_PENDING",
                                "awg_failed_mihomo_recovered", True), mem
            if not mem.outage_since:
                mem.outage_since = obs.now
            return Decision("RECOVERY_WAIT", "", "NO_WORKING_TRANSPORT"
                            if obs.mihomo_status == "FAIL" else "SERVICE_DEGRADED",
                            "awg_failed_no_verified_mihomo", True), mem
        if obs.awg_status == "UNKNOWN":
            return Decision("KEEP", "", "PROBE_UNKNOWN", "awg_unconfirmed"), mem
        if obs.awg_status == "FAIL":
            return Decision("KEEP", "", "SUSPECT_AWG", "awaiting_failure_confirmation"), mem
        mem.outage_since = 0
        if (policy.priority[0] == "mihomo" and policy.auto_failback
                and obs.mihomo_status == "PASS" and warm
                and mem.mihomo_passes >= policy.failback_passes
                and obs.now - mem.last_switch_at >= policy.failback_dwell_seconds):
            return Decision("SELECT_TRANSPORT", "mihomo", "RECOVERY_PENDING",
                            "confirmed_priority_failback"), mem
        return Decision("KEEP", "", "ACTIVE_AWG", "stable_or_waiting_failback"), mem

    # Fresh install / recovery: choose only explicitly verified transport.
    for transport in policy.priority:
        if transport == "mihomo" and obs.mihomo_status == "PASS" and warm:
            return Decision("SELECT_TRANSPORT", "mihomo", "RECOVERY_PENDING",
                            "mihomo_first_ready"), mem
        if transport == "awg" and obs.awg_status == "PASS":
            return Decision("SELECT_TRANSPORT", "awg", "RECOVERY_PENDING",
                            "awg_first_ready"), mem
    return Decision("RECOVERY_WAIT", "", "NO_WORKING_TRANSPORT",
                    "no_verified_transport"), mem


def commit_success(mem: Memory, now: int) -> Memory:
    """Call ONLY after confirmed successful switch, never on a recommendation."""
    after = Memory(**vars(mem))
    after.last_switch_at = now
    after.last_recovery_seconds = max(0, now - after.outage_since) if after.outage_since else 0
    after.switches_total += 1
    after.outage_since = 0
    after.mihomo_first_bad_at = 0
    after.awg_first_bad_at = 0
    after.mihomo_fails = 0
    after.awg_fails = 0
    after.mihomo_passes = 0
    return after
