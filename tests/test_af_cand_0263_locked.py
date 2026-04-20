"""Property tests for the AF-CAND-0263 locked-benchmark guard (ML-1.7).

Per the ML-1.7 plan-hardening amendment, the locked-benchmark detection must
be robust to common adversarial variants:

    - case variants
    - whitespace variants
    - JSON-embedding variants (id appears inside a JSON blob)
    - quoted variants

Unicode-lookalike confusables are explicitly out of scope (a separate
governance concern).
"""

from __future__ import annotations

import json

import pytest

from agentic_forex.governance.locked_benchmark import (
    LOCKED_BENCHMARK_ID,
    assert_not_locked_benchmark,
    contains_locked_benchmark,
    is_locked_benchmark,
    normalize_candidate_id,
)


@pytest.mark.parametrize(
    "raw",
    [
        "AF-CAND-0263",
        "af-cand-0263",
        "Af-Cand-0263",
        "AF-cand-0263",
        "aF-CAND-0263",
    ],
)
def test_case_variants_detected(raw: str) -> None:
    assert is_locked_benchmark(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "  AF-CAND-0263",
        "AF-CAND-0263  ",
        "\tAF-CAND-0263\t",
        "AF-CAND-0263\n",
        "  af-cand-0263  ",
    ],
)
def test_whitespace_variants_detected(raw: str) -> None:
    assert is_locked_benchmark(raw)


@pytest.mark.parametrize(
    "raw",
    [
        '"AF-CAND-0263"',
        "'AF-CAND-0263'",
        ' " AF-CAND-0263 " ',
    ],
)
def test_quoted_variants_detected(raw: str) -> None:
    assert is_locked_benchmark(raw)


@pytest.mark.parametrize(
    "blob",
    [
        '{"candidate_id": "AF-CAND-0263"}',
        '{"candidates": ["AF-CAND-0001", "af-cand-0263"]}',
        '["AF-CAND-0263"]',
        "candidate=AF-CAND-0263",
        "running candidate AF-CAND-0263 now",
    ],
)
def test_json_embedding_detected(blob: str) -> None:
    assert contains_locked_benchmark(blob)


@pytest.mark.parametrize(
    "raw",
    [
        "AF-CAND-0264",
        "AF-CAND-02631",
        "AF-CAND-026",
        "XAF-CAND-0263",
        "AF-CAND-0263X",
        "",
        "   ",
    ],
)
def test_non_matches_pass_through(raw: str) -> None:
    assert not is_locked_benchmark(raw)


def test_non_strings_safe() -> None:
    assert not is_locked_benchmark(None)  # type: ignore[arg-type]
    assert not is_locked_benchmark(263)  # type: ignore[arg-type]
    assert not contains_locked_benchmark(None)  # type: ignore[arg-type]


def test_normalize_strips_quotes_and_whitespace() -> None:
    assert normalize_candidate_id('"  af-cand-0263  "') == LOCKED_BENCHMARK_ID
    assert normalize_candidate_id("AF-CAND-0007") == "AF-CAND-0007"


def test_normalize_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        normalize_candidate_id(263)  # type: ignore[arg-type]


def test_assert_not_locked_benchmark_raises_on_match() -> None:
    with pytest.raises(ValueError, match="locked overlap benchmark"):
        assert_not_locked_benchmark("af-cand-0263", context="ML-test")


def test_assert_not_locked_benchmark_passes_on_other() -> None:
    assert_not_locked_benchmark("AF-CAND-0007", context="ML-test")


def test_substring_in_longer_id_does_not_falsely_match() -> None:
    # contains_locked_benchmark uses word boundaries; embedded substrings
    # like AF-CAND-02631 must NOT trigger.
    assert not contains_locked_benchmark("running AF-CAND-02631 now")
    assert not contains_locked_benchmark("XAF-CAND-0263Y")


def test_contains_locked_benchmark_matches_in_real_json_blob() -> None:
    blob = json.dumps({"candidates": ["AF-CAND-0007", "AF-CAND-0263", "AF-CAND-0322"]})
    assert contains_locked_benchmark(blob)
