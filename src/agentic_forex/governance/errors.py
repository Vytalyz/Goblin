"""Governance-layer error classes.

These exceptions are raised by ML phase runners when a deterministic
gate is violated. They are caught by callers (CLI / scripts) and turned
into non-zero exit codes plus Decision-Log entries.

Phase 1.7 (D14) requires the baseline runner to raise these explicitly
so the gate is enforced in code, not just in narrative documentation.
"""
from __future__ import annotations


class GovernanceError(Exception):
    """Base for all governance violations."""


class RegimeNonNegativityError(GovernanceError):
    """Raised when XGB-vs-rule PF lift is negative in any regime bucket.

    The plan (1.6 Acceptance, D14) requires lift >= 0 in every regime,
    not just in aggregate.
    """


class CostSensitivityError(GovernanceError):
    """Raised when XGB lift fails to persist at +1.0 pip transaction cost.

    The plan (1.6 Acceptance, D14) requires the lift be robust to a
    +1.0 pip cost shock; if it disappears, the edge is fragile and the
    candidate is not P2-eligible.
    """


class DatasetSHAMismatchError(GovernanceError):
    """Raised when working-tree parquet SHA does not match the Decision
    Log pin for the active phase (D15 enforcement)."""


class HoldoutAccessExceededError(GovernanceError):
    """Raised when more than 2 HOLDOUT-ACCESS Decision Log entries exist
    (D12 enforcement). The sealed holdout may be opened exactly twice:
    once at Phase 2.0 re-gate, once at Phase 2.10 final."""
