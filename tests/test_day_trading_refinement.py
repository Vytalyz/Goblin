from __future__ import annotations

from conftest import create_economic_calendar_csv, create_oanda_candles_json

from agentic_forex.experiments import refine_day_trading_target
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.policy.calendar import ingest_economic_calendar
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import CandidateDraft, MarketContextSummary, StrategySpec


def test_refine_day_trading_target_generates_variants_and_report(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-TARGET",
        family="day_trading",
        title="Europe Compression Break Day Trade",
        thesis="Broad Europe compression-break day trade seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Broad Europe compression breakouts need a narrower release pocket and tighter quality gates.",
        market_context=MarketContextSummary(
            session_focus="europe_compression_expansion",
            volatility_preference="low_to_moderate",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[6, 7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Require a compressed Europe-session range before the break.",
        entry_summary="Enter on a compression break when momentum, z-score, and range position all align.",
        exit_summary="Exit via fixed stop, target, or 90-bar timeout.",
        risk_summary="Longer intraday hold that still needs better cost discipline.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="compression_breakout",
        holding_bars=90,
        signal_threshold=1.15,
        stop_loss_pips=7.5,
        take_profit_pips=12.5,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_compression_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.target_candidate_id == target.candidate_id
    assert report.challenger_family == "europe_open_compression_research"
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}
    assert len(report.variants) == 5
    for variant in report.variants:
        assert variant.candidate_path.exists()
        assert variant.spec_path.exists()
        assert variant.review_packet_path.exists()


def test_refine_day_trading_target_writes_overridden_family_to_specs(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-TARGET-FAMILY",
        family="day_trading",
        title="Europe Compression Break Day Trade",
        thesis="Broad Europe compression-break day trade seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Broad Europe compression breakouts need a narrower release pocket and tighter quality gates.",
        market_context=MarketContextSummary(
            session_focus="europe_compression_expansion",
            volatility_preference="low_to_moderate",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[6, 7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Require a compressed Europe-session range before the break.",
        entry_summary="Enter on a compression break when momentum, z-score, and range position all align.",
        exit_summary="Exit via fixed stop, target, or 90-bar timeout.",
        risk_summary="Longer intraday hold that still needs better cost discipline.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="compression_breakout",
        holding_bars=90,
        signal_threshold=1.15,
        stop_loss_pips=7.5,
        take_profit_pips=12.5,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="gap_day_trading_compression_research",
    )

    first_variant = report.variants[0]
    spec = StrategySpec.model_validate(read_json(first_variant.spec_path))
    assert spec.family == "gap_day_trading_compression_research"
    assert spec.news_policy.enabled is True


def test_refine_day_trading_target_supports_range_reclaim(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-RECLAIM",
        family="day_trading",
        title="London Range Reclaim Day Trade",
        thesis="Broad London reclaim day trade seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Broad London reclaims need a tighter time window and weaker trend context removed.",
        market_context=MarketContextSummary(
            session_focus="london_range_reclaim",
            volatility_preference="moderate",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[6, 7, 8, 9, 10, 11, 12, 13],
        ),
        setup_summary="Look for stretched movement beyond the range, then require reclaim back into it.",
        entry_summary="Enter on a reclaim when the extension and reversal recovery align back into the range.",
        exit_summary="Exit via fixed stop, target, or 72-bar timeout.",
        risk_summary="Mean-reversion day trade that needs tighter timing and context filtering.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="range_reclaim",
        holding_bars=72,
        signal_threshold=1.1,
        stop_loss_pips=7.0,
        take_profit_pips=11.0,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_reclaim_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.challenger_family == "europe_open_reclaim_research"
    assert len(report.variants) == 5
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}


def test_refine_day_trading_target_supports_drift_reclaim(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-DRIFT-RECLAIM",
        family="asia_europe_transition_reclaim_research",
        title="Asia-Europe Transition Reclaim Seed",
        thesis="High-volatility Asia-to-Europe reclaim seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis=(
            "Asia-to-Europe transition reclaim should improve by removing trend-context contamination, "
            "tightening the handoff window, and cautiously restoring density only where high-volatility "
            "transition conditions persist."
        ),
        market_context=MarketContextSummary(
            session_focus="asia_europe_transition_reclaim",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[5, 6, 7],
        ),
        setup_summary="Require a high-volatility overnight drift stretch before reclaim back through the transition handoff.",
        entry_summary="Enter on reclaim once drift extension, reclaim confirmation, and reversal recovery align.",
        exit_summary="Exit via fixed stop, target, or 16-bar timeout.",
        risk_summary="Transition-state reclaim seed that needs more density without losing cost-adjusted robustness.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="drift_reclaim",
        holding_bars=16,
        signal_threshold=0.90,
        stop_loss_pips=5.2,
        take_profit_pips=7.2,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "daytype_spread_guard_density"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="asia_europe_transition_reclaim_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.challenger_family == "asia_europe_transition_reclaim_research"
    assert len(report.variants) == 3
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}


def test_refine_day_trading_target_uses_drift_reclaim_follow_on_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-DRIFT-RECLAIM-FOLLOW",
        family="asia_europe_transition_reclaim_research",
        title="Europe Handoff Reclaim Seed",
        thesis="First-wave Asia-Europe transition reclaim refinement seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis=(
            "The revived Asia-Europe handoff reclaim should improve by concentrating on the supported 07:00-08:59 UTC block "
            "and testing whether later-handoff decay can restore density without losing stress survival."
        ),
        market_context=MarketContextSummary(
            session_focus="europe_handoff_reclaim",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[6, 7, 8],
        ),
        setup_summary="Keep the reclaim anchored to the later handoff where the Europe side of the transition was already stronger.",
        entry_summary="Enter on a Europe-handoff reclaim when the overnight drift is stretched and the later transition reversal confirms.",
        exit_summary="Exit via fixed stop, target, or 14-bar timeout.",
        risk_summary="Later-handoff transition reclaim seed.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="drift_reclaim",
        holding_bars=14,
        signal_threshold=0.90,
        stop_loss_pips=5.0,
        take_profit_pips=6.9,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "europe_handoff_reclaim"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="asia_europe_transition_reclaim_research",
    )

    variant_labels = {variant.variant_label for variant in report.variants}
    assert variant_labels == {
        "daytype_spread_guard",
        "daytype_quality_soft",
        "late_decay_cost_guard",
        "late_decay_density_restoration",
        "late_decay_short_hold",
        "late_decay_europe_bias",
    }


def test_refine_day_trading_target_uses_daytype_spread_guard_follow_on_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-DRIFT-RECLAIM-DAYTYPE",
        family="asia_europe_transition_reclaim_research",
        title="Day-Type Spread-Guard Reclaim Seed",
        thesis="Second-wave Asia-Europe transition reclaim refinement seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis=(
            "The spread-guard transition reclaim should improve by softening the day-type filters just enough to restore density "
            "without giving back the later-handoff quality improvement."
        ),
        market_context=MarketContextSummary(
            session_focus="asia_europe_daytype_spread_guard_reclaim",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[6, 7, 8],
        ),
        setup_summary="Keep the later handoff reclaim, but only on spread-controlled transition days.",
        entry_summary="Enter on a spread-guard reclaim when the overnight drift is stretched and the later transition reversal confirms.",
        exit_summary="Exit via fixed stop, target, or 14-bar timeout.",
        risk_summary="Soft day-type guarded transition reclaim seed.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="drift_reclaim",
        holding_bars=14,
        signal_threshold=0.89,
        stop_loss_pips=4.9,
        take_profit_pips=6.8,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "daytype_spread_guard"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="asia_europe_transition_reclaim_research",
    )

    variant_labels = {variant.variant_label for variant in report.variants}
    assert variant_labels == {
        "daytype_spread_guard_density",
        "daytype_spread_guard_late_core",
        "daytype_spread_guard_short_hold",
    }


