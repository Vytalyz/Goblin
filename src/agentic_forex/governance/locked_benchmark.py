"""AF-CAND-0263 locked-benchmark identifier guard.

Provides a single canonical normalizer + matcher used by all ML drivers and
governance code paths to detect attempts to use the locked overlap benchmark
candidate ID, including under common adversarial variants:

    - case variants: ``af-cand-0263``, ``Af-CaNd-0263``
    - whitespace variants: ``"  AF-CAND-0263  "``, ``"AF-CAND-0263\\n"``
    - JSON-embedding variants: ``'{"id": "AF-CAND-0263"}'``
    - quoted variants: ``'"AF-CAND-0263"'``

We deliberately do NOT attempt to match unicode-lookalike confusables — that is
a separate concern (the AGENTS.md governance rule is about literal identifier
mutation, not adversarial unicode).

Used by ML-1.7 plan-hardening property tests.
"""

from __future__ import annotations

import re

LOCKED_BENCHMARK_ID = "AF-CAND-0263"

# Match the locked id even when embedded in a longer ASCII string, anchored on
# the canonical hyphenated form. Word boundaries on both sides keep
# AF-CAND-02631 from triggering a false positive.
_LOCKED_PATTERN = re.compile(r"(?<![A-Za-z0-9])AF-CAND-0263(?![A-Za-z0-9])", re.IGNORECASE)


def normalize_candidate_id(raw: str) -> str:
    """Canonicalize a candidate id by stripping whitespace/quotes and uppercasing.

    Returns the original (stripped) string if it does not look like a candidate
    id. Used at the boundary of every CLI driver before identity comparisons.
    """
    if not isinstance(raw, str):
        raise TypeError(f"candidate id must be str, got {type(raw).__name__}")
    stripped = raw.strip().strip('"').strip("'").strip()
    return stripped.upper()


def is_locked_benchmark(raw: str) -> bool:
    """Return True if ``raw`` (after normalization) IS the locked benchmark id."""
    if not isinstance(raw, str):
        return False
    return normalize_candidate_id(raw) == LOCKED_BENCHMARK_ID


def contains_locked_benchmark(text: str) -> bool:
    """Return True if ``text`` contains the locked benchmark id anywhere.

    Use this when scanning a JSON blob, a CLI argument list rendered as a
    single string, or any other transport that may smuggle the id inside.
    """
    if not isinstance(text, str):
        return False
    return _LOCKED_PATTERN.search(text) is not None


def assert_not_locked_benchmark(raw: str, *, context: str = "candidate") -> None:
    """Raise ValueError if ``raw`` resolves to the locked benchmark id."""
    if is_locked_benchmark(raw):
        raise ValueError(
            f"{context}: {LOCKED_BENCHMARK_ID} is the locked overlap benchmark and cannot be used here (per AGENTS.md)."
        )
