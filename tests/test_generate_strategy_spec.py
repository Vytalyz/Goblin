"""Tests for tools/generate_strategy_spec.py (Stage 1 scaffolder)."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import generate_strategy_spec as gss  # type: ignore  # noqa: E402
import verify_strategy_decisions_schema as vsd  # type: ignore  # noqa: E402


# --- Fixtures ---------------------------------------------------------------


def _write_policy(tmp_path: Path) -> Path:
    """Write a minimal portfolio_policy.toml mirroring the real layout."""
    policy = tmp_path / "config" / "portfolio_policy.toml"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        textwrap.dedent(
            """
            [portfolio]

            [[portfolio.slots]]
            slot_id = "slot_a"
            mode = "active_candidate"
            mutation_allowed = true
            allowed_families = ["overlap_resolution_bridge_research"]

            [[portfolio.slots]]
            slot_id = "slot_b"
            mode = "blank_slate_research"
            mutation_allowed = true
            allowed_families = [
              "europe_open_impulse_retest_research",
              "europe_open_opening_range_retest_research",
            ]
            strategy_inheritance = "none_from_prior_candidates"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return policy


@pytest.fixture
def isolated_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    policy = _write_policy(tmp_path)
    monkeypatch.setattr(gss, "PORTFOLIO_POLICY", policy)
    monkeypatch.setattr(gss, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gss, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(gss, "DECISIONS_LOG", tmp_path / "Goblin" / "decisions" / "strategy_decisions.jsonl")
    monkeypatch.setattr(gss, "RATIONALE_CARD_DIR", tmp_path / "Goblin" / "reports" / "strategy_rationale_cards")
    return tmp_path


def _valid_kwargs(slot_id: str = "slot_b", family: str = "europe_open_impulse_retest_research") -> dict:
    return dict(
        slot_id=slot_id,
        family=family,
        hypothesis="EUR/USD shows mean-reverting behavior after >20pip moves at the EU open.",
        stop_loss_pips=8.0,
        take_profit_pips=24.0,
        holding_bars=120,
        signal_threshold=2.0,
        what_invalidates="Trend regime overrides mean-reversion at session open.",
        hostile_regimes=["trend_high_vol", "news_event"],
        execution_assumptions="M1 fills, OANDA spread, no slippage adjustment",
        non_deployable_when="Spread > 2.0 pips or news within 15 minutes.",
    )


# --- Happy path -------------------------------------------------------------


def test_scaffold_creates_three_artifacts(isolated_repo: Path) -> None:
    result = gss.scaffold(repo_root=isolated_repo, **_valid_kwargs())

    cid = result["candidate_id"]
    assert cid == "AF-CAND-0001"

    spec_path = Path(result["spec_path"])
    rationale_path = Path(result["rationale_card_path"])
    log_path = isolated_repo / "Goblin" / "decisions" / "strategy_decisions.jsonl"

    assert spec_path.exists()
    assert rationale_path.exists()
    assert log_path.exists()

    spec = json.loads(spec_path.read_text())
    assert spec["candidate_id"] == cid
    assert spec["slot_id"] == "slot_b"
    assert spec["family"] == "europe_open_impulse_retest_research"
    assert spec["instrument"] == "EUR_USD"
    assert spec["holding_bars"] == 120
    assert spec["stop_loss_pips"] == 8.0
    assert spec["take_profit_pips"] == 24.0
    assert spec["signal_threshold"] == 2.0
    assert spec["stage"] == "S1"

    card = json.loads(rationale_path.read_text())
    assert set(card.keys()) >= {
        "candidate_id",
        "why_edge_should_exist",
        "what_invalidates_the_edge",
        "regimes_that_should_hurt_it",
        "execution_assumptions_it_depends_on",
        "what_makes_it_non_deployable",
    }
    assert card["regimes_that_should_hurt_it"] == ["trend_high_vol", "news_event"]


def test_decision_entry_passes_schema_validator(isolated_repo: Path) -> None:
    gss.scaffold(repo_root=isolated_repo, **_valid_kwargs())
    log_path = isolated_repo / "Goblin" / "decisions" / "strategy_decisions.jsonl"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])

    # Run the canonical validator against the entry.
    seen_ids: set[str] = set()
    vsd._check_entry(1, entry, seen_ids=seen_ids)
    assert entry["decision_id"] in seen_ids


def test_decision_id_format(isolated_repo: Path) -> None:
    result = gss.scaffold(repo_root=isolated_repo, **_valid_kwargs())
    entry = result["decision_entry"]
    assert entry["decision_id"] == f"DEC-STRAT-{result['candidate_id']}-S1-PASS"
    assert entry["stage"] == "S1"
    assert entry["outcome"] == "pass"
    assert entry["decided_by"] == "runner"


