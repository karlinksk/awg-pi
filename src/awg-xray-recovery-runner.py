#!/usr/bin/env python3
"""Pure transaction orchestration for failed-node recovery.

No system services are touched by this module. A production adapter must
provide the watchdog, candidate activation, live-TUN verification and
Transit-safe quiesce operations; it must not use the manual canary rollback,
which may restore the already failed original node.
"""
from dataclasses import dataclass
from typing import Callable

class RecoveryFailed(RuntimeError):
    pass

@dataclass(frozen=True)
class Recovery:
    selected: str
    attempted: tuple[str, ...]
    verified: bool

def recover(failed: str, candidates: list[str], *,
            activate: Callable[[str], bool],
            verify: Callable[[str], bool],
            quiesce: Callable[[], bool],
            reject_cleanup: Callable[[str], bool] | None = None,
            max_attempts: int = 6) -> Recovery:
    if not failed or max_attempts < 1:
        raise ValueError("INVALID_RECOVERY_INPUT")
    seen = {failed}
    attempted = []
    for candidate in candidates:
        if len(attempted) >= max_attempts:
            break
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        attempted.append(candidate)
        try:
            if activate(candidate) and verify(candidate):
                return Recovery(candidate, tuple(attempted), True)
        except Exception:
            # A candidate error is never evidence that the previous failed
            # node has recovered. Keep trying only distinct candidates.
            pass
        # A failed activation or TUN postcheck may have left a live sidecar
        # or new Mihomo controller selection. Never try another candidate
        # until an independent cleanup proves that state is safe.
        try:
            cleaned = reject_cleanup is not None and reject_cleanup(candidate)
        except Exception:
            cleaned = False
        if not cleaned:
            try:
                safe = quiesce()
            except Exception:
                safe = False
            if not safe:
                raise RecoveryFailed("REJECT_CLEANUP_AND_QUIESCE_FAILED")
            raise RecoveryFailed("REJECT_CLEANUP_UNVERIFIED")
    # Stop unverified forwarding under the existing Transit drop guard or
    # apply Selective fail-open using the platform's existing quiesce policy.
    if not quiesce():
        raise RecoveryFailed("QUIESCE_FAILED")
    raise RecoveryFailed("NO_VERIFIED_RECOVERY")
