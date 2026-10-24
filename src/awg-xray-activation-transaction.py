#!/usr/bin/env python3
"""Guarded cross-core activation transaction (backend-independent).

The Linux backend is deliberately not activated by this module. Every state
change is delegated to an explicitly installed backend. The transaction will
not disarm its independent watchdog or report PASS before local runtime validation
AND persistence/reboot wiring are validated. A failed predecessor is never
restored by this transaction.
"""
from dataclasses import dataclass
from typing import Protocol

class ActivationFailure(RuntimeError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable

class Backend(Protocol):
    def preflight(self, failed: str, candidate: str) -> None: ...
    def arm_watchdog(self) -> None: ...
    def stage_xray(self, candidate: str) -> None: ...
    def start_xray(self) -> None: ...
    def check_local_ready(self) -> bool: ...
    def stage_mihomo_bridge(self) -> None: ...
    def restart_mihomo(self) -> None: ...
    def restore_kernel_routes(self) -> None: ...
    def select_xray_bridge(self) -> None: ...
    def check_tun_ready(self) -> bool: ...
    def check_policy_routes(self) -> bool: ...
    def check_provider_unchanged(self) -> bool: ...
    def install_boot_dependencies(self) -> None: ...
    def check_boot_dependencies(self) -> bool: ...
    def verify_committed_node(self, candidate: str) -> bool: ...
    def commit(self) -> None: ...
    def disarm_watchdog(self) -> None: ...
    def fail_closed(self) -> bool: ...
    def finalize_retryable_abort(self) -> bool: ...

@dataclass(frozen=True)
class Receipt:
    candidate: str
    stages: tuple[str, ...]
    runtime_ready: bool
    boot_wiring_verified: bool

def activate(failed: str, candidate: str, backend: Backend) -> Receipt:
    if not failed or not candidate or candidate == failed:
        raise ActivationFailure("FAILED_NODE_REUSE_OR_INVALID_CANDIDATE")
    stages = []
    armed = False
    try:
        backend.preflight(failed, candidate)
        stages.append("PREFLIGHT")
        backend.arm_watchdog()
        armed = True
        stages.append("WATCHDOG_ARMED")
        backend.stage_xray(candidate)
        backend.start_xray()
        if not backend.check_local_ready():
            raise ActivationFailure("XRAY_LOCAL_NOT_READY")
        stages.append("XRAY_LOCAL_READY")
        if not backend.check_provider_unchanged():
            raise ActivationFailure("PROVIDER_CHANGED")
        backend.stage_mihomo_bridge()
        backend.restart_mihomo()
        backend.restore_kernel_routes()
        backend.select_xray_bridge()
        if not backend.check_tun_ready():
            raise ActivationFailure("LIVE_TUN_NOT_READY")
        if not backend.check_policy_routes():
            raise ActivationFailure("POLICY_ROUTES_CHANGED")
        stages.append("TUN_RUNTIME_READY")
        backend.install_boot_dependencies()
        if not backend.check_boot_dependencies():
            raise ActivationFailure("BOOT_DEPENDENCIES_UNVERIFIED")
        if not backend.check_provider_unchanged():
            raise ActivationFailure("PROVIDER_CHANGED")
        if not backend.verify_committed_node(candidate):
            raise ActivationFailure("COMMITTED_NODE_MISMATCH")
        stages.append("BOOT_WIRING_VERIFIED")
        # A failed commit must NOT cancel the watchdog.
        backend.commit()
        stages.append("COMMITTED")
        backend.disarm_watchdog()
        return Receipt(candidate, tuple(stages), True, True)
    except Exception as exc:
        if armed:
            try:
                safe = backend.fail_closed()
            except Exception:
                safe = False
            if not safe:
                raise ActivationFailure("FAIL_CLOSED_UNCONFIRMED_WATCHDOG_ARMED") from exc
            # Only typed candidate runtime failure can permit another AUTO node.
            # Retire this transaction's watchdog durably before any retry:
            # an old armed watchdog must never quiesce a later healthy node.
            if (isinstance(exc, ActivationFailure) and
                str(exc) in ("XRAY_LOCAL_NOT_READY", "LIVE_TUN_NOT_READY")):
                finalize = getattr(backend, "finalize_retryable_abort", None)
                try:
                    retryable = bool(finalize and finalize())
                except Exception:
                    retryable = False
                if retryable:
                    raise ActivationFailure("ACTIVATION_ABORTED_"+str(exc),
                                            retryable=True) from exc
            # Unsafe/infrastructure failures retain the independent watchdog.
        raise ActivationFailure("ACTIVATION_ABORTED_"+str(exc)) from exc