def test_id_allocation_increments_past_existing(isolated_repo: Path) -> None:
    (isolated_repo / "reports" / "AF-CAND-0050").mkdir(parents=True)
    (isolated_repo / "reports" / "AF-CAND-0099").mkdir(parents=True)
    (isolated_repo / "reports" / "AF-CAND-0007").mkdir(parents=True)
    result = gss.scaffold(repo_root=isolated_repo, **_valid_kwargs())
    assert result["candidate_id"] == "AF-CAND-0100"


def test_two_consecutive_scaffolds_get_distinct_ids(isolated_repo: Path) -> None:
    r1 = gss.scaffold(repo_root=isolated_repo, **_valid_kwargs())
    r2 = gss.scaffold(repo_root=isolated_repo, **_valid_kwargs())
    assert r1["candidate_id"] == "AF-CAND-0001"
    assert r2["candidate_id"] == "AF-CAND-0002"
    log_path = isolated_repo / "Goblin" / "decisions" / "strategy_decisions.jsonl"
    assert len(log_path.read_text().splitlines()) == 2


# --- Validation failures ----------------------------------------------------


def test_rejects_family_not_in_slot_allowed(isolated_repo: Path) -> None:
    kwargs = _valid_kwargs()
    kwargs["family"] = "some_unapproved_family"
    with pytest.raises(gss.StrategyScaffoldError, match="not in allowed_families"):
        gss.scaffold(repo_root=isolated_repo, **kwargs)


def test_rejects_slot_a_family_for_slot_b(isolated_repo: Path) -> None:
    """slot_a's family is not allowed for slot_b."""
    kwargs = _valid_kwargs(slot_id="slot_b", family="overlap_resolution_bridge_research")
    with pytest.raises(gss.StrategyScaffoldError, match="not in allowed_families"):
        gss.scaffold(repo_root=isolated_repo, **kwargs)


def test_rejects_short_hypothesis(isolated_repo: Path) -> None:
    kwargs = _valid_kwargs()
    kwargs["hypothesis"] = "too short"
    with pytest.raises(gss.StrategyScaffoldError, match="at least"):
        gss.scaffold(repo_root=isolated_repo, **kwargs)


def test_rejects_unknown_slot(isolated_repo: Path) -> None:
    kwargs = _valid_kwargs()
    kwargs["slot_id"] = "slot_z"
    with pytest.raises(gss.StrategyScaffoldError, match="not found"):
        gss.scaffold(repo_root=isolated_repo, **kwargs)


# --- Dry run ---------------------------------------------------------------


def test_dry_run_writes_nothing(isolated_repo: Path) -> None:
    result = gss.scaffold(repo_root=isolated_repo, dry_run=True, **_valid_kwargs())
    assert result["dry_run"] is True
    assert "spec_preview" in result
    assert "rationale_card_preview" in result
    # No files created.
    spec_path = Path(result["spec_path"])
    rationale_path = Path(result["rationale_card_path"])
    assert not spec_path.exists()
    assert not rationale_path.exists()
    assert not (isolated_repo / "Goblin" / "decisions" / "strategy_decisions.jsonl").exists()


# --- CLI ------------------------------------------------------------------


def test_cli_main_success(isolated_repo: Path, capsys: pytest.CaptureFixture) -> None:
    argv = [
        "--slot", "slot_b",
        "--family", "europe_open_impulse_retest_research",
        "--hypothesis", "EUR/USD shows mean-reverting behavior after >20pip moves at the EU open.",
        "--stop-loss-pips", "8",
        "--take-profit-pips", "24",
        "--holding-bars", "120",
        "--signal-threshold", "2.0",
        "--what-invalidates", "Trend regime overrides mean-reversion at session open.",
        "--hostile-regimes", "trend_high_vol,news_event",
        "--execution-assumptions", "M1 fills, OANDA spread, no slippage adjustment",
        "--non-deployable-when", "Spread > 2.0 pips or news within 15 minutes.",
        "--json",
    ]
    rc = gss.main(argv)
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["candidate_id"] == "AF-CAND-0001"
    assert payload["decision_entry"]["decision_id"] == "DEC-STRAT-AF-CAND-0001-S1-PASS"


def test_cli_main_returns_2_on_validation_error(isolated_repo: Path, capsys: pytest.CaptureFixture) -> None:
    argv = [
        "--slot", "slot_b",
        "--family", "BOGUS",
        "--hypothesis", "EUR/USD shows mean-reverting behavior after >20pip moves at the EU open.",
        "--stop-loss-pips", "8",
        "--take-profit-pips", "24",
        "--holding-bars", "120",
        "--signal-threshold", "2.0",
        "--what-invalidates", "x",
        "--hostile-regimes", "x",
        "--execution-assumptions", "x",
        "--non-deployable-when", "x",
    ]
    rc = gss.main(argv)
    assert rc == 2
    err = capsys.readouterr().err
    assert "ERROR" in err
