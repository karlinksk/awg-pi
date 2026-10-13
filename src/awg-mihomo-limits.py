"""Shared conservative Mihomo limits for AUTO SMART and Hot Standby.

All limits are caps, not guarantees of enough service-qualified nodes.
Changing one of these settings affects both independent screening engines.
"""
CANDIDATES = 10
SUSTAINED = 3
CONFIRMED = 2

assert 1 <= CONFIRMED <= SUSTAINED <= CANDIDATES <= 15
