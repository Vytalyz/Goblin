from __future__ import annotations

from conftest import create_corpus_mirror, create_oanda_candles_json

from agentic_forex.experiments import explore_day_trading_candidates, scan_day_trading_behaviors
from agentic_forex.experiments.day_trading_lab import _behavior_scan_score, _front_door_comparison_gate
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.utils.io import read_json


def test_explore_day_trading_candidates_generates_reviewed_candidate_set(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=3,
        max_sources=4,
    )

    assert report.report_path.exists()
    assert report.scan_report_path is not None
    assert report.scan_report_path.exists()
    assert report.comparison_report_path.exists()
    scan_payload = read_json(report.scan_report_path)
    eligible_candidate_ids = [
        record["candidate_id"] for record in scan_payload["records"] if record["comparison_eligible"]
    ][:3]
    ranked_candidate_ids = [record["candidate_id"] for record in scan_payload["records"]][:3]
    expected_candidate_ids = eligible_candidate_ids or ranked_candidate_ids
    assert len(report.candidates) == len(expected_candidate_ids)
    assert [candidate.candidate_id for candidate in report.candidates] == expected_candidate_ids
    assert report.recommended_candidate_id == (eligible_candidate_ids[0] if eligible_candidate_ids else None)
    for candidate in report.candidates:
        assert candidate.candidate_path.exists()
        assert candidate.spec_path.exists()
        assert candidate.backtest_summary_path.exists()
        assert candidate.stress_report_path.exists()
        assert candidate.review_packet_path.exists()


def test_explore_day_trading_candidates_can_seed_fourth_non_overlap_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=4,
        max_sources=4,
    )

    scan_payload = read_json(report.scan_report_path)
    eligible_candidate_ids = [
        record["candidate_id"] for record in scan_payload["records"] if record["comparison_eligible"]
    ][:4]
    ranked_candidate_ids = [record["candidate_id"] for record in scan_payload["records"]][:4]
    expected_candidate_ids = eligible_candidate_ids or ranked_candidate_ids
    assert len(report.candidates) == len(expected_candidate_ids)
    assert [candidate.candidate_id for candidate in report.candidates] == expected_candidate_ids
    comparison = read_json(report.comparison_report_path)
    for candidate in report.candidates:
        if comparison["candidate_filters"]:
            assert candidate.candidate_id in comparison["candidate_filters"]
        assert candidate.candidate_path.exists()
        assert candidate.review_packet_path.exists()