def test_refine_day_trading_target_uses_daytype_spread_guard_density_follow_on_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-DRIFT-RECLAIM-DENSITY",
        family="asia_europe_transition_reclaim_research",
        title="Day-Type Spread-Guard Density Seed",
        thesis="Third-wave Asia-Europe transition reclaim refinement seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis=(
            "The revived Asia-Europe handoff reclaim should improve by concentrating on the supported "
            "07:00-08:59 UTC block and testing whether weak-window density can recover through bounded "
            "phase-aware day-type variants."
        ),
        market_context=MarketContextSummary(
            session_focus="asia_europe_daytype_spread_guard_density_reclaim",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[6, 7, 8],
        ),
        setup_summary="Require a high-volatility overnight drift stretch before reclaim back through the transition handoff.",
        entry_summary="Enter on reclaim once drift extension, reclaim confirmation, and reversal recovery align.",
        exit_summary="Exit via fixed stop, target, or 16-bar timeout.",
        risk_summary="Transition-state reclaim refinement that needs more weak-window density without losing cost-adjusted robustness.",
        notes=["Refinement label: daytype_spread_guard_density."],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="drift_reclaim",
        holding_bars=16,
        signal_threshold=0.86,
        stop_loss_pips=5.0,
        take_profit_pips=7.0,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "daytype_spread_guard_density"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="asia_europe_transition_reclaim_research",
    )

    variant_labels = {variant.variant_label for variant in report.variants}
    assert variant_labels == {
        "daytype_density_handoff_bridge",
        "daytype_density_early_follow",
        "daytype_density_late_decay",
    }


