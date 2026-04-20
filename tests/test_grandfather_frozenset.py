"""EX-7 — CI assertion that the grandfather frozenset is exactly the locked value."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import verify_decision_log_schema as v  # noqa: E402


def test_grandfathered_set_is_exact_locked_value():
    """The grandfather set must be the exact frozenset({'DEC-ML-1.6.0-CANDIDATES'}).

    Adding or removing entries silently would break the EX-7 invariant.
    A maintainer who legitimately needs to amend the set MUST update both
    this test AND the verify_decision_log_schema.py module-level assertion
    in the same commit (CODEOWNERS gate enforces review).
    """
    assert v.GRANDFATHERED_NO_BIAS_AUDIT == frozenset({"DEC-ML-1.6.0-CANDIDATES"})


def test_grandfathered_set_is_frozen():
    """frozenset is immutable; this catches accidental refactor to a set."""
    assert isinstance(v.GRANDFATHERED_NO_BIAS_AUDIT, frozenset)


def test_grandfathered_set_size_is_one():
    assert len(v.GRANDFATHERED_NO_BIAS_AUDIT) == 1