def test_scan_day_trading_behaviors_generates_ranked_behavior_report(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = scan_day_trading_behaviors(
        settings,
        mirror_path=mirror,
        max_sources=4,
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.screened_template_count >= report.materialized_candidate_count >= 1
    assert len(report.screen_records) == report.screened_template_count
    assert len(report.records) == report.materialized_candidate_count
    assert len(report.records) <= 4
    assert report.records == sorted(report.records, key=lambda item: item.scan_score, reverse=True)
    top_eligible = next((record for record in report.records if record.comparison_eligible), None)
    assert report.recommended_candidate_id == (top_eligible.candidate_id if top_eligible else None)
    default_families = {
        "europe_open_gap_drift_research",
        "europe_open_opening_range_breakout_research",
        "europe_open_post_open_pullback_research",
        "asia_europe_transition_daytype_reclaim_research",
    }
    assert {record.family for record in report.screen_records}.issubset(default_families)
    assert {record.family for record in report.records}.issubset(default_families)
    assert any(record.pretest_eligible for record in report.screen_records)
    for record in report.screen_records:
        assert record.open_anchor_hour_utc in {6, 7}
        assert record.max_hold_bars is not None and record.max_hold_bars <= 18
        assert record.overnight_allowed is False
    for record in report.records:
        assert record.candidate_path.exists()
        assert record.spec_path.exists()
        assert record.backtest_summary_path.exists()
        assert record.stress_report_path.exists()
        assert record.review_packet_path.exists()
        assert record.open_anchor_hour_utc == 7
        assert record.max_hold_bars is not None and record.max_hold_bars <= 18
        assert record.overnight_allowed is False
        assert record.risk_filter_profile == "spread_shock_realized_vol_calendar_blackout"
        assert record.book_alignment_score > 0.0


def test_explore_day_trading_candidates_can_target_gap_drift_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_gap_drift_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "session_breakout"
    candidate_payload = read_json(candidate.candidate_path)
    assert candidate_payload["open_anchor_hour_utc"] == 7
    assert candidate_payload["overnight_allowed"] is False
    assert candidate_payload["max_hold_bars"] <= 16


def test_explore_day_trading_candidates_can_target_opening_range_breakout_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_opening_range_breakout_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "compression_breakout"
    candidate_payload = read_json(candidate.candidate_path)
    assert candidate_payload["open_anchor_hour_utc"] == 7
    assert candidate_payload["overnight_allowed"] is False
    assert candidate_payload["max_hold_bars"] <= 16


def test_explore_day_trading_candidates_can_target_post_open_pullback_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_post_open_pullback_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "pullback_continuation"
    candidate_payload = read_json(candidate.candidate_path)
    assert candidate_payload["open_anchor_hour_utc"] == 7
    assert candidate_payload["overnight_allowed"] is False
    assert candidate_payload["max_hold_bars"] <= 14


def test_behavior_scan_score_prefers_density_over_sparse_outlier():
    sparse_outlier = _behavior_scan_score(
        trade_count=10,
        min_walk_forward_trade_count=0,
        oos_profit_factor=4.0,
        expectancy_pips=1.4,
        stressed_profit_factor=1.5,
        max_drawdown_pct=0.25,
        stress_passed=True,
        walk_forward_ok=False,
        supported_slice_count=2,
        comparison_eligible=True,
    )
    denser_candidate = _behavior_scan_score(
        trade_count=120,
        min_walk_forward_trade_count=18,
        oos_profit_factor=1.1,
        expectancy_pips=0.1,
        stressed_profit_factor=1.02,
        max_drawdown_pct=4.0,
        stress_passed=True,
        walk_forward_ok=False,
        supported_slice_count=1,
        comparison_eligible=True,
    )

    assert denser_candidate > sparse_outlier


def test_front_door_comparison_gate_rejects_uniformly_negative_train_validation():
    eligible, reason = _front_door_comparison_gate(
        split_breakdown={
            "train": {"profit_factor": 0.82, "expectancy_pips": -0.31},
            "validation": {"profit_factor": 0.77, "expectancy_pips": -0.12},
        },
        out_of_sample_profit_factor=0.91,
        expectancy_pips=-0.18,
        stressed_profit_factor=0.74,
        stress_passed=False,
    )

    assert eligible is False
    assert reason == "uniformly_negative_train_validation"


def test_front_door_comparison_gate_keeps_mixed_split_candidate():
    eligible, reason = _front_door_comparison_gate(
        split_breakdown={
            "train": {"profit_factor": 0.88, "expectancy_pips": -0.15},
            "validation": {"profit_factor": 1.08, "expectancy_pips": 0.06},
        },
        out_of_sample_profit_factor=1.12,
        expectancy_pips=0.09,
        stressed_profit_factor=1.01,
        stress_passed=True,
    )

    assert eligible is True
    assert reason is None


def test_front_door_comparison_gate_rejects_negative_edge_failed_stress():
    eligible, reason = _front_door_comparison_gate(
        split_breakdown={
            "train": {"profit_factor": 0.91, "expectancy_pips": -0.04},
            "validation": {"profit_factor": 1.04, "expectancy_pips": 0.02},
        },
        out_of_sample_profit_factor=0.93,
        expectancy_pips=-0.11,
        stressed_profit_factor=0.82,
        stress_passed=False,
    )

    assert eligible is False
    assert reason == "negative_edge_failed_stress"


def test_front_door_comparison_gate_rejects_book_vetoed_release_persistence():
    eligible, reason = _front_door_comparison_gate(
        split_breakdown={
            "train": {"profit_factor": 1.02, "expectancy_pips": 0.04},
            "validation": {"profit_factor": 1.01, "expectancy_pips": 0.01},
        },
        out_of_sample_profit_factor=1.08,
        expectancy_pips=0.05,
        stressed_profit_factor=1.01,
        stress_passed=True,
        book_alignment_score=-0.15,
        book_veto_reasons=["eurusd_release_persistence_veto"],
        overnight_allowed=False,
        max_hold_bars=12,
    )

    assert eligible is False
    assert reason == "book_veto_release_persistence"


def test_explore_day_trading_candidates_can_target_impulse_retest_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_impulse_retest_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "volatility_retest_breakout"
    candidate_payload = read_json(candidate.candidate_path)
    assert candidate_payload["open_anchor_hour_utc"] == 7
    assert candidate_payload["overnight_allowed"] is False
    assert candidate_payload["max_hold_bars"] <= 12


def test_explore_day_trading_candidates_can_target_opening_range_retest_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_opening_range_retest_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "compression_retest_breakout"
    candidate_payload = read_json(candidate.candidate_path)
    assert candidate_payload["open_anchor_hour_utc"] == 7
    assert candidate_payload["overnight_allowed"] is False
    assert candidate_payload["max_hold_bars"] <= 12


def test_explore_day_trading_candidates_can_target_early_follow_through_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_early_follow_through_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "session_momentum_band"
    candidate_payload = read_json(candidate.candidate_path)
    assert candidate_payload["open_anchor_hour_utc"] == 7
    assert candidate_payload["overnight_allowed"] is False
    assert candidate_payload["max_hold_bars"] <= 12


def test_explore_day_trading_candidates_can_target_opening_drive_fade_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_opening_drive_fade_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "failed_break_fade"
    candidate_payload = read_json(candidate.candidate_path)
    assert candidate_payload["open_anchor_hour_utc"] == 7
    assert candidate_payload["overnight_allowed"] is False
    assert candidate_payload["max_hold_bars"] <= 10


def test_explore_day_trading_candidates_can_target_asia_europe_transition_reclaim_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="asia_europe_transition_reclaim_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "drift_reclaim"
    candidate_payload = read_json(candidate.candidate_path)
    assert candidate_payload["open_anchor_hour_utc"] == 6
    assert candidate_payload["overnight_allowed"] is False
    assert candidate_payload["max_hold_bars"] <= 16


def test_explore_day_trading_candidates_can_target_compression_reversion_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_compression_reversion_research",
    )

    assert report.scan_report_path is not None
    assert report.scan_report_path.exists()
    scan_payload = read_json(report.scan_report_path)
    assert scan_payload["screen_records"]
    assert {record["family"] for record in scan_payload["screen_records"]} == {
        "europe_open_compression_reversion_research"
    }
    if report.candidates:
        candidate = report.candidates[0]
        assert candidate.entry_style == "compression_reversion"
        assert candidate.candidate_path.exists()
        assert candidate.review_packet_path.exists()
    else:
        assert scan_payload["records"] == []


def test_explore_day_trading_candidates_can_target_trend_retest_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_trend_retest_research",
    )

    assert report.scan_report_path is not None
    scan_payload = read_json(report.scan_report_path)
    assert scan_payload["screen_records"]
    assert {record["family"] for record in scan_payload["screen_records"]} == {"europe_open_trend_retest_research"}
    if report.candidates:
        candidate = report.candidates[0]
        assert candidate.entry_style == "trend_retest"
        assert candidate.candidate_path.exists()
        assert candidate.review_packet_path.exists()
    else:
        assert scan_payload["records"] == []