def test_refine_day_trading_target_uses_range_reclaim_follow_on_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-RECLAIM-FOLLOW",
        family="europe_open_reclaim_research",
        title="Early London Buffered Reclaim",
        thesis="First-wave reclaim refinement seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="The buffered early-London reclaim can improve by removing the weak bridging hour.",
        market_context=MarketContextSummary(
            session_focus="early_london_buffered_reclaim",
            volatility_preference="moderate",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[7, 8, 9, 10],
        ),
        setup_summary="Keep the reclaim centered on the early London window with the trend-context slice removed.",
        entry_summary="Enter on an early-London reclaim when extension and reclaim-zone recovery align.",
        exit_summary="Exit via fixed stop, target, or 28-bar timeout.",
        risk_summary="Buffered early-London reclaim seed.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="range_reclaim",
        holding_bars=28,
        signal_threshold=1.04,
        stop_loss_pips=6.0,
        take_profit_pips=8.6,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "early_london_buffered"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_reclaim_research",
    )

    variant_labels = {variant.variant_label for variant in report.variants}
    assert variant_labels == {
        "dual_pocket_buffered",
        "dual_pocket_cost_guard",
        "dual_pocket_mean_reversion",
        "open_plus_release_reclaim",
    }


def test_refine_day_trading_target_supports_failed_break_fade(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-FAILED-BREAK",
        family="europe_open_failed_break_research",
        title="Europe Failed Break Fade Day Trade",
        thesis="Broad Europe failed-break fade seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Europe-open failed breaks may improve when medium-volatility reversal pockets are isolated.",
        market_context=MarketContextSummary(
            session_focus="europe_failed_break_reversal",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Require a failed directional break first, then wait for reversal pressure.",
        entry_summary="Enter on a failed break fade when extension is stretched and reversal pressure points back into range.",
        exit_summary="Exit via fixed stop, target, or 54-bar timeout.",
        risk_summary="Europe-session fade that still needs tighter context and cost control.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="failed_break_fade",
        holding_bars=54,
        signal_threshold=1.05,
        stop_loss_pips=6.2,
        take_profit_pips=9.8,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_failed_break_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.challenger_family == "europe_open_failed_break_research"
    assert len(report.variants) == 4
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}


def test_refine_day_trading_target_uses_failed_break_follow_on_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-FAILED-BREAK-FOLLOW",
        family="europe_open_failed_break_research",
        title="Open Release Cost-Guard Failed Break Fade",
        thesis="First-wave failed-break refinement seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="The cost-guard failed-break branch may improve by restoring density without reopening the weak base profile.",
        market_context=MarketContextSummary(
            session_focus="europe_failed_break_cost_guard",
            volatility_preference="medium",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[7, 8, 9],
        ),
        setup_summary="Trade only the open-release failed-break reversals with tighter cost control.",
        entry_summary="Enter on a cost-guard failed break fade when the exhaustion move is stretched and reversal pressure is present.",
        exit_summary="Exit via fixed stop, target, or 38-bar timeout.",
        risk_summary="Open-release failed-break follow-on seed.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="failed_break_fade",
        holding_bars=38,
        signal_threshold=1.12,
        stop_loss_pips=5.6,
        take_profit_pips=8.0,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "open_release_cost_guard"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_failed_break_research",
    )

    variant_labels = {variant.variant_label for variant in report.variants}
    assert variant_labels == {
        "open_release_balanced_density",
        "open_release_short_hold_guard",
        "release_plus_late_medium",
        "open_release_dual_vol_buffered",
    }


