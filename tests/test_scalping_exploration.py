from __future__ import annotations

from conftest import create_corpus_mirror, create_economic_calendar_csv, create_oanda_candles_json

from agentic_forex.experiments import explore_scalping_candidates
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.policy.calendar import ingest_economic_calendar


def test_explore_scalping_candidates_generates_reviewed_candidate_set(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    report = explore_scalping_candidates(
        settings,
        mirror_path=mirror,
        max_candidates=3,
        max_sources=4,
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert len(report.candidates) == 3
    if report.recommended_candidate_id is not None:
        assert report.recommended_candidate_id in {candidate.candidate_id for candidate in report.candidates}
    assert report.digest_source_count >= 1
    assert report.approved_source_ids
    assert {candidate.entry_style for candidate in report.candidates} == {
        "session_breakout",
        "volatility_breakout",
        "pullback_continuation",
    }
    for candidate in report.candidates:
        assert candidate.candidate_path.exists()
        assert candidate.spec_path.exists()
        assert candidate.backtest_summary_path.exists()
        assert candidate.stress_report_path.exists()
        assert candidate.review_packet_path.exists()
