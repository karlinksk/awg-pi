#!/usr/bin/env python3
"""Pure cross-core failover decision gate. No networking, writes or activation.

This module is intentionally NOT an activation implementation. It rejects
unsafe transactions until a separately installed, hardware-validated executor
provides proof of both independent recovery and a live TUN postcheck.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Candidate:
    name: str
    engine: str
    basic_network: str
    provider_sha256: str

class Rejected(ValueError):
    pass

def select_candidate(current, candidates, provider_sha256, *,
                     xray_executor_certified=False, max_visits=6):
    if not current or not isinstance(provider_sha256, str) or len(provider_sha256) != 64:
        raise Rejected("INVALID_EVENT")
    visited = set((current,))
    for candidate in candidates[:max_visits]:
        if candidate.name in visited:
            continue
        visited.add(candidate.name)
        if candidate.provider_sha256 != provider_sha256:
            continue
        if candidate.basic_network != "NETWORK_OK":
            continue
        if candidate.engine == "MIHOMO":
            return candidate
        if candidate.engine == "XRAY" and xray_executor_certified:
            return candidate
    raise Rejected("NO_CERTIFIED_CANDIDATE")

def validate_xray_commit(*, original_failed, selected, independent_recovery,
                         tun_postcheck, route_100, route_101, transit_guard):
    if not all((independent_recovery, tun_postcheck, route_100, route_101, transit_guard)):
        raise Rejected("CROSS_CORE_POSTCHECK_INCOMPLETE")
    if not selected or selected == original_failed:
        raise Rejected("FAILED_NODE_REUSE")
    return True