def test_refine_day_trading_target_uses_pullback_follow_on_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-PULLBACK-FOLLOW",
        family="europe_open_pullback_continuation_research",
        title="Balanced Pre-Overlap Pullback Continuation",
        thesis="First-wave pullback refinement seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="The balanced pullback branch may improve by isolating the stronger high-volatility continuation pocket and shortening cost exposure.",
        market_context=MarketContextSummary(
            session_focus="balanced_pre_overlap_pullback_continuation",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[8, 9, 10, 11, 12],
        ),
        setup_summary="Trade balanced pre-overlap pullbacks only when the initial release is already established and the pullback remains shallow.",
        entry_summary="Enter on a balanced pullback continuation when trend direction remains active and the recovery bar resumes the move.",
        exit_summary="Exit via fixed stop, target, or 28-bar timeout.",
        risk_summary="Balanced pullback follow-on seed.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="pullback_continuation",
        holding_bars=28,
        signal_threshold=0.90,
        stop_loss_pips=5.7,
        take_profit_pips=8.4,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "balanced_pre_overlap_pullback"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_pullback_continuation_research",
    )

    variant_labels = {variant.variant_label for variant in report.variants}
    assert variant_labels == {
        "balanced_high_vol_pullback",
        "open_plus_release_high_vol_pullback",
        "late_window_high_vol_pullback",
        "balanced_short_hold_cost_guard_pullback",
    }


def test_refine_day_trading_target_uses_pullback_density_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-PULLBACK-DENSITY",
        family="europe_open_pullback_continuation_research",
        title="Late-Window High-Vol Pullback Continuation",
        thesis="Second-wave pullback density-restoration seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="The late-window high-volatility pullback branch may restore throughput by widening only the session and pullback band, not by reopening the weak medium-volatility base profile.",
        market_context=MarketContextSummary(
            session_focus="late_window_high_vol_pullback_continuation",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[9, 10, 11, 12],
        ),
        setup_summary="Trade late Europe-window high-volatility pullbacks only when the continuation leg remains active and the pullback stays tight.",
        entry_summary="Enter on a late-window high-volatility pullback continuation when the recovery bar resumes the move.",
        exit_summary="Exit via fixed stop, target, or 22-bar timeout.",
        risk_summary="Late-window high-volatility density-restoration seed.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="pullback_continuation",
        holding_bars=22,
        signal_threshold=0.94,
        stop_loss_pips=5.2,
        take_profit_pips=7.4,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "late_window_high_vol_pullback"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_pullback_continuation_research",
    )

    variant_labels = {variant.variant_label for variant in report.variants}
    assert variant_labels == {
        "full_pre_overlap_high_vol_pullback",
        "late_window_high_vol_buffered",
        "late_window_dual_vol_guarded_pullback",
        "open_to_late_high_vol_short_hold",
    }


def test_refine_day_trading_target_supports_session_breakout(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-BREAKOUT",
        family="europe_open_breakout_research",
        title="Europe Selective Breakout Day Trade",
        thesis="Broad Europe-open breakout seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Europe-open balance releases may improve when the weaker mean-reversion context is removed.",
        market_context=MarketContextSummary(
            session_focus="europe_open_selective_breakout",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Require a real Europe release from balance first.",
        entry_summary="Enter on a Europe-open breakout when momentum and range position confirm the release.",
        exit_summary="Exit via fixed stop, target, or 42-bar timeout.",
        risk_summary="Europe-open breakout seed that still needs tighter cost and context control.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="session_breakout",
        holding_bars=42,
        signal_threshold=0.98,
        stop_loss_pips=6.0,
        take_profit_pips=8.8,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_breakout_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.challenger_family == "europe_open_breakout_research"
    assert len(report.variants) == 4
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}


def test_refine_day_trading_target_uses_pullback_regime_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-PULLBACK-REGIME",
        family="europe_open_high_vol_pullback_regime_research",
        title="Europe High-Vol Pullback Regime Quality",
        thesis="Regime-quality pullback refinement seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="The regime-quality pullback clue may restore density if the realized-activity floor is relaxed without reopening weak continuation states.",
        market_context=MarketContextSummary(
            session_focus="core_pre_overlap_high_vol_pullback_regime_quality",
            volatility_preference="high_to_persistent",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[8, 9, 10, 11, 12],
        ),
        setup_summary="Trade regime-quality pullbacks when the release remains active and the reset stays controlled.",
        entry_summary="Enter on a regime-quality pullback continuation when the recovery resumes on the correct side of the mean.",
        exit_summary="Exit via fixed stop, target, or 22-bar timeout.",
        risk_summary="Regime-quality pullback refinement seed.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="pullback_continuation",
        holding_bars=22,
        signal_threshold=0.89,
        stop_loss_pips=5.2,
        take_profit_pips=7.6,
    )
    target_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(target_path, target.model_dump(mode="json"))
    spec_payload = compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    target_spec = StrategySpec.model_validate(spec_payload)
    target_spec = target_spec.model_copy(
        update={
            "family": "europe_open_high_vol_pullback_regime_research",
            "variant_name": "base",
        }
    )
    write_json(
        settings.paths().reports_dir / target.candidate_id / "strategy_spec.json", target_spec.model_dump(mode="json")
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_high_vol_pullback_regime_research",
    )

    labels = {variant.variant_label for variant in report.variants}
    assert {
        "bridge_relaxed_regime_quality",
        "core_relaxed_regime_quality",
        "persistent_reset_density",
        "short_hold_density_regime_quality",
    }.issubset(labels)