def test_explore_day_trading_candidates_can_target_retest_breakout_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_retest_breakout_research",
    )

    assert report.scan_report_path is not None
    scan_payload = read_json(report.scan_report_path)
    assert scan_payload["screen_records"]
    assert {record["family"] for record in scan_payload["screen_records"]} == {"europe_open_retest_breakout_research"}
    if report.candidates:
        candidate = report.candidates[0]
        assert candidate.entry_style == "volatility_retest_breakout"
        assert candidate.candidate_path.exists()
        assert candidate.review_packet_path.exists()
    else:
        assert scan_payload["records"] == []


def test_explore_day_trading_candidates_can_target_pullback_continuation_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_pullback_continuation_research",
    )

    assert report.scan_report_path is not None
    scan_payload = read_json(report.scan_report_path)
    assert scan_payload["screen_records"]
    assert {record["family"] for record in scan_payload["screen_records"]} == {
        "europe_open_pullback_continuation_research"
    }
    if report.candidates:
        candidate = report.candidates[0]
        assert candidate.entry_style == "pullback_continuation"
        assert candidate.candidate_path.exists()
        assert candidate.review_packet_path.exists()
    else:
        assert scan_payload["records"] == []


def test_explore_day_trading_candidates_can_target_high_vol_momentum_band_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_high_vol_momentum_band_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "session_momentum_band"
    assert candidate.candidate_path.exists()
    assert candidate.review_packet_path.exists()


