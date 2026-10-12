#!/usr/bin/env python3
"""Fail-closed transactional *model* for service-aware selector switches.

NO production adapters. This module deliberately cannot call a real
transport/node CLI or modify routes. It executes exclusively against an
explicit injected interface in unit/fault-injection tests.

The eventual adapter must be owned by the existing awg-selection-monitor.
Do NOT hold /run/awg-maintenance.lock while calling awg-transport select:
that CLI acquires the same lock itself. Use an independent action gate,
revalidate observations immediately before apply, and respect the internal
maintenance lock in the existing transport implementation.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Verdict:
    status: str
    reason: str
    action: str
    target: str
    rolled_back: bool = False
    fail_closed: bool = False


def allowed_action(advice: dict, evidence: dict, backend: Any) -> tuple[bool, str]:
    """Defensive independent authorization, not merely 'trust the AI/observer'."""
    if advice.get("mode") != "DRY_RUN_ONLY":
        return False, "invalid_advisory_format"
    action, target = advice.get("action"), advice.get("target")
    if action not in ("SELECT_NODE", "SELECT_TRANSPORT"):
        return False, "no_switch_requested"
    import time
    now = int(time.time())
    # Never act on an expired or attacker-crafted result attributed to a
    # different monitoring cycle. Local files are not signatures.
    generated = evidence.get("generated_at")
    if (evidence.get("version") != 1
            or not isinstance(generated, int) or isinstance(generated, bool)
            or generated > now or now - generated > 60):
        return False, "stale_or_invalid_evidence"
    if (advice.get("status") != "RECOVERY_PENDING"
            or advice.get("reason") not in
            ("service_failover_to_hot_spare", "no_warm_mihomo_node",
             "confirmed_priority_failback", "awg_failed_mihomo_recovered")):
        return False, "invalid_recovery_recommendation"
    selection = evidence.get("selection", {})
    if not isinstance(selection, dict) or selection.get("mode") != "auto":
        return False, "automatic_selection_disabled"
    existing = backend.snapshot()
    main = evidence.get("main", {})
    if (not isinstance(main, dict)
            or existing.get("transport") != main.get("transport")
            or existing.get("node", "") != main.get("node", "")):
        return False, "selected_transport_or_node_changed"
    if not existing.get("guard_safe"):
        return False, "guard_not_safe"

    # Evidence is not executable just because some JSON says PASS.
    from pathlib import Path
    import importlib.machinery
    import importlib.util
    import sys
    path = Path(__file__).with_name("awg-service-observer.py")
    loader = importlib.machinery.SourceFileLoader("awg_switch_observer", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    ttl = 120
    def service(target_transport: str, identity: str) -> str:
        status, _ = module.checked_status(evidence.get("service", {}).get(target_transport),
                                           now=now, transport=target_transport,
                                           identity=identity, ttl=ttl)
        return status

    warmed = module.standby_ready(
        evidence.get("standby"), now=now, ttl=ttl,
        provider_sha=evidence.get("provider_sha256", ""),
        router_generation=evidence.get("router_generation"),
        router_boot_id=evidence.get("router_boot_id", ""))
    if action == "SELECT_TRANSPORT":
        if target not in ("awg", "mihomo") or target == existing["transport"]:
            return False, "invalid_transport_target"
        if target == "awg":
            if (existing["transport"] != "mihomo"
                    or advice.get("reason") != "no_warm_mihomo_node"
                    or advice.get("recovery_confirmed") is not True):
                return False, "awg_fallback_not_authorized"
            if service("awg", "awg0") != "PASS":
                return False, "awg_not_service_qualified"
            if service("mihomo", existing.get("node", "")) != "FAIL":
                return False, "active_mihomo_not_confirmed_failed"
            if warmed:
                return False, "warm_mihomo_spare_has_priority"
        if target == "mihomo":
            if existing["transport"] != "awg":
                return False, "mihomo_target_requires_active_awg"
            if not warmed:
                return False, "mihomo_has_no_service_qualified_hot_spare"
            if advice.get("reason") == "confirmed_priority_failback":
                if (selection.get("auto_failback") is not True
                        or selection.get("priority", ["mihomo", "awg"])[0] != "mihomo"):
                    return False, "priority_failback_not_enabled"
            elif advice.get("reason") == "awg_failed_mihomo_recovered":
                if (advice.get("recovery_confirmed") is not True
                        or service("awg", "awg0") != "FAIL"):
                    return False, "awg_failure_not_confirmed"
            else:
                return False, "invalid_mihomo_recovery_reason"
        return True, "validated"

    if (advice.get("reason") != "service_failover_to_hot_spare"
            or advice.get("recovery_confirmed") is not True):
        return False, "node_failover_not_authorized"
    if existing["transport"] != "mihomo":
        return False, "cannot_switch_node_when_mihomo_inactive"
    if service("mihomo", existing.get("node", "")) != "FAIL":
        return False, "active_mihomo_not_confirmed_failed"
    if not isinstance(target, str) or not target or target == existing.get("node"):
        return False, "invalid_node_target"
    mode = evidence.get("node_policy", {})
    if mode.get("mode") == "manual":
        return False, "node_policy_manual"
    if mode.get("mode") == "fixed":
        order = mode.get("allowed", [])
        if existing.get("node") not in order or target not in order:
            return False, "node_not_in_fixed_chain"
        if order.index(target) <= order.index(existing["node"]):
            return False, "fixed_chain_cannot_wrap"
    if target not in warmed:
        return False, "target_not_service_qualified_in_hot_spare"
    return True, "validated"


def execute_mock_transaction(advice: dict, evidence: dict, backend: Any) -> Verdict:
    """The injected backend is *test-only*. No OS or VPN command here."""
    allowed, why = allowed_action(advice, evidence, backend)
    action, target = str(advice.get("action", "")), str(advice.get("target", ""))
    if not allowed:
        return Verdict("BLOCKED", why, action, target)
    prior = backend.snapshot()
    if not backend.try_action_gate():
        return Verdict("BLOCKED", "concurrent_switch_or_maintenance", action, target)
    applied = False
    try:
        # State and service evidence must be checked by the real adapter again
        # *after* acquiring a separate action gate.
        allowed, why = allowed_action(advice, evidence, backend)
        if not allowed:
            return Verdict("BLOCKED", "revalidate_" + why, action, target)
        # An advisory JSON file cannot testify to its own validity. The live
        # adapter must independently verify two DISTINCT recent observations
        # of the current failure and a freshly qualified target while under
        # an action gate, before touching any service or route.
        if not backend.confirm_recent_evidence(advice, evidence):
            return Verdict("BLOCKED", "independent_evidence_unconfirmed",
                           action, target)
        if not backend.prepare(action, target):
            return Verdict("BLOCKED", "prepare_failed", action, target)
        # Preparing another node must never preempt live user routing.
        after_prepare = backend.snapshot()
        if (after_prepare.get("transport") != prior.get("transport")
                or after_prepare.get("route") != prior.get("route")):
            try:
                backend.restore(prior)
                recovered = backend.snapshot()
                if (recovered.get("route") == prior.get("route")
                        and recovered.get("transport") == prior.get("transport")
                        and recovered.get("guard_safe")):
                    return Verdict("ROLLED_BACK", "prepare_changed_route",
                                   action, target, rolled_back=True)
            except Exception:
                pass
            backend.force_fail_closed()
            return Verdict("FAIL_CLOSED_REQUIRED", "prepare_rollback_unverified",
                           action, target, fail_closed=True)
        if not backend.preflight(action, target):
            try:
                if backend.restore(prior) is False:
                    raise RuntimeError("prepare abort failed")
                after_abort = backend.snapshot()
                if (after_abort.get("route") == prior.get("route")
                        and after_abort.get("transport") == prior.get("transport")
                        and after_abort.get("guard_safe")):
                    return Verdict("BLOCKED", "preflight_failed", action,
                                   target, rolled_back=True)
            except Exception:
                pass
            backend.force_fail_closed()
            return Verdict("FAIL_CLOSED_REQUIRED", "preflight_abort_unverified",
                           action, target, fail_closed=True)
        applied = True
        if not backend.apply(action, target):
            raise RuntimeError("apply_failed")
        after = backend.snapshot()
        expected_transport = target if action == "SELECT_TRANSPORT" else "mihomo"
        if (after.get("transport") != expected_transport
                or not after.get("guard_safe")
                or not backend.postflight(action, target)):
            raise RuntimeError("postflight_failed")
        return Verdict("COMMITTED", "postflight_passed", action, target)
    except Exception:
        if not applied:
            return Verdict("FAILED", "unexpected_precommit_error", action, target)
        try:
            backend.restore(prior)
            after_rollback = backend.snapshot()
            if (after_rollback.get("route") == prior.get("route")
                    and after_rollback.get("transport") == prior.get("transport")
                    and after_rollback.get("guard_safe")):
                return Verdict("ROLLED_BACK", "postflight_or_apply_failed", action,
                               target, rolled_back=True)
        except Exception:
            pass
        # Only a future real adapter can call the hardware firewall guard.
        backend.force_fail_closed()
        return Verdict("FAIL_CLOSED_REQUIRED", "rollback_unverified", action,
                       target, fail_closed=True)
    finally:
        backend.release_action_gate()