def test_refine_day_trading_target_supports_balance_area_breakout(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-BALANCE",
        family="europe_open_balance_breakout_research",
        title="Europe Balance Breakout Day Trade",
        thesis="Broad Europe-open balance-release breakout seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Europe-open balance releases may improve when weaker mean-reversion states are removed.",
        market_context=MarketContextSummary(
            session_focus="europe_balance_release_breakout",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11],
        ),
        setup_summary="Require a tighter intraday balance first.",
        entry_summary="Enter on a balance-area breakout when directional release and range position confirm the move.",
        exit_summary="Exit via fixed stop, target, or 30-bar timeout.",
        risk_summary="Selective Europe-open breakout seed that still needs tighter cost and context control.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="balance_area_breakout",
        holding_bars=30,
        signal_threshold=0.86,
        stop_loss_pips=5.6,
        take_profit_pips=8.0,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_balance_breakout_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.challenger_family == "europe_open_balance_breakout_research"
    assert len(report.variants) == 4
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}


def test_refine_day_trading_target_supports_compression_reversion(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-COMPRESSION-REV",
        family="europe_open_compression_reversion_research",
        title="Europe Compression Reversion Day Trade",
        thesis="Broad Europe compression reversion seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Compressed Europe-session extremes may mean-revert better than breakout-style release families.",
        market_context=MarketContextSummary(
            session_focus="europe_core_compression_reversion",
            volatility_preference="low_to_moderate",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11],
        ),
        setup_summary="Require a tight Europe balance first, then wait for an extreme to start snapping back.",
        entry_summary="Enter on a compression reversion when the extreme extension starts reclaiming into the local range.",
        exit_summary="Exit via fixed stop, target, or 36-bar timeout.",
        risk_summary="Compression snapback seed that must stay orthogonal to breakout and failed-break logic.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        custom_filters=[
            {"name": "max_range_width_10_pips", "rule": "7.4"},
            {"name": "reclaim_range_position_floor", "rule": "0.20"},
            {"name": "reclaim_range_position_ceiling", "rule": "0.42"},
            {"name": "reclaim_momentum_ceiling", "rule": "3.0"},
            {"name": "require_reversal_ret_1", "rule": "true"},
        ],
        enable_news_blackout=True,
        entry_style="compression_reversion",
        holding_bars=36,
        signal_threshold=1.02,
        stop_loss_pips=5.8,
        take_profit_pips=8.0,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_compression_reversion_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.challenger_family == "europe_open_compression_reversion_research"
    assert len(report.variants) == 4
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}


def test_refine_day_trading_target_uses_balance_area_breakout_follow_on_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-BALANCE-FOLLOW",
        family="europe_open_balance_breakout_research",
        title="High-Vol Core Release Balance Breakout",
        thesis="First-wave balance-breakout refinement seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="The high-volatility core balance release may improve with shorter holds and tighter cost control.",
        market_context=MarketContextSummary(
            session_focus="high_vol_core_balance_release",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[8, 9],
        ),
        setup_summary="Trade only the core high-volatility balance release.",
        entry_summary="Enter on a high-volatility balance breakout when the range is tight and release direction is strong.",
        exit_summary="Exit via fixed stop, target, or 20-bar timeout.",
        risk_summary="High-volatility core-release seed.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="balance_area_breakout",
        holding_bars=20,
        signal_threshold=0.96,
        stop_loss_pips=5.0,
        take_profit_pips=7.2,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "high_vol_core_release"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_balance_breakout_research",
    )

    variant_labels = {variant.variant_label for variant in report.variants}
    assert variant_labels == {
        "high_vol_dual_hour_buffered",
        "open_release_high_vol_buffered",
        "high_vol_release_short_hold",
        "core_release_buffered",
    }