def test_explore_day_trading_candidates_pretest_blocks_release_persistence_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_release_persistence_research",
    )

    assert report.candidates == []
    assert report.recommended_candidate_id is None
    scan_payload = read_json(report.scan_report_path)
    assert scan_payload["records"] == []
    assert scan_payload["screen_records"]
    assert all(record["pretest_eligible"] is False for record in scan_payload["screen_records"])
    assert all(str(record["pretest_reason"]).startswith("book_veto:") for record in scan_payload["screen_records"])
    comparison_payload = read_json(report.comparison_report_path)
    assert comparison_payload["total_records"] == 0


def test_explore_day_trading_candidates_can_target_compression_retest_breakout_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_compression_retest_breakout_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "compression_retest_breakout"
    assert candidate.candidate_path.exists()
    assert candidate.review_packet_path.exists()


def test_explore_day_trading_candidates_can_target_high_vol_pullback_persistence_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_high_vol_pullback_persistence_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "pullback_continuation"
    assert candidate.candidate_path.exists()
    assert candidate.review_packet_path.exists()


def test_scan_day_trading_behaviors_emits_continuation_gate_for_high_vol_pullback_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    seed_report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_high_vol_pullback_persistence_research",
    )
    reference_candidate_id = seed_report.candidates[0].candidate_id

    report = scan_day_trading_behaviors(
        settings,
        mirror_path=mirror,
        max_sources=4,
        family_filter="europe_open_high_vol_pullback_persistence_research",
        reference_candidate_id=reference_candidate_id,
    )

    assert len(report.records) >= 1
    assert len(report.records) <= len(report.screen_records)
    assert report.reference_candidate_id == reference_candidate_id
    assert report.continuation_gate is not None
    assert report.continuation_gate.reference_candidate_id == reference_candidate_id
    assert report.continuation_gate.required_trade_count >= 40
    assert report.continuation_gate.required_min_walk_forward_trade_count >= 8
    assert report.continuation_gate.decision in {"continue_refinement", "reopen_discovery"}


def test_explore_day_trading_candidates_can_target_high_vol_pullback_reset_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_high_vol_pullback_reset_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "pullback_continuation"
    assert candidate.candidate_path.exists()
    assert candidate.review_packet_path.exists()


def test_explore_day_trading_candidates_can_target_high_vol_pullback_regime_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_high_vol_pullback_regime_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "pullback_continuation"
    assert candidate.candidate_path.exists()
    assert candidate.review_packet_path.exists()


def test_scan_day_trading_behaviors_uses_cached_family_artifacts(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_high_vol_pullback_persistence_research",
    )
    before_candidates = {path.name for path in settings.paths().reports_dir.iterdir() if path.is_dir()}

    report = scan_day_trading_behaviors(
        settings,
        mirror_path=mirror,
        max_sources=4,
        family_filter="europe_open_high_vol_pullback_persistence_research",
        materialize_candidates=False,
    )

    after_candidates = {path.name for path in settings.paths().reports_dir.iterdir() if path.is_dir()}
    assert before_candidates == after_candidates
    assert len(report.records) >= 1
    assert len(report.records) <= len(report.screen_records)
    assert {record.candidate_id for record in report.records}.issubset(after_candidates)


def test_explore_day_trading_candidates_can_target_high_vol_pullback_chronology_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="europe_open_high_vol_pullback_chronology_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "pullback_continuation"
    assert candidate.candidate_path.exists()
    assert candidate.review_packet_path.exists()


def test_explore_day_trading_candidates_can_target_asia_transition_daytype_family(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    report = explore_day_trading_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=1,
        max_sources=4,
        family_filter="asia_europe_transition_daytype_reclaim_research",
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.entry_style == "drift_reclaim"
    candidate_payload = read_json(candidate.candidate_path)
    filter_rules = {item["name"]: item["rule"] for item in candidate_payload["custom_filters"]}
    assert candidate_payload["open_anchor_hour_utc"] == 6
    assert candidate_payload["overnight_allowed"] is False
    assert candidate_payload["max_hold_bars"] <= 18
    assert filter_rules["max_spread_shock_20"]
    assert filter_rules["min_range_efficiency_10"]