def test_refine_day_trading_target_supports_trend_retest(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-TREND-RETEST",
        family="europe_open_trend_retest_research",
        title="Europe Trend Retest Day Trade",
        thesis="Broad Europe-open retest continuation seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Europe-open continuation may improve when the first impulse is avoided and entries wait for a controlled retest.",
        market_context=MarketContextSummary(
            session_focus="europe_open_trend_retest",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[8, 9, 10, 11, 12],
        ),
        setup_summary="Require a directional Europe release first, then wait for a controlled retest.",
        entry_summary="Enter on a trend retest when momentum remains aligned and the recovery bar resumes the move.",
        exit_summary="Exit via fixed stop, target, or 30-bar timeout.",
        risk_summary="Europe-open retest continuation seed that should stay distinct from breakout chase and reclaim logic.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="trend_retest",
        holding_bars=30,
        signal_threshold=0.92,
        stop_loss_pips=5.8,
        take_profit_pips=8.4,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_trend_retest_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.challenger_family == "europe_open_trend_retest_research"
    assert len(report.variants) == 4
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}


def test_refine_day_trading_target_supports_volatility_retest_breakout(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-RETEST-BREAKOUT",
        family="europe_open_retest_breakout_research",
        title="Europe Retest Breakout Day Trade",
        thesis="Broad Europe-open retest breakout seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Europe-open continuation may become practical when the initial release is followed by a controlled retest and resumed breakout.",
        market_context=MarketContextSummary(
            session_focus="europe_open_retest_breakout",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[8, 9, 10, 11, 12],
        ),
        setup_summary="Require a directional Europe release first, then wait for a controlled retest breakout.",
        entry_summary="Enter on a retest breakout when volatility remains active and the continuation bar resumes the move.",
        exit_summary="Exit via fixed stop, target, or 28-bar timeout.",
        risk_summary="Europe-open retest breakout seed intended to lift throughput relative to strict trend-retest logic.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="volatility_retest_breakout",
        holding_bars=28,
        signal_threshold=0.94,
        stop_loss_pips=5.8,
        take_profit_pips=8.6,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_retest_breakout_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.challenger_family == "europe_open_retest_breakout_research"
    assert len(report.variants) == 4
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}


def test_refine_day_trading_target_supports_pullback_continuation(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    target = CandidateDraft(
        candidate_id="AF-CAND-DAY-PULLBACK-CONT",
        family="europe_open_pullback_continuation_research",
        title="Europe Pullback Continuation Day Trade",
        thesis="Broad Europe-open pullback continuation seed.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Europe-open continuation may become practical when the initial release is followed by a shallow pullback that resumes without requiring a very strict retest shape.",
        market_context=MarketContextSummary(
            session_focus="europe_open_pullback_continuation",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[8, 9, 10, 11, 12],
        ),
        setup_summary="Require a directional Europe release first, then wait for a shallow continuation pullback.",
        entry_summary="Enter on a pullback continuation when trend remains aligned and the recovery bar resumes the move.",
        exit_summary="Exit via fixed stop, target, or 30-bar timeout.",
        risk_summary="Europe-open pullback continuation seed intended to sit between strict retests and broad breakout releases.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="pullback_continuation",
        holding_bars=30,
        signal_threshold=0.92,
        stop_loss_pips=5.8,
        take_profit_pips=8.6,
    )
    candidate_path = settings.paths().reports_dir / target.candidate_id / "candidate.json"
    write_json(candidate_path, target.model_dump(mode="json"))
    compile_strategy_spec_tool(
        payload=target.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    report = refine_day_trading_target(
        settings,
        target_candidate_id=target.candidate_id,
        family_override="europe_open_pullback_continuation_research",
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.challenger_family == "europe_open_pullback_continuation_research"
    assert len(report.variants) == 4
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}
