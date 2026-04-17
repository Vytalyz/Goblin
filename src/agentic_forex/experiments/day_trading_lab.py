from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from agentic_forex.config import Settings
from agentic_forex.corpus.catalog import build_digest, catalog_corpus
from agentic_forex.experiments.models import (
    DayTradingBehaviorScanRecord,
    DayTradingBehaviorScanReport,
    DayTradingContinuationGate,
    DayTradingExplorationCandidate,
    DayTradingExplorationReport,
    DayTradingHypothesisScreenRecord,
)
from agentic_forex.experiments.service import compare_experiments
from agentic_forex.features.service import build_features
from agentic_forex.llm import MockLLMClient
from agentic_forex.nodes import build_tool_registry
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.runtime import ReadPolicy, WorkflowEngine
from agentic_forex.utils.ids import next_candidate_id
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows import WorkflowRepository
from agentic_forex.workflows.contracts import CandidateDraft, MarketContextSummary, MarketRationale, ReviewPacket, StrategySpec


def scan_day_trading_behaviors(
    settings: Settings,
    *,
    mirror_path: Path | None = None,
    max_sources: int = 5,
    family_filter: str | None = None,
    reference_candidate_id: str | None = None,
    materialize_candidates: bool = False,
    max_materialized: int | None = None,
) -> DayTradingBehaviorScanReport:
    digest = _load_day_trading_digest(settings, mirror_path=mirror_path, max_sources=max_sources)
    templates = _day_trading_templates(family_filter=family_filter)
    cached_artifacts = _load_cached_day_trading_artifacts(settings, family_filter=family_filter)
    feature_frame = _load_day_trading_pretest_frame(settings)
    review_engine = None
    review_workflow = None

    screen_records: list[DayTradingHypothesisScreenRecord] = []
    candidate_templates: list[tuple[float, dict[str, object], str]] = []
    for template in templates:
        prior = _book_prior_assessment(template, digest)
        enriched_template = dict(template)
        enriched_template.update(prior)
        screen_record = _screen_day_trading_template(
            enriched_template,
            feature_frame=feature_frame,
        )
        screen_records.append(screen_record)
        if screen_record.pretest_eligible:
            candidate_templates.append((screen_record.pretest_score, enriched_template, screen_record.title))

    candidate_templates.sort(key=lambda item: item[0], reverse=True)
    materialization_budget = (
        len(candidate_templates)
        if family_filter and max_materialized is None
        else max(1, max_materialized or 4)
    )
    selected_templates = [template for _, template, _ in candidate_templates[:materialization_budget]]

    records: list[DayTradingBehaviorScanRecord] = []
    for template in selected_templates:
        cache_key = (
            str(template.get("family") or "day_trading"),
            str(template.get("title") or ""),
            str(template.get("entry_style") or ""),
        )
        artifact = None if materialize_candidates else cached_artifacts.get(cache_key)
        if artifact is None:
            if review_engine is None or review_workflow is None:
                review_engine, review_workflow = _build_review_runner(settings)
            candidate = _draft_from_template(
                template,
                digest,
                settings,
                index=len(records),
            )
            artifact = _materialize_candidate(candidate, settings, review_engine=review_engine, review_workflow=review_workflow)
        records.append(_scan_record_from_artifact(artifact))

    ordered = sorted(records, key=lambda item: item.scan_score, reverse=True)
    eligible_records = [record for record in ordered if record.comparison_eligible]
    comparison_candidate_ids = [record.candidate_id for record in eligible_records]
    comparison = compare_experiments(
        settings,
        family=family_filter,
        candidate_ids=comparison_candidate_ids if comparison_candidate_ids else [],
    )
    continuation_gate = _evaluate_day_trading_continuation_gate(
        settings,
        ordered,
        reference_candidate_id=reference_candidate_id,
    )
    report_path = _scan_report_path(settings)
    report = DayTradingBehaviorScanReport(
        digest_source_count=len(digest.source_citations),
        approved_source_ids=digest.approved_source_ids,
        family_filter=family_filter,
        comparison_report_path=comparison.report_path,
        screened_template_count=len(screen_records),
        materialized_candidate_count=len(ordered),
        recommended_candidate_id=eligible_records[0].candidate_id if eligible_records else None,
        reference_candidate_id=reference_candidate_id,
        continuation_gate=continuation_gate,
        report_path=report_path,
        screen_records=sorted(screen_records, key=lambda item: item.pretest_score, reverse=True),
        records=ordered,
    )
    write_json(report_path, report.model_dump(mode="json"))
    return report


def explore_day_trading_candidates(
    settings: Settings,
    *,
    mirror_path: Path | None = None,
    max_candidates: int = 3,
    max_sources: int = 5,
    family_filter: str | None = None,
    reference_candidate_id: str | None = None,
    max_materialized: int | None = None,
) -> DayTradingExplorationReport:
    resolved_max_materialized = (
        max_materialized
        if max_materialized is not None
        else (None if family_filter else max(max_candidates, 4))
    )
    scan = scan_day_trading_behaviors(
        settings,
        mirror_path=mirror_path,
        max_sources=max_sources,
        family_filter=family_filter,
        reference_candidate_id=reference_candidate_id,
        materialize_candidates=True,
        max_materialized=resolved_max_materialized,
    )
    eligible_records = [record for record in scan.records if record.comparison_eligible]
    selected_pool = eligible_records if eligible_records else scan.records
    selected = selected_pool[: max(max_candidates, 0)]
    report_path = _report_path(settings)
    report = DayTradingExplorationReport(
        digest_source_count=scan.digest_source_count,
        approved_source_ids=list(scan.approved_source_ids),
        scan_report_path=scan.report_path,
        comparison_report_path=scan.comparison_report_path,
        recommended_candidate_id=selected[0].candidate_id if selected and selected[0].comparison_eligible else None,
        reference_candidate_id=reference_candidate_id,
        continuation_gate=scan.continuation_gate,
        report_path=report_path,
        candidates=[
            DayTradingExplorationCandidate(
                candidate_id=record.candidate_id,
                title=record.title,
                entry_style=record.entry_style,
                thesis=_load_candidate(settings, record.candidate_id).thesis,
                candidate_path=record.candidate_path,
                spec_path=record.spec_path,
                backtest_summary_path=record.backtest_summary_path,
                stress_report_path=record.stress_report_path,
                review_packet_path=record.review_packet_path,
            )
            for record in selected
        ],
    )
    write_json(report_path, report.model_dump(mode="json"))
    return report


def _load_day_trading_digest(settings: Settings, *, mirror_path: Path | None, max_sources: int):
    allowed_roots = [mirror_path] if mirror_path else []
    allowed_roots.extend(_supplemental_corpus_roots(settings))
    read_policy = ReadPolicy(project_root=settings.project_root, allowed_external_roots=allowed_roots)
    if not settings.catalog_path.exists() or (mirror_path is not None and _catalog_needs_refresh(settings)):
        if mirror_path is None:
            raise ValueError("--mirror-path is required when the corpus catalog does not exist yet.")
        catalog_corpus(mirror_path, settings, read_policy)
    return build_digest(family="day_trading", settings=settings, max_sources=max_sources)


def _supplemental_corpus_roots(settings: Settings) -> list[Path]:
    roots: list[Path] = []
    for configured_path in settings.data.supplemental_source_paths:
        source_path = Path(configured_path)
        if source_path.exists():
            roots.append(source_path.parent)
    return roots


def _catalog_needs_refresh(settings: Settings) -> bool:
    if not settings.catalog_path.exists():
        return True
    catalog_payload = read_json(settings.catalog_path)
    catalog_entries = list(catalog_payload.get("entries") or [])
    existing_paths = {
        str(Path(str(entry.get("path") or "")).resolve())
        for entry in catalog_entries
        if entry.get("path")
    }
    expected_paths = {
        str(Path(configured_path).resolve())
        for configured_path in settings.data.supplemental_source_paths
        if Path(configured_path).exists()
    }
    return not expected_paths.issubset(existing_paths)


def _book_prior_assessment(template: dict[str, object], digest) -> dict[str, object]:
    claim_map = {claim.claim_type: claim for claim in digest.strategy_claims}
    family = str(template.get("family") or "day_trading")
    entry_style = str(template.get("entry_style") or "")
    allowed_hours = [int(hour) for hour in list(template.get("allowed_hours_utc") or [])]
    open_anchor_hour_utc = int(template.get("open_anchor_hour_utc") or (min(allowed_hours) if allowed_hours else 7))
    max_hold_bars = int(template.get("max_hold_bars") or template.get("holding_bars") or 0)
    overnight_allowed = bool(template.get("overnight_allowed", False))
    risk_filter_profile = str(template.get("risk_filter_profile") or "spread_shock_realized_vol_calendar_blackout")
    geometry_knob_count = len(dict(template.get("custom_filters") or {}))
    latest_hour = max(allowed_hours, default=open_anchor_hour_utc)
    score = 0.0
    veto_reasons: list[str] = []

    if "session_anchor" in claim_map:
        score += 0.35 if open_anchor_hour_utc == 7 else 0.10
    if "holding_horizon" in claim_map:
        if max_hold_bars <= 18 and latest_hour <= open_anchor_hour_utc + 2:
            score += 0.25
        elif latest_hour > open_anchor_hour_utc + 2 or max_hold_bars > 20:
            score -= 0.15
            veto_reasons.append("late_morning_decay_without_density_support")
    if "overnight_rule" in claim_map:
        if overnight_allowed:
            veto_reasons.append("overnight_momentum_carry_disallowed")
            score -= 0.25
        else:
            score += 0.15
    if "risk_day_filter" in claim_map and risk_filter_profile:
        score += 0.15
    if any(claim_type in claim_map for claim_type in ("momentum_event_decay", "anti_pattern")):
        if family == "europe_open_release_persistence_research" or entry_style == "volatility_expansion":
            veto_reasons.append("eurusd_release_persistence_veto")
            score -= 0.40
        if latest_hour > open_anchor_hour_utc + 2 or max_hold_bars > 24:
            veto_reasons.append("late_morning_decay_without_density_support")
            score -= 0.15
    if geometry_knob_count > 8:
        veto_reasons.append("too_many_geometry_knobs")
        score -= 0.10
    if family in _default_open_anchor_families():
        score += 0.15
    return {
        "book_alignment_score": round(score, 6),
        "book_veto_reasons": list(dict.fromkeys(veto_reasons)),
        "open_anchor_hour_utc": open_anchor_hour_utc,
        "max_hold_bars": max_hold_bars,
        "overnight_allowed": overnight_allowed,
        "risk_filter_profile": risk_filter_profile,
    }


def _research_dataset_path(settings: Settings) -> Path:
    return settings.paths().normalized_research_dir / (
        f"{settings.data.instrument.lower()}_{settings.data.execution_granularity.lower()}.parquet"
    )


def _load_day_trading_pretest_frame(settings: Settings) -> pd.DataFrame:
    dataset_path = _research_dataset_path(settings)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Research dataset not found for day-trading pretest: {dataset_path}")
    frame = pd.read_parquet(dataset_path)
    feature_frame = build_features(frame)
    timestamps = pd.to_datetime(feature_frame["timestamp_utc"], utc=True)
    feature_frame["trade_date"] = timestamps.dt.floor("D")
    return feature_frame


def _screen_day_trading_template(
    template: dict[str, object],
    *,
    feature_frame: pd.DataFrame,
) -> DayTradingHypothesisScreenRecord:
    family = str(template.get("family") or "day_trading")
    entry_style = str(template.get("entry_style") or "")
    title = str(template.get("title") or family)
    allowed_hours = [int(hour) for hour in list(template.get("allowed_hours_utc") or [])]
    open_anchor_hour_utc = int(template.get("open_anchor_hour_utc") or (min(allowed_hours) if allowed_hours else 7))
    max_hold_bars = int(template.get("max_hold_bars") or template.get("holding_bars") or 0)
    overnight_allowed = bool(template.get("overnight_allowed", False))
    risk_filter_profile = str(template.get("risk_filter_profile") or "spread_shock_realized_vol_calendar_blackout")
    book_alignment_score = float(template.get("book_alignment_score") or 0.0)
    book_veto_reasons = list(template.get("book_veto_reasons") or [])
    hard_veto = next(
        (
            reason
            for reason in book_veto_reasons
            if reason in {"eurusd_release_persistence_veto", "overnight_momentum_carry_disallowed"}
        ),
        None,
    )
    if hard_veto is not None:
        return DayTradingHypothesisScreenRecord(
            family=family,
            entry_style=entry_style,
            title=title,
            pretest_score=-100.0 + (book_alignment_score * 10.0),
            pretest_eligible=False,
            pretest_reason=f"book_veto:{hard_veto}",
            book_alignment_score=book_alignment_score,
            book_veto_reasons=book_veto_reasons,
            open_anchor_hour_utc=open_anchor_hour_utc,
            max_hold_bars=max_hold_bars,
            overnight_allowed=overnight_allowed,
            risk_filter_profile=risk_filter_profile,
        )

    scoped = feature_frame.copy()
    if allowed_hours:
        scoped = scoped.loc[scoped["hour"].isin(allowed_hours)]
    if scoped.empty:
        return DayTradingHypothesisScreenRecord(
            family=family,
            entry_style=entry_style,
            title=title,
            pretest_score=-50.0,
            pretest_eligible=False,
            pretest_reason="no_rows_in_allowed_hours",
            book_alignment_score=book_alignment_score,
            book_veto_reasons=book_veto_reasons,
            open_anchor_hour_utc=open_anchor_hour_utc,
            max_hold_bars=max_hold_bars,
            overnight_allowed=overnight_allowed,
            risk_filter_profile=risk_filter_profile,
        )

    qualifying = scoped.loc[_template_pretest_mask(scoped, template, open_anchor_hour_utc=open_anchor_hour_utc)]
    day_counts = qualifying.groupby("trade_date").size() if not qualifying.empty else pd.Series(dtype="int64")
    total_available_days = int(scoped["trade_date"].nunique())
    minimum_trade_days = 2 if total_available_days <= 5 else 5
    estimated_trade_days = int((day_counts >= 1).sum())
    estimated_signal_count = int(day_counts.clip(upper=2).sum())

    anchor_alignment_score = _anchor_alignment_score(
        allowed_hours=allowed_hours,
        open_anchor_hour_utc=open_anchor_hour_utc,
        max_hold_bars=max_hold_bars,
        overnight_allowed=overnight_allowed,
    )
    daytype_alignment_score = _daytype_alignment_score(qualifying)
    geometry_knob_count = len(dict(template.get("custom_filters") or {}))
    pretest_score = (
        estimated_trade_days * 1.15
        + min(estimated_signal_count, 120) * 0.35
        + anchor_alignment_score * 25.0
        + daytype_alignment_score * 25.0
        + max(min(book_alignment_score, 1.0), -1.0) * 18.0
        - max(geometry_knob_count - 8, 0) * 3.5
    )

    if estimated_trade_days < minimum_trade_days:
        return DayTradingHypothesisScreenRecord(
            family=family,
            entry_style=entry_style,
            title=title,
            pretest_score=round(pretest_score - 30.0, 6),
            pretest_eligible=False,
            pretest_reason="insufficient_trade_day_density",
            estimated_trade_days=estimated_trade_days,
            estimated_signal_count=estimated_signal_count,
            anchor_alignment_score=round(anchor_alignment_score, 6),
            daytype_alignment_score=round(daytype_alignment_score, 6),
            book_alignment_score=book_alignment_score,
            book_veto_reasons=book_veto_reasons,
            open_anchor_hour_utc=open_anchor_hour_utc,
            max_hold_bars=max_hold_bars,
            overnight_allowed=overnight_allowed,
            risk_filter_profile=risk_filter_profile,
        )
    if anchor_alignment_score < 0.45:
        return DayTradingHypothesisScreenRecord(
            family=family,
            entry_style=entry_style,
            title=title,
            pretest_score=round(pretest_score - 20.0, 6),
            pretest_eligible=False,
            pretest_reason="weak_open_anchor_alignment",
            estimated_trade_days=estimated_trade_days,
            estimated_signal_count=estimated_signal_count,
            anchor_alignment_score=round(anchor_alignment_score, 6),
            daytype_alignment_score=round(daytype_alignment_score, 6),
            book_alignment_score=book_alignment_score,
            book_veto_reasons=book_veto_reasons,
            open_anchor_hour_utc=open_anchor_hour_utc,
            max_hold_bars=max_hold_bars,
            overnight_allowed=overnight_allowed,
            risk_filter_profile=risk_filter_profile,
        )

    return DayTradingHypothesisScreenRecord(
        family=family,
        entry_style=entry_style,
        title=title,
        pretest_score=round(pretest_score, 6),
        pretest_eligible=True,
        pretest_reason="eligible_for_materialization",
        estimated_trade_days=estimated_trade_days,
        estimated_signal_count=estimated_signal_count,
        anchor_alignment_score=round(anchor_alignment_score, 6),
        daytype_alignment_score=round(daytype_alignment_score, 6),
        book_alignment_score=book_alignment_score,
        book_veto_reasons=book_veto_reasons,
        open_anchor_hour_utc=open_anchor_hour_utc,
        max_hold_bars=max_hold_bars,
        overnight_allowed=overnight_allowed,
        risk_filter_profile=risk_filter_profile,
    )


def _anchor_alignment_score(
    *,
    allowed_hours: list[int],
    open_anchor_hour_utc: int,
    max_hold_bars: int,
    overnight_allowed: bool,
) -> float:
    if not allowed_hours:
        return 0.0
    latest_hour = max(allowed_hours)
    earliest_hour = min(allowed_hours)
    score = 0.0
    if earliest_hour >= open_anchor_hour_utc and latest_hour <= open_anchor_hour_utc + 2:
        score += 0.6
    elif earliest_hour >= open_anchor_hour_utc and latest_hour <= open_anchor_hour_utc + 3:
        score += 0.45
    elif latest_hour <= open_anchor_hour_utc + 4:
        score += 0.25
    if max_hold_bars <= 18:
        score += 0.25
    elif max_hold_bars <= 24:
        score += 0.10
    if not overnight_allowed:
        score += 0.15
    return min(score, 1.0)


def _daytype_alignment_score(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    spread_component = (
        1.0 / frame["spread_shock_20"].clip(lower=1.0, upper=5.0)
    ).clip(lower=0.0, upper=1.0).mean()
    volatility_component = (
        frame["volatility_ratio_5_to_20"].clip(lower=0.0, upper=1.5) / 1.5
    ).mean()
    efficiency_component = (
        frame["range_efficiency_10"].clip(lower=0.0, upper=1.2) / 1.2
    ).mean()
    return float((spread_component + volatility_component + efficiency_component) / 3.0)


def _template_pretest_mask(
    frame: pd.DataFrame,
    template: dict[str, object],
    *,
    open_anchor_hour_utc: int,
) -> pd.Series:
    custom_filters = dict(template.get("custom_filters") or {})
    mask = pd.Series(True, index=frame.index)
    if not custom_filters:
        return mask

    def filter_float(name: str) -> float | None:
        raw = custom_filters.get(name)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def filter_enabled(name: str) -> bool:
        raw = str(custom_filters.get(name, "")).strip().lower()
        return raw in {"1", "true", "yes", "on", "required"}

    max_spread = filter_float("max_spread_pips")
    if max_spread is not None:
        mask &= frame["spread_pips"] <= max_spread
    max_spread_shock = filter_float("max_spread_shock_20")
    if max_spread_shock is not None:
        mask &= frame["spread_shock_20"] <= max_spread_shock
    max_spread_to_range = filter_float("max_spread_to_range_10")
    if max_spread_to_range is not None:
        mask &= frame["spread_to_range_10"] <= max_spread_to_range
    min_volatility = filter_float("min_volatility_20")
    if min_volatility is not None:
        mask &= frame["volatility_20"] >= (min_volatility * 0.5)
    max_range_width = filter_float("max_range_width_10_pips")
    if max_range_width is not None:
        mask &= frame["range_width_10_pips"] <= max_range_width
    min_range_efficiency = filter_float("min_range_efficiency_10")
    if min_range_efficiency is not None:
        mask &= frame["range_efficiency_10"] >= min_range_efficiency
    max_range_efficiency = filter_float("max_range_efficiency_10")
    if max_range_efficiency is not None:
        mask &= frame["range_efficiency_10"] <= max_range_efficiency
    blocked_context = str(custom_filters.get("exclude_context_bucket", "")).strip()
    if blocked_context:
        mask &= _context_series(frame) != blocked_context
    required_phase_bucket = str(custom_filters.get("required_phase_bucket", "")).strip()
    if required_phase_bucket:
        mask &= frame["hour"].map(lambda hour: _phase_bucket_for_hour(int(hour), open_anchor_hour_utc=open_anchor_hour_utc)) == required_phase_bucket
    if filter_enabled("require_ret_1_confirmation") or filter_enabled("require_reversal_ret_1") or filter_enabled("require_recovery_ret_1"):
        mask &= frame["ret_1"].abs() > 0.0
    return mask


def _volatility_bucket(volatility: float) -> str:
    if volatility <= 0.00005:
        return "low"
    if volatility <= 0.00012:
        return "medium"
    return "high"


def _context_series(frame: pd.DataFrame) -> pd.Series:
    return frame.apply(lambda row: _context_bucket(float(row["zscore_10"]), float(row["momentum_12"])), axis=1)


def _context_bucket(zscore: float, momentum: float) -> str:
    if abs(zscore) >= 1.2:
        return "mean_reversion_context"
    if abs(momentum) >= 0.8:
        return "trend_context"
    return "neutral_context"


def _phase_bucket_for_hour(hour_utc: int, *, open_anchor_hour_utc: int) -> str:
    if hour_utc <= open_anchor_hour_utc:
        return "open_impulse"
    if hour_utc == open_anchor_hour_utc + 1:
        return "early_follow_through"
    if hour_utc <= open_anchor_hour_utc + 4:
        return "late_morning_decay"
    return "outside_anchor"


def _build_review_runner(settings: Settings):
    review_engine = WorkflowEngine(
        settings=settings,
        llm_client=MockLLMClient(),
        tool_registry=build_tool_registry(),
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    review_workflow = WorkflowRepository(settings.paths()).load(settings.workflows.review_workflow_id)
    return review_engine, review_workflow


def _load_cached_day_trading_artifacts(
    settings: Settings,
    *,
    family_filter: str | None = None,
) -> dict[tuple[str, str, str], "_CandidateArtifact"]:
    cache: dict[tuple[str, str, str], _CandidateArtifact] = {}
    report_dirs = sorted(
        (path for path in settings.paths().reports_dir.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for report_dir in report_dirs:
        candidate_path = report_dir / "candidate.json"
        spec_path = report_dir / "strategy_spec.json"
        review_path = report_dir / "review_packet.json"
        if not candidate_path.exists() or not spec_path.exists() or not review_path.exists():
            continue
        candidate = CandidateDraft.model_validate(read_json(candidate_path))
        if family_filter and candidate.family != family_filter:
            continue
        key = (candidate.family, candidate.title, candidate.entry_style)
        if key in cache:
            continue
        spec = StrategySpec.model_validate(read_json(spec_path))
        review_packet = ReviewPacket.model_validate(read_json(review_path))
        cache[key] = _CandidateArtifact(candidate=candidate, spec=spec, review_packet=review_packet)
    return cache


class _CandidateArtifact:
    def __init__(self, candidate: CandidateDraft, spec: StrategySpec, review_packet: ReviewPacket) -> None:
        self.candidate = candidate
        self.spec = spec
        self.review_packet = review_packet


def _materialize_candidate(
    candidate: CandidateDraft,
    settings: Settings,
    *,
    review_engine: WorkflowEngine,
    review_workflow,
) -> _CandidateArtifact:
    candidate_path = settings.paths().reports_dir / candidate.candidate_id / "candidate.json"
    write_json(candidate_path, candidate.model_dump(mode="json"))
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    review_trace = review_engine.run(review_workflow, spec.model_dump(mode="json"))
    if review_trace.output_payload is None:
        error = next((item.error for item in review_trace.node_traces if item.error), "Review workflow failed.")
        raise RuntimeError(error)
    review_packet = ReviewPacket.model_validate(review_trace.output_payload)
    return _CandidateArtifact(candidate=candidate, spec=spec, review_packet=review_packet)


def _scan_record_from_artifact(artifact: _CandidateArtifact) -> DayTradingBehaviorScanRecord:
    metrics = artifact.review_packet.metrics
    walk_forward = list(metrics.get("walk_forward_summary") or [])
    regime_breakdown = dict(metrics.get("regime_breakdown") or {})
    split_breakdown = dict(metrics.get("split_breakdown") or {})
    stress_scenarios = list(metrics.get("stress_scenarios") or [])
    min_walk_forward_trade_count = min((int(window.get("trade_count", 0)) for window in walk_forward), default=0)
    stressed_profit_factor = float(stress_scenarios[-1]["profit_factor"]) if stress_scenarios else 0.0
    supported_slice_count = _supported_slice_count(regime_breakdown)
    trade_count = int(metrics.get("trade_count", 0))
    oos_pf = float(metrics.get("out_of_sample_profit_factor", 0.0))
    expectancy = float(metrics.get("expectancy_pips", 0.0))
    drawdown = float(metrics.get("max_drawdown_pct", 0.0))
    walk_forward_ok = all(bool(window.get("passed")) for window in walk_forward) if walk_forward else False
    stress_passed = bool(metrics.get("stress_passed", False))
    book_alignment_score = float(artifact.candidate.book_alignment_score or 0.0)
    book_veto_reasons = list(artifact.candidate.book_veto_reasons or [])
    open_anchor_hour_utc = artifact.candidate.open_anchor_hour_utc
    max_hold_bars = artifact.candidate.max_hold_bars
    overnight_allowed = bool(artifact.candidate.overnight_allowed)
    risk_filter_profile = artifact.candidate.risk_filter_profile
    comparison_eligible, comparison_eligibility_reason = _front_door_comparison_gate(
        split_breakdown=split_breakdown,
        out_of_sample_profit_factor=oos_pf,
        expectancy_pips=expectancy,
        stressed_profit_factor=stressed_profit_factor,
        stress_passed=stress_passed,
        book_alignment_score=book_alignment_score,
        book_veto_reasons=book_veto_reasons,
        overnight_allowed=overnight_allowed,
        max_hold_bars=max_hold_bars,
    )
    scan_score = _behavior_scan_score(
        trade_count=trade_count,
        min_walk_forward_trade_count=min_walk_forward_trade_count,
        oos_profit_factor=oos_pf,
        expectancy_pips=expectancy,
        stressed_profit_factor=stressed_profit_factor,
        max_drawdown_pct=drawdown,
        stress_passed=stress_passed,
        walk_forward_ok=walk_forward_ok,
        supported_slice_count=supported_slice_count,
        comparison_eligible=comparison_eligible,
        book_alignment_score=book_alignment_score,
    )
    report_dir = Path(metrics["data_provenance"]["report_path"]).parent
    return DayTradingBehaviorScanRecord(
        candidate_id=artifact.candidate.candidate_id,
        family=artifact.candidate.family,
        entry_style=artifact.candidate.entry_style,
        title=artifact.candidate.title,
        trade_count=trade_count,
        min_walk_forward_trade_count=min_walk_forward_trade_count,
        walk_forward_ok=walk_forward_ok,
        out_of_sample_profit_factor=oos_pf,
        expectancy_pips=expectancy,
        stressed_profit_factor=stressed_profit_factor,
        stress_passed=stress_passed,
        max_drawdown_pct=drawdown,
        supported_slice_count=supported_slice_count,
        comparison_eligible=comparison_eligible,
        comparison_eligibility_reason=comparison_eligibility_reason,
        book_alignment_score=book_alignment_score,
        book_veto_reasons=book_veto_reasons,
        open_anchor_hour_utc=open_anchor_hour_utc,
        max_hold_bars=max_hold_bars,
        overnight_allowed=overnight_allowed,
        risk_filter_profile=risk_filter_profile,
        scan_score=round(scan_score, 6),
        candidate_path=report_dir / "candidate.json",
        spec_path=report_dir / "strategy_spec.json",
        backtest_summary_path=report_dir / "backtest_summary.json",
        stress_report_path=report_dir / "stress_test.json",
        review_packet_path=report_dir / "review_packet.json",
    )


def _front_door_comparison_gate(
    *,
    split_breakdown: dict[str, object],
    out_of_sample_profit_factor: float,
    expectancy_pips: float,
    stressed_profit_factor: float,
    stress_passed: bool,
    book_alignment_score: float = 0.0,
    book_veto_reasons: list[str] | None = None,
    overnight_allowed: bool = False,
    max_hold_bars: int | None = None,
) -> tuple[bool, str | None]:
    train = dict(split_breakdown.get("train") or {})
    validation = dict(split_breakdown.get("validation") or {})
    train_expectancy = float(train.get("expectancy_pips", 0.0))
    validation_expectancy = float(validation.get("expectancy_pips", 0.0))
    train_pf = float(train.get("profit_factor", 0.0))
    validation_pf = float(validation.get("profit_factor", 0.0))
    uniformly_negative = (
        train_expectancy < 0.0
        and validation_expectancy < 0.0
        and train_pf < 1.0
        and validation_pf < 1.0
    )
    if uniformly_negative:
        return False, "uniformly_negative_train_validation"
    negative_edge_failed_stress = (
        expectancy_pips <= 0.0
        and out_of_sample_profit_factor < 1.0
        and (not stress_passed or stressed_profit_factor < 1.0)
    )
    if negative_edge_failed_stress:
        return False, "negative_edge_failed_stress"
    veto_reasons = list(book_veto_reasons or [])
    if "eurusd_release_persistence_veto" in veto_reasons:
        return False, "book_veto_release_persistence"
    if "overnight_momentum_carry_disallowed" in veto_reasons or overnight_allowed:
        return False, "book_veto_overnight_carry"
    if "late_morning_decay_without_density_support" in veto_reasons and (max_hold_bars or 0) > 18:
        return False, "book_veto_late_morning_decay"
    if book_alignment_score < -0.05:
        return False, "negative_book_alignment"
    return True, None


def _evaluate_day_trading_continuation_gate(
    settings: Settings,
    records: list[DayTradingBehaviorScanRecord],
    *,
    reference_candidate_id: str | None,
) -> DayTradingContinuationGate | None:
    if not reference_candidate_id:
        return None
    reference = _load_existing_scan_record(settings, reference_candidate_id)
    required_trade_count = max(int(reference.trade_count * 1.6), reference.trade_count + 15, 40)
    required_min_walk_forward_trade_count = max(reference.min_walk_forward_trade_count + 6, 8)
    minimum_out_of_sample_profit_factor = max(
        settings.validation.out_of_sample_profit_factor_floor + 0.10,
        reference.out_of_sample_profit_factor * 0.35,
    )
    minimum_expectancy_pips = max(
        settings.validation.expectancy_floor + 0.25,
        reference.expectancy_pips * 0.40,
    )
    minimum_stressed_profit_factor = max(
        settings.validation.stress_profit_factor_floor,
        reference.stressed_profit_factor * 0.65,
    )
    selected = next(
        (
            record
            for record in records
            if record.trade_count >= required_trade_count
            and record.min_walk_forward_trade_count >= required_min_walk_forward_trade_count
            and record.out_of_sample_profit_factor >= minimum_out_of_sample_profit_factor
            and record.expectancy_pips >= minimum_expectancy_pips
            and record.stressed_profit_factor >= minimum_stressed_profit_factor
            and record.stress_passed
        ),
        None,
    )
    if selected is not None:
        reason = (
            f"{selected.candidate_id} cleared the density-first continuation gate with "
            f"{selected.trade_count} trades and minimum walk-forward trade count "
            f"{selected.min_walk_forward_trade_count} while keeping expectancy and stress above the "
            "family-preservation floor."
        )
        decision = "continue_refinement"
        selected_candidate_id = selected.candidate_id
    else:
        densest = max(records, key=lambda item: item.trade_count, default=None)
        if densest is None:
            reason = "No family records were produced, so the high-vol persistence clue must reopen discovery."
        else:
            reason = (
                f"No sibling reached the density-first continuation gate. The densest result was "
                f"{densest.candidate_id} with {densest.trade_count} trades, minimum walk-forward trade count "
                f"{densest.min_walk_forward_trade_count}, expectancy {densest.expectancy_pips:.3f}, and stressed "
                f"profit factor {densest.stressed_profit_factor:.3f}."
            )
        decision = "reopen_discovery"
        selected_candidate_id = None
    return DayTradingContinuationGate(
        reference_candidate_id=reference_candidate_id,
        reference_trade_count=reference.trade_count,
        reference_min_walk_forward_trade_count=reference.min_walk_forward_trade_count,
        reference_out_of_sample_profit_factor=reference.out_of_sample_profit_factor,
        reference_expectancy_pips=reference.expectancy_pips,
        reference_stressed_profit_factor=reference.stressed_profit_factor,
        required_trade_count=required_trade_count,
        required_min_walk_forward_trade_count=required_min_walk_forward_trade_count,
        minimum_out_of_sample_profit_factor=round(minimum_out_of_sample_profit_factor, 6),
        minimum_expectancy_pips=round(minimum_expectancy_pips, 6),
        minimum_stressed_profit_factor=round(minimum_stressed_profit_factor, 6),
        decision=decision,
        selected_candidate_id=selected_candidate_id,
        reason=reason,
    )


def _load_existing_scan_record(settings: Settings, candidate_id: str) -> DayTradingBehaviorScanRecord:
    report_dir = settings.paths().reports_dir / candidate_id
    candidate = _load_candidate(settings, candidate_id)
    review = ReviewPacket.model_validate(read_json(report_dir / "review_packet.json"))
    metrics = dict(review.metrics)
    walk_forward = list(metrics.get("walk_forward_summary") or [])
    regime_breakdown = dict(metrics.get("regime_breakdown") or {})
    stress_scenarios = list(metrics.get("stress_scenarios") or [])
    min_walk_forward_trade_count = min((int(window.get("trade_count", 0)) for window in walk_forward), default=0)
    stressed_profit_factor = float(stress_scenarios[-1]["profit_factor"]) if stress_scenarios else 0.0
    return DayTradingBehaviorScanRecord(
        candidate_id=candidate_id,
        family=candidate.family,
        entry_style=candidate.entry_style,
        title=candidate.title,
        trade_count=int(metrics.get("trade_count", 0)),
        min_walk_forward_trade_count=min_walk_forward_trade_count,
        walk_forward_ok=all(bool(window.get("passed")) for window in walk_forward) if walk_forward else False,
        out_of_sample_profit_factor=float(metrics.get("out_of_sample_profit_factor", 0.0)),
        expectancy_pips=float(metrics.get("expectancy_pips", 0.0)),
        stressed_profit_factor=stressed_profit_factor,
        stress_passed=bool(metrics.get("stress_passed", False)),
        max_drawdown_pct=float(metrics.get("max_drawdown_pct", 0.0)),
        supported_slice_count=_supported_slice_count(regime_breakdown),
        comparison_eligible=True,
        book_alignment_score=float(candidate.book_alignment_score or 0.0),
        book_veto_reasons=list(candidate.book_veto_reasons or []),
        open_anchor_hour_utc=candidate.open_anchor_hour_utc,
        max_hold_bars=candidate.max_hold_bars,
        overnight_allowed=bool(candidate.overnight_allowed),
        risk_filter_profile=candidate.risk_filter_profile,
        scan_score=0.0,
        candidate_path=report_dir / "candidate.json",
        spec_path=report_dir / "strategy_spec.json",
        backtest_summary_path=report_dir / "backtest_summary.json",
        stress_report_path=report_dir / "stress_test.json",
        review_packet_path=report_dir / "review_packet.json",
    )


def _load_candidate(settings: Settings, candidate_id: str) -> CandidateDraft:
    candidate_path = settings.paths().reports_dir / candidate_id / "candidate.json"
    return CandidateDraft.model_validate(read_json(candidate_path))


def _supported_slice_count(regime_breakdown: dict[str, object]) -> int:
    count = 0
    for bucket in regime_breakdown.values():
        if not isinstance(bucket, dict):
            continue
        for metrics in bucket.values():
            if not isinstance(metrics, dict):
                continue
            trade_count = int(metrics.get("trade_count", 0))
            profit_factor = float(metrics.get("profit_factor", 0.0))
            mean_pnl = float(metrics.get("mean_pnl_pips", 0.0))
            if trade_count >= 10 and profit_factor >= 1.0 and mean_pnl > 0:
                count += 1
    return count


def _behavior_scan_score(
    *,
    trade_count: int,
    min_walk_forward_trade_count: int,
    oos_profit_factor: float,
    expectancy_pips: float,
    stressed_profit_factor: float,
    max_drawdown_pct: float,
    stress_passed: bool,
    walk_forward_ok: bool,
    supported_slice_count: int,
    comparison_eligible: bool,
    book_alignment_score: float = 0.0,
) -> float:
    trade_density = min(trade_count / 120.0, 1.0)
    window_density = min(min_walk_forward_trade_count / 20.0, 1.0)
    density_factor = trade_density * window_density
    edge_score = 0.0
    edge_score += min(max(oos_profit_factor, 0.0), 2.0) * 16.0
    edge_score += max(min(expectancy_pips, 1.5), -2.0) * 18.0
    edge_score += min(max(stressed_profit_factor, 0.0), 1.5) * 20.0
    edge_score += supported_slice_count * 8.0

    score = 0.0
    score += min(trade_count, 180) * 0.18
    score += min(min_walk_forward_trade_count, 30) * 1.2
    score += edge_score * density_factor
    score -= min(max_drawdown_pct, 25.0) * 1.8
    if trade_count >= 150:
        score += 16.0
    elif trade_count >= 75:
        score += 10.0
    elif trade_count >= 30:
        score += 3.0
    elif trade_count < 15:
        score -= 42.0
    else:
        score -= 18.0
    if min_walk_forward_trade_count >= 20:
        score += 18.0
    elif min_walk_forward_trade_count >= 10:
        score += 8.0
    else:
        score -= 36.0
    if stress_passed:
        score += 20.0
    else:
        score -= 20.0
    if walk_forward_ok:
        score += 16.0
    else:
        score -= 8.0
    if expectancy_pips > 0:
        score += 8.0
    if oos_profit_factor >= 1.05:
        score += 8.0
    if stressed_profit_factor >= 1.0:
        score += 10.0
    if not comparison_eligible:
        score -= 28.0
    score += max(min(book_alignment_score, 1.0), -1.0) * 12.0
    return score


def _load_candidate(settings: Settings, candidate_id: str) -> CandidateDraft:
    path = settings.paths().reports_dir / candidate_id / "candidate.json"
    return CandidateDraft.model_validate_json(path.read_text(encoding="utf-8"))


def _day_trading_templates(*, family_filter: str | None = None) -> list[dict[str, object]]:
    templates = [
        {
            "title": "Europe Compression Break Day Trade",
            "family": "europe_open_compression_research",
            "entry_style": "compression_breakout",
            "holding_bars": 90,
            "signal_threshold": 1.15,
            "stop_loss_pips": 7.5,
            "take_profit_pips": 12.5,
            "session_focus": "europe_compression_expansion",
            "volatility_preference": "low_to_moderate",
            "allowed_hours_utc": [6, 7, 8, 9, 10, 11, 12],
            "thesis": "Trade directional expansion only when a compressed Europe-session range starts releasing with aligned momentum and range-position confirmation.",
            "setup_summary": "Require a compressed intraday range first, then only act when directional expansion starts from the edge of that compression rather than after a fully extended move.",
            "entry_summary": "Enter on a compression break when short-term momentum, z-score, and range-position confirmation align in the same direction.",
            "exit_summary": "Exit via fixed stop, fixed target, or 90-bar timeout.",
            "risk_summary": "Longer intraday hold that prefers low pre-break compression and avoids late-chase entries.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.4",
                "max_range_width_10_pips": "8.2",
                "breakout_zscore_floor": "0.52",
                "compression_range_position_floor": "0.68",
                "require_ret_1_confirmation": "true",
            },
        },
        {
            "title": "Europe Failed Break Fade Day Trade",
            "family": "europe_open_failed_break_research",
            "entry_style": "failed_break_fade",
            "holding_bars": 54,
            "signal_threshold": 1.05,
            "stop_loss_pips": 6.2,
            "take_profit_pips": 9.8,
            "session_focus": "europe_failed_break_reversal",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Fade a failed Europe-open break only after the extension stalls, reversal pressure appears, and price starts snapping back from the stretched edge rather than chasing continuation.",
            "setup_summary": "Require a directional break attempt first, then wait for the move to lose momentum and print a reversal profile before fading back toward the intraday balance.",
            "entry_summary": "Enter on a failed break fade when z-score extension is stretched, short-horizon follow-through has stalled, and the reversal bar points back into the prior range.",
            "exit_summary": "Exit via fixed stop, fixed target, or 54-bar timeout.",
            "risk_summary": "Europe-session reversion day trade that only fades stretched, slowing breaks and avoids late-session overlap behavior.",
            "enable_news_blackout": True,
        },
        {
            "title": "London Range Reclaim Day Trade",
            "family": "europe_open_reclaim_research",
            "entry_style": "range_reclaim",
            "holding_bars": 72,
            "signal_threshold": 1.1,
            "stop_loss_pips": 7.0,
            "take_profit_pips": 11.0,
            "session_focus": "london_range_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [6, 7, 8, 9, 10, 11, 12, 13],
            "thesis": "Fade failed London-session extension only after price starts reclaiming back into the recent range with a controlled reversal profile.",
            "setup_summary": "Look for stretched movement beyond the short-term range, then require reclaim back into the range rather than blindly fading the first extension print.",
            "entry_summary": "Enter on a range reclaim when z-score extension, reversal bar direction, and range-position recovery support the same mean-reverting path.",
            "exit_summary": "Exit via fixed stop, fixed target, or 72-bar timeout.",
            "risk_summary": "Session mean-reversion day trade that demands reclaim evidence before taking a reversal.",
            "enable_news_blackout": True,
        },
        {
            "title": "Europe Selective Breakout Day Trade",
            "family": "europe_open_breakout_research",
            "entry_style": "session_breakout",
            "holding_bars": 42,
            "signal_threshold": 0.98,
            "stop_loss_pips": 6.0,
            "take_profit_pips": 8.8,
            "session_focus": "europe_open_selective_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Trade Europe-open directional breaks only when a balance-area release develops with real follow-through and the move is not immediately fading back into mean-reversion noise.",
            "setup_summary": "Require a real Europe-morning release from balance first, then only take the break when short-horizon direction and range position confirm the move is still expanding.",
            "entry_summary": "Enter on a Europe-open breakout when momentum, z-score, and range-position confirmation align in the same direction and the move still has room to extend.",
            "exit_summary": "Exit via fixed stop, fixed target, or 42-bar timeout.",
            "risk_summary": "Europe-open breakout day trade that seeks cleaner non-overlap directional participation than the reversion families.",
            "enable_news_blackout": True,
        },
        {
            "title": "Europe Balance Breakout Day Trade",
            "family": "europe_open_balance_breakout_research",
            "entry_style": "balance_area_breakout",
            "holding_bars": 30,
            "signal_threshold": 0.86,
            "stop_loss_pips": 5.6,
            "take_profit_pips": 8.0,
            "session_focus": "europe_balance_release_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9, 10, 11],
            "thesis": "Trade Europe-open releases from balance only when price is leaving a tighter range with enough directional expansion to outrun costs without turning into a broad overtraded breakout filter.",
            "setup_summary": "Require a tighter intraday balance first, then only take the breakout when momentum, range position, and short-horizon direction all confirm a real release.",
            "entry_summary": "Enter on a balance-area breakout when compression remains tight, directional momentum is active, and price is already leaving the range from the correct side.",
            "exit_summary": "Exit via fixed stop, fixed target, or 30-bar timeout.",
            "risk_summary": "Selective Europe-open breakout day trade intended to reduce overtrading while keeping the directional release thesis intact.",
            "enable_news_blackout": True,
        },
        {
            "title": "Europe Compression Reversion Day Trade",
            "family": "europe_open_compression_reversion_research",
            "entry_style": "compression_reversion",
            "holding_bars": 36,
            "signal_threshold": 1.02,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.0,
            "session_focus": "europe_core_compression_reversion",
            "volatility_preference": "low_to_moderate",
            "allowed_hours_utc": [7, 8, 9, 10, 11],
            "thesis": "Fade compressed Europe-morning extremes only when the move starts snapping back into the local range with controlled momentum, so the family stays orthogonal to reclaim and breakout release logic.",
            "setup_summary": "Require a tight Europe-session balance first, then only act when an extreme extension starts reclaiming back into the range rather than continuing to expand.",
            "entry_summary": "Enter on a compression reversion when the range stays tight, z-score extension is extreme, price has reclaimed into the recovery band, and the one-bar move confirms reversal direction.",
            "exit_summary": "Exit via fixed stop, fixed target, or 36-bar timeout.",
            "risk_summary": "Europe-core mean-reversion family that targets compressed extremes instead of failed breaks or outright balance releases.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.2",
                "max_range_width_10_pips": "7.4",
                "reclaim_range_position_floor": "0.20",
                "reclaim_range_position_ceiling": "0.42",
                "reclaim_momentum_ceiling": "3.0",
            },
        },
        {
            "title": "Europe Trend Retest Day Trade",
            "family": "europe_open_trend_retest_research",
            "entry_style": "trend_retest",
            "holding_bars": 30,
            "signal_threshold": 0.92,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.4,
            "session_focus": "europe_open_trend_retest",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Trade Europe-open continuation only after the initial directional release pulls back into a controlled retest and then resumes, so the family stays orthogonal to outright breakout chase and mean-reversion reclaim logic.",
            "setup_summary": "Require a directional Europe-morning release first, then wait for a contained retest instead of chasing the first impulse or fading the move back into range.",
            "entry_summary": "Enter on a trend retest when short-horizon trend is already established, price has pulled back into a controlled retest band, and the recovery bar confirms direction.",
            "exit_summary": "Exit via fixed stop, fixed target, or 30-bar timeout.",
            "risk_summary": "Europe-open retest-continuation day trade that aims to keep breakout follow-through while avoiding the weakest chase and reversal states.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.2",
                "min_volatility_20": "0.00006",
                "trend_ret_5_min": "0.00010",
                "retest_zscore_limit": "0.32",
                "retest_range_position_floor": "0.56",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Retest Breakout Day Trade",
            "family": "europe_open_retest_breakout_research",
            "entry_style": "volatility_retest_breakout",
            "holding_bars": 28,
            "signal_threshold": 0.94,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.6,
            "session_focus": "europe_open_retest_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Trade Europe-open continuation after a directional release pulls back into a controlled retest and then breaks again, so the family keeps the continuation edge while broadening beyond the very sparse strict trend-retest cases.",
            "setup_summary": "Require a real Europe-morning release first, then only act when price retests the move without collapsing back into mean-reversion noise.",
            "entry_summary": "Enter on a retest breakout when volatility remains active, trend direction is still aligned, the pullback stays inside the retest band, and the recovery bar resumes the release.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Europe-open retest-breakout day trade intended to lift throughput relative to the strict trend-retest family without reopening broad breakout chase behavior.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.2",
                "min_volatility_20": "0.00005",
                "breakout_zscore_floor": "0.48",
                "trend_ret_5_min": "0.00008",
                "retest_zscore_limit": "0.35",
                "retest_range_position_floor": "0.55",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Pullback Continuation Day Trade",
            "family": "europe_open_pullback_continuation_research",
            "entry_style": "pullback_continuation",
            "holding_bars": 30,
            "signal_threshold": 0.92,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.6,
            "session_focus": "europe_open_pullback_continuation",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Trade Europe-open continuation after the initial release has already established direction and price only pulls back into a shallow continuation zone, so the family is broader than strict retests but still avoids first-impulse chase and reversal logic.",
            "setup_summary": "Require a directional Europe-morning release first, then wait for a shallow pullback that still looks like continuation rather than a full balance reset.",
            "entry_summary": "Enter on a pullback continuation when short-horizon trend remains aligned, the pullback stays inside the allowed continuation band, and the recovery bar resumes the move.",
            "exit_summary": "Exit via fixed stop, fixed target, or 30-bar timeout.",
            "risk_summary": "Europe-open pullback-continuation day trade intended to lift throughput relative to strict retests while staying cleaner than broad breakout-release families.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.1",
                "min_volatility_20": "0.00006",
                "trend_ret_5_min": "0.00008",
                "pullback_zscore_limit": "0.38",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        *_compression_retest_breakout_templates(),
        *_high_vol_momentum_band_templates(),
        *_release_persistence_templates(),
        *_high_vol_pullback_persistence_templates(),
        *_high_vol_pullback_reset_templates(),
        *_high_vol_pullback_regime_templates(),
        *_high_vol_pullback_chronology_templates(),
        *_europe_open_gap_drift_templates(),
        *_europe_open_opening_range_breakout_templates(),
        *_europe_open_post_open_pullback_templates(),
        *_europe_open_impulse_retest_templates(),
        *_europe_open_opening_range_retest_templates(),
        *_europe_open_early_follow_through_templates(),
        *_europe_open_opening_drive_fade_templates(),
        *_asia_europe_transition_reclaim_templates(),
        *_asia_europe_transition_daytype_reclaim_templates(),
    ]
    if family_filter:
        templates = [template for template in templates if str(template.get("family") or "day_trading") == family_filter]
        if not templates:
            raise ValueError(f"No day-trading exploration templates match family={family_filter!r}.")
        return templates
    return [
        template
        for template in templates
        if str(template.get("family") or "day_trading") in _default_open_anchor_families()
    ]


def _default_open_anchor_families() -> set[str]:
    return {
        "europe_open_gap_drift_research",
        "europe_open_opening_range_breakout_research",
        "europe_open_post_open_pullback_research",
        "asia_europe_transition_daytype_reclaim_research",
    }


def _europe_open_gap_drift_templates() -> list[dict[str, object]]:
    family = "europe_open_gap_drift_research"
    return [
        {
            "title": "Europe Open Gap Drift Core",
            "family": family,
            "entry_style": "session_breakout",
            "holding_bars": 14,
            "max_hold_bars": 14,
            "signal_threshold": 0.82,
            "stop_loss_pips": 4.8,
            "take_profit_pips": 6.9,
            "session_focus": "europe_open_gap_drift",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Trade the first Europe-open directional drift only when the opening impulse is large relative to recent close-to-open volatility and still has room to extend before late-morning decay becomes dominant.",
            "setup_summary": "Anchor the setup to 07:00 UTC, require an opening drift that is meaningfully larger than the recent close-to-open baseline, and avoid taking the move once it has already drifted into late-morning decay.",
            "entry_summary": "Enter on a Europe-open gap drift when the opening impulse clears the normalized release floor, spread stays contained versus the live range, and the move remains outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 14-bar timeout with same-day flat only.",
            "risk_summary": "Short-horizon Europe-open drift family with explicit spread, volatility, and calendar-risk filters and no overnight carry.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_spread_to_range_10": "0.34",
                "min_volatility_20": "0.00005",
                "min_volatility_ratio_5_to_20": "1.00",
                "breakout_zscore_floor": "0.46",
                "trend_ret_5_min": "0.00007",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Open Gap Drift Tight Risk",
            "family": family,
            "entry_style": "session_breakout",
            "holding_bars": 12,
            "max_hold_bars": 12,
            "signal_threshold": 0.85,
            "stop_loss_pips": 4.5,
            "take_profit_pips": 6.4,
            "session_focus": "europe_open_gap_drift_tight_risk",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Use the same opening-drift idea but fail faster, so the family only keeps the cleanest Europe-open impulse cases and rejects slower late-morning continuation states.",
            "setup_summary": "Require the same normalized Europe-open impulse, but demand tighter spread-to-range conditions and a shorter hold before the middle-window decay hole starts dominating.",
            "entry_summary": "Enter on a tight-risk Europe-open gap drift when the normalized opening impulse is already live, short-horizon direction is aligned, and the move has not slipped back into balance.",
            "exit_summary": "Exit via fixed stop, fixed target, or 12-bar timeout with same-day flat only.",
            "risk_summary": "Shorter-horizon sibling intended to preserve expectancy and stress survival while keeping the session anchor explicit.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "max_spread_to_range_10": "0.32",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "1.05",
                "breakout_zscore_floor": "0.48",
                "trend_ret_5_min": "0.00008",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
    ]


def _europe_open_opening_range_breakout_templates() -> list[dict[str, object]]:
    family = "europe_open_opening_range_breakout_research"
    return [
        {
            "title": "Europe Opening Range Breakout Core",
            "family": family,
            "entry_style": "compression_breakout",
            "holding_bars": 16,
            "max_hold_bars": 16,
            "signal_threshold": 0.84,
            "stop_loss_pips": 4.9,
            "take_profit_pips": 7.1,
            "session_focus": "europe_open_opening_range_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Wait for the first Europe-open range to set, then trade the breakout only if the release is strong enough to clear costs and still remains inside the short post-open phase rather than late-morning drift.",
            "setup_summary": "Anchor the opening range at 07:00 UTC, require a clean early balance first, and only participate once the range resolves with enough directional quality to outrun costs.",
            "entry_summary": "Enter on an opening-range breakout when the early range is still tight, the breakout is normalized against close-to-open volatility, and the move remains outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout with same-day flat only.",
            "risk_summary": "Opening-range breakout family with explicit open anchor, short time exit, and risk-day veto filters.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_spread_to_range_10": "0.36",
                "max_range_width_10_pips": "7.4",
                "min_volatility_20": "0.000045",
                "breakout_zscore_floor": "0.42",
                "compression_range_position_floor": "0.63",
                "exclude_context_bucket": "mean_reversion_context",
                "require_ret_1_confirmation": "true",
            },
        },
        {
            "title": "Europe Opening Range Breakout Short Hold",
            "family": family,
            "entry_style": "compression_breakout",
            "holding_bars": 12,
            "max_hold_bars": 12,
            "signal_threshold": 0.87,
            "stop_loss_pips": 4.6,
            "take_profit_pips": 6.5,
            "session_focus": "europe_open_opening_range_breakout_short_hold",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Use the same opening-range breakout anchor but cap the holding window more aggressively so the family stays inside the early follow-through phase instead of the weak late-morning decay regime.",
            "setup_summary": "Require an early opening range first, then only accept the breakout if the move clears a higher release floor and still has a short-horizon route to target before the window-two decay state appears.",
            "entry_summary": "Enter on a short-hold opening-range breakout when the early range is tight, the breakout is strong relative to the background window, and spread remains controlled against the active range.",
            "exit_summary": "Exit via fixed stop, fixed target, or 12-bar timeout with same-day flat only.",
            "risk_summary": "Short-hold sibling designed to preserve book-aligned simplicity and avoid late-morning momentum decay.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "max_spread_to_range_10": "0.34",
                "max_range_width_10_pips": "7.0",
                "min_volatility_20": "0.00005",
                "breakout_zscore_floor": "0.45",
                "compression_range_position_floor": "0.66",
                "exclude_context_bucket": "mean_reversion_context",
                "require_ret_1_confirmation": "true",
            },
        },
    ]


def _europe_open_post_open_pullback_templates() -> list[dict[str, object]]:
    family = "europe_open_post_open_pullback_research"
    return [
        {
            "title": "Europe Post-Open Pullback Core",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 14,
            "max_hold_bars": 14,
            "signal_threshold": 0.86,
            "stop_loss_pips": 4.7,
            "take_profit_pips": 6.8,
            "session_focus": "europe_open_post_open_pullback",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Require a valid Europe-open impulse first, then only trade a shallow continuation pullback inside the early post-open phase before the weak middle-window decay starts to dominate.",
            "setup_summary": "Anchor the family to the 07:00 UTC opening impulse and only admit shallow continuation pullbacks after a validated release instead of stretching the hold into late-morning persistence.",
            "entry_summary": "Enter on a post-open pullback when the opening impulse is already established, the pullback remains shallow inside the early continuation band, and the recovery resumes outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 14-bar timeout with same-day flat only.",
            "risk_summary": "Post-open pullback continuation family with explicit session anchor, short horizon, and soft risk-day veto filters.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_spread_to_range_10": "0.35",
                "min_volatility_20": "0.00005",
                "trend_ret_5_min": "0.00007",
                "pullback_zscore_limit": "0.34",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Post-Open Pullback Fast Exit",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 10,
            "max_hold_bars": 10,
            "signal_threshold": 0.88,
            "stop_loss_pips": 4.4,
            "take_profit_pips": 6.1,
            "session_focus": "europe_open_post_open_pullback_fast_exit",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Shorten the post-open pullback horizon further so the family only keeps the fast continuation states that can survive costs before the hour-9 density hole develops.",
            "setup_summary": "Require the same anchored opening impulse and shallow pullback, but insist on faster re-acceleration and a tighter hold window to stay inside the early follow-through phase.",
            "entry_summary": "Enter on a fast-exit post-open pullback when the opening impulse is already live, the pullback stays shallow, and the recovery resumes quickly with controlled spread-to-range.",
            "exit_summary": "Exit via fixed stop, fixed target, or 10-bar timeout with same-day flat only.",
            "risk_summary": "Fast-exit sibling aimed at preserving expectancy and stress pass while broadening only the earliest valid pullback states.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "max_spread_to_range_10": "0.33",
                "min_volatility_20": "0.000055",
                "trend_ret_5_min": "0.00008",
                "pullback_zscore_limit": "0.32",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
    ]


def _europe_open_impulse_retest_templates() -> list[dict[str, object]]:
    family = "europe_open_impulse_retest_research"
    return [
        {
            "title": "Europe Open Follow-Through Retest Core",
            "family": family,
            "entry_style": "volatility_retest_breakout",
            "holding_bars": 8,
            "max_hold_bars": 8,
            "signal_threshold": 0.86,
            "stop_loss_pips": 4.3,
            "take_profit_pips": 5.8,
            "session_focus": "europe_open_follow_through_retest",
            "volatility_preference": "high",
            "allowed_hours_utc": [8],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Require a real Europe-open impulse first, then trade only the first hour-8 follow-through retest that resumes in the opening direction before late-morning decay starts.",
            "setup_summary": "Anchor at 07:00 UTC, require a normalized opening impulse, and only admit the first retest during the early follow-through phase rather than the opening burst itself.",
            "entry_summary": "Enter on a Europe-open follow-through retest when the opening move is already live, volatility is elevated, the retest stays shallow, and the recovery confirms immediately after the first hour.",
            "exit_summary": "Exit via fixed stop, fixed target, or 8-bar timeout with same-day flat only.",
            "risk_summary": "Selective early follow-through retest family with a shorter holding horizon, explicit risk-day filters, and no overnight carry.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.08",
                "breakout_zscore_floor": "0.52",
                "retest_zscore_limit": "0.28",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Open Follow-Through Retest Tight",
            "family": family,
            "entry_style": "volatility_retest_breakout",
            "holding_bars": 6,
            "max_hold_bars": 6,
            "signal_threshold": 0.89,
            "stop_loss_pips": 4.0,
            "take_profit_pips": 5.4,
            "session_focus": "europe_open_follow_through_retest_tight",
            "volatility_preference": "high",
            "allowed_hours_utc": [8],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Use the same hour-8 follow-through retest anchor but cap the hold even harder so the family keeps only the fastest post-open continuation states.",
            "setup_summary": "Require a strong opening impulse first, then accept only the immediate follow-through retest states that can resolve before the hour-9 decay hole begins.",
            "entry_summary": "Enter on a tight Europe-open follow-through retest when volatility is high, the retest remains shallow, and the recovery resumes with immediate confirmation after the open.",
            "exit_summary": "Exit via fixed stop, fixed target, or 6-bar timeout with same-day flat only.",
            "risk_summary": "Tight sibling that favors simple post-open continuation over broader breakout drift.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.7",
                "min_volatility_20": "0.000065",
                "min_volatility_ratio_5_to_20": "1.10",
                "breakout_zscore_floor": "0.55",
                "retest_zscore_limit": "0.24",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
    ]


def _europe_open_opening_range_retest_templates() -> list[dict[str, object]]:
    family = "europe_open_opening_range_retest_research"
    return [
        {
            "title": "Europe Opening Range Follow-Through Retest Core",
            "family": family,
            "entry_style": "compression_retest_breakout",
            "holding_bars": 8,
            "max_hold_bars": 8,
            "signal_threshold": 0.85,
            "stop_loss_pips": 4.2,
            "take_profit_pips": 5.8,
            "session_focus": "europe_open_opening_range_follow_through_retest",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Let the first Europe-open range set, then trade only the first hour-8 retest breakout that escapes the opening balance with enough quality to clear costs before late-morning decay.",
            "setup_summary": "Anchor the opening range to 07:00 UTC, require a compact early balance, and only admit retest breakouts during early follow-through rather than the opening burst.",
            "entry_summary": "Enter on an opening-range follow-through retest when the range remains tight, the retest is shallow, and the release resumes with short-horizon continuation after the first hour.",
            "exit_summary": "Exit via fixed stop, fixed target, or 8-bar timeout with same-day flat only.",
            "risk_summary": "Opening-range follow-through retest family with an explicit open anchor, short hold, and the same risk-day veto profile as the other book-guided momentum families.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "max_range_width_10_pips": "6.8",
                "min_volatility_20": "0.00005",
                "breakout_zscore_floor": "0.40",
                "retest_zscore_limit": "0.26",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Opening Range Follow-Through Retest Tight",
            "family": family,
            "entry_style": "compression_retest_breakout",
            "holding_bars": 6,
            "max_hold_bars": 6,
            "signal_threshold": 0.88,
            "stop_loss_pips": 3.9,
            "take_profit_pips": 5.2,
            "session_focus": "europe_open_opening_range_follow_through_retest_tight",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Use the same opening-range retest idea but only keep the fastest, tightest hour-8 release states that can resolve before the hour-9 density hole appears.",
            "setup_summary": "Require a narrower opening range, a cleaner retest, and a faster release so the setup stays inside the earliest post-open continuation phase.",
            "entry_summary": "Enter on a tight opening-range follow-through retest when the range is compressed, the retest stays contained, and the breakout resumes immediately after the first hour.",
            "exit_summary": "Exit via fixed stop, fixed target, or 6-bar timeout with same-day flat only.",
            "risk_summary": "Tighter sibling intended to reduce noisy broad breakouts and keep only compact Europe-open release states.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.7",
                "max_range_width_10_pips": "6.2",
                "min_volatility_20": "0.000055",
                "breakout_zscore_floor": "0.42",
                "retest_zscore_limit": "0.24",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
    ]


def _europe_open_early_follow_through_templates() -> list[dict[str, object]]:
    family = "europe_open_early_follow_through_research"
    return [
        {
            "title": "Europe Delayed Follow-Through Core",
            "family": family,
            "entry_style": "session_momentum_band",
            "holding_bars": 8,
            "max_hold_bars": 8,
            "signal_threshold": 0.86,
            "stop_loss_pips": 4.2,
            "take_profit_pips": 5.8,
            "session_focus": "europe_open_delayed_follow_through",
            "volatility_preference": "high",
            "allowed_hours_utc": [8],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Trade only the delayed follow-through band after a real Europe-open impulse, while momentum is still concentrated in hour 8 and before the late-morning decay regime starts.",
            "setup_summary": "Anchor to 07:00 UTC, require a live opening impulse first, and only admit continuation inside a narrow momentum band during delayed follow-through rather than the opening burst.",
            "entry_summary": "Enter on delayed follow-through when the Europe-open impulse stays outside balance, volatility is elevated, and short-horizon direction confirms after the first hour.",
            "exit_summary": "Exit via fixed stop, fixed target, or 8-bar timeout with same-day flat only.",
            "risk_summary": "Delayed follow-through family that emphasizes short-horizon momentum persistence with explicit risk-day filters and no overnight carry.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "min_volatility_20": "0.00006",
                "continuation_zscore_floor": "0.24",
                "continuation_zscore_ceiling": "0.82",
                "require_ret_1_confirmation": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Delayed Follow-Through Tight Band",
            "family": family,
            "entry_style": "session_momentum_band",
            "holding_bars": 6,
            "max_hold_bars": 6,
            "signal_threshold": 0.88,
            "stop_loss_pips": 3.9,
            "take_profit_pips": 5.2,
            "session_focus": "europe_open_delayed_follow_through_tight",
            "volatility_preference": "high",
            "allowed_hours_utc": [8],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Use the same delayed follow-through idea but keep only the cleanest, most concentrated continuation states inside hour 8.",
            "setup_summary": "Require stronger Europe-open momentum, a tighter continuation band, and a shorter hold so the family stays inside the book-aligned delayed follow-through phase.",
            "entry_summary": "Enter on a tight-band delayed follow-through when the opening impulse remains active, the continuation band stays narrow, and ret-1 confirms after the first hour.",
            "exit_summary": "Exit via fixed stop, fixed target, or 6-bar timeout with same-day flat only.",
            "risk_summary": "Tight-band sibling intended to keep only the highest-quality delayed continuation states and discard broader late drift.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.7",
                "min_volatility_20": "0.000065",
                "continuation_zscore_floor": "0.28",
                "continuation_zscore_ceiling": "0.76",
                "require_ret_1_confirmation": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
    ]


def _europe_open_opening_drive_fade_templates() -> list[dict[str, object]]:
    family = "europe_open_opening_drive_fade_research"
    return [
        {
            "title": "Europe Opening Drive Fade Core",
            "family": family,
            "entry_style": "failed_break_fade",
            "holding_bars": 8,
            "max_hold_bars": 8,
            "signal_threshold": 0.84,
            "stop_loss_pips": 4.4,
            "take_profit_pips": 5.8,
            "session_focus": "europe_open_opening_drive_fade",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Fade the first failed Europe-open follow-through only after the opening drive extends, stalls, and begins snapping back during hour 8 rather than continuing cleanly.",
            "setup_summary": "Anchor to 07:00 UTC, require a real opening drive first, then wait for the post-open continuation attempt to fail before fading back toward balance.",
            "entry_summary": "Enter on an opening-drive fade when the hour-8 continuation attempt is stretched, reversal pressure appears, and the move starts rotating back into the prior range.",
            "exit_summary": "Exit via fixed stop, fixed target, or 8-bar timeout with same-day flat only.",
            "risk_summary": "Short-horizon Europe-open fade family aimed at exploiting failed follow-through rather than chasing continuation.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.02",
                "fade_ret_5_floor": "0.00005",
                "fade_momentum_ceiling": "2.4",
                "require_reversal_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Opening Drive Fade Tight",
            "family": family,
            "entry_style": "failed_break_fade",
            "holding_bars": 6,
            "max_hold_bars": 6,
            "signal_threshold": 0.87,
            "stop_loss_pips": 4.0,
            "take_profit_pips": 5.2,
            "session_focus": "europe_open_opening_drive_fade_tight",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8],
            "open_anchor_hour_utc": 7,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Use the same opening-drive fade anchor but keep only the quickest failed hour-8 continuation states that rotate back immediately.",
            "setup_summary": "Require a real opening drive first, then accept only the tightest failed follow-through states that resolve before the hour-9 decay window opens.",
            "entry_summary": "Enter on a tight opening-drive fade when the hour-8 continuation attempt is stretched, reversal pressure is immediate, and the move rotates back toward the opening range.",
            "exit_summary": "Exit via fixed stop, fixed target, or 6-bar timeout with same-day flat only.",
            "risk_summary": "Tighter sibling meant to keep the fade thesis simple, short, and cost-aware.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.7",
                "min_volatility_20": "0.000065",
                "min_volatility_ratio_5_to_20": "1.05",
                "fade_ret_5_floor": "0.00006",
                "fade_momentum_ceiling": "2.2",
                "require_reversal_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
    ]


def _asia_europe_transition_reclaim_templates() -> list[dict[str, object]]:
    family = "asia_europe_transition_reclaim_research"
    return [
        {
            "title": "Asia-Europe Transition Reclaim Core",
            "family": family,
            "entry_style": "drift_reclaim",
            "holding_bars": 16,
            "max_hold_bars": 16,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.2,
            "session_focus": "asia_europe_transition_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [5, 6, 7],
            "open_anchor_hour_utc": 6,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Trade only the high-volatility reclaim after an Asia-to-Europe directional drift overextends and begins rotating back toward balance during the handoff window.",
            "setup_summary": "Require a one-way late-Asia drift first, then wait for handoff exhaustion and reclaim confirmation instead of chasing the drift into Europe.",
            "entry_summary": "Enter on an Asia-Europe transition reclaim when the overnight drift is stretched, volatility remains elevated, and reclaim confirmation rotates back from the drift extreme.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout with same-day flat only.",
            "risk_summary": "Transition-state reclaim family that keeps the bridge logic blank-slate, high-volatility only, and short-horizon.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.05",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.72",
                "reclaim_confirmation_floor": "0.42",
                "require_reversal_ret_1": "true",
            },
        },
        {
            "title": "Asia-Europe Transition Reclaim Tight",
            "family": family,
            "entry_style": "drift_reclaim",
            "holding_bars": 12,
            "max_hold_bars": 12,
            "signal_threshold": 0.93,
            "stop_loss_pips": 4.8,
            "take_profit_pips": 6.6,
            "session_focus": "asia_europe_transition_reclaim_tight",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7],
            "open_anchor_hour_utc": 6,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_realized_vol_calendar_blackout",
            "thesis": "Use the same transition reclaim idea but keep only the tightest, later handoff states where the stretched drift fails cleanly into Europe.",
            "setup_summary": "Require a high-volatility handoff drift first, then only admit the reclaim once the late-Asia move is clearly exhausting into the Europe transition.",
            "entry_summary": "Enter on a tight transition reclaim when drift extension is stretched, the reclaim confirms cleanly, and the move rotates back before Europe-open continuation takes over.",
            "exit_summary": "Exit via fixed stop, fixed target, or 12-bar timeout with same-day flat only.",
            "risk_summary": "Tighter bridge-state reclaim sibling aimed at preserving expectancy and stress by avoiding earlier low-quality handoff noise.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.000065",
                "min_volatility_ratio_5_to_20": "1.08",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.78",
                "reclaim_confirmation_floor": "0.46",
                "require_reversal_ret_1": "true",
            },
        },
    ]


def _asia_europe_transition_daytype_reclaim_templates() -> list[dict[str, object]]:
    family = "asia_europe_transition_daytype_reclaim_research"
    return [
        {
            "title": "Asia-Europe Transition Day-Type Reclaim Core",
            "family": family,
            "entry_style": "drift_reclaim",
            "holding_bars": 16,
            "max_hold_bars": 16,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.1,
            "session_focus": "asia_europe_transition_daytype_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8],
            "open_anchor_hour_utc": 6,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_range_efficiency_vol_persistence",
            "thesis": "Trade the Asia-to-Europe reclaim only on transition days where the bridge remains directional, spread has not shocked wider than normal, and realized volatility is still persistent enough for the handoff reversal to rotate cleanly.",
            "setup_summary": "Classify the handoff day first: controlled spread shock, efficient bridge directionality, and persistent volatility must all be present before reclaim logic is allowed to fire.",
            "entry_summary": "Enter on a transition reclaim when the drift is stretched, bridge-day quality remains intact, reclaim confirmation is present, and the trade stays outside the weak neutral context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout with same-day flat only.",
            "risk_summary": "Day-type filtered bridge reclaim intended to add repeatable density without reopening low-quality transition days.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "max_spread_shock_20": "1.15",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "1.00",
                "min_range_efficiency_10": "0.38",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.68",
                "reclaim_confirmation_floor": "0.38",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
        },
        {
            "title": "Asia-Europe Transition Day-Type Tight",
            "family": family,
            "entry_style": "drift_reclaim",
            "holding_bars": 14,
            "max_hold_bars": 14,
            "signal_threshold": 0.90,
            "stop_loss_pips": 4.9,
            "take_profit_pips": 6.8,
            "session_focus": "asia_europe_transition_daytype_tight",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8],
            "open_anchor_hour_utc": 6,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_range_efficiency_vol_persistence",
            "thesis": "Keep only the cleaner Europe-side handoff reclaims where transition-day quality is highest and the reclaim begins after earlier bridge churn has already been filtered out.",
            "setup_summary": "Require the same directional transition day, but only keep the later handoff pocket with tighter spread-shock and range-efficiency requirements.",
            "entry_summary": "Enter on a tight day-type reclaim when the bridge remains high-quality, the drift is still stretched, reclaim confirmation is present, and the later handoff begins rotating back from the extreme.",
            "exit_summary": "Exit via fixed stop, fixed target, or 14-bar timeout with same-day flat only.",
            "risk_summary": "Later-handoff sibling aimed at preserving expectancy and stress while blocking weaker early bridge noise.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_spread_shock_20": "1.08",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.03",
                "min_range_efficiency_10": "0.44",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.72",
                "reclaim_confirmation_floor": "0.41",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
        },
        {
            "title": "Asia-Europe Transition Day-Type Density",
            "family": family,
            "entry_style": "drift_reclaim",
            "holding_bars": 18,
            "max_hold_bars": 18,
            "signal_threshold": 0.86,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.3,
            "session_focus": "asia_europe_transition_daytype_density",
            "volatility_preference": "high",
            "allowed_hours_utc": [5, 6, 7, 8],
            "open_anchor_hour_utc": 6,
            "overnight_allowed": False,
            "risk_filter_profile": "spread_shock_range_efficiency_vol_persistence",
            "thesis": "Let density expand one hour earlier and one hour later, but only on transition days whose spread, volatility persistence, and directional efficiency still look like the cleaner reclaim days rather than generic bridge noise.",
            "setup_summary": "Broaden the bridge cautiously, but keep the day-type quality gates so extra trades come from structurally similar handoff days instead of time expansion alone.",
            "entry_summary": "Enter on a density-restoration day-type reclaim when transition-day quality remains intact, the drift is stretched, reclaim confirmation is present, and the bridge remains outside neutral context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout with same-day flat only.",
            "risk_summary": "Density-restoration sibling intended to test whether better day selection can add trades without losing the seed economics.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "max_spread_shock_20": "1.20",
                "min_volatility_20": "0.00005",
                "min_volatility_ratio_5_to_20": "0.98",
                "min_range_efficiency_10": "0.34",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.66",
                "reclaim_confirmation_floor": "0.36",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
        },
    ]


def _compression_retest_breakout_templates() -> list[dict[str, object]]:
    family = "europe_open_compression_retest_breakout_research"
    return [
        {
            "title": "Europe Compression Retest Breakout Day Trade",
            "family": family,
            "entry_style": "compression_retest_breakout",
            "holding_bars": 24,
            "signal_threshold": 0.86,
            "stop_loss_pips": 5.6,
            "take_profit_pips": 8.2,
            "session_focus": "europe_open_compression_retest_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Trade Europe-open release only after a compressed range breaks and then retests from the live side, so the family stays orthogonal to pullback continuation and only participates once expansion proves it can hold a retest.",
            "setup_summary": "Require a compressed Europe-open range first, then wait for a clean directional break and a live-side retest instead of chasing the first impulse.",
            "entry_summary": "Enter on a compression retest breakout when expansion clears the compression ceiling, the retest holds above the live-side floor, and short-horizon trend remains aligned.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Orthogonal Europe-open breakout family that trades only after compression resolves and the first retest confirms persistence under realistic costs.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "max_range_width_10_pips": "8.0",
                "min_volatility_20": "0.00005",
                "required_volatility_bucket": "high",
                "breakout_zscore_floor": "0.42",
                "trend_ret_5_min": "0.00008",
                "retest_zscore_limit": "0.28",
                "retest_range_position_floor": "0.60",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Bridge Compression Retest Breakout",
            "family": family,
            "entry_style": "compression_retest_breakout",
            "holding_bars": 24,
            "signal_threshold": 0.85,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.1,
            "session_focus": "bridge_to_pre_overlap_compression_retest_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Test whether the compression-retest breakout clue gains density when the Europe bridge hour is allowed, but still require the break to survive a live-side retest before entering.",
            "setup_summary": "Require a compressed bridge-to-pre-overlap range, a directional break, and a held retest rather than a one-bar impulse.",
            "entry_summary": "Enter on a bridge compression retest breakout when expansion holds above the compression edge, the retest stays constructive, and the short-term trend remains aligned.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Bridge-inclusive sibling intended to add density without reverting to raw breakout chase behavior.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "max_range_width_10_pips": "8.2",
                "min_volatility_20": "0.00005",
                "required_volatility_bucket": "high",
                "breakout_zscore_floor": "0.40",
                "trend_ret_5_min": "0.000075",
                "retest_zscore_limit": "0.30",
                "retest_range_position_floor": "0.57",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Core Compression Retest Cost Guard",
            "family": family,
            "entry_style": "compression_retest_breakout",
            "holding_bars": 22,
            "signal_threshold": 0.87,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.9,
            "session_focus": "core_pre_overlap_compression_retest_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11],
            "thesis": "Keep the compression-retest breakout thesis inside the strongest Europe-core pocket and tighten cost guards so the family proves it can survive realistic friction before any broader release is admitted.",
            "setup_summary": "Require a compressed core pre-overlap range, a directional break, and a contained retest that does not drift back into balance.",
            "entry_summary": "Enter on a core compression retest breakout when the break remains live, the retest holds above the continuation floor, and costs stay inside the tighter guardrail.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Core Europe cost-guard sibling intended to preserve expectancy and stress survival before density expansion.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.85",
                "max_range_width_10_pips": "7.6",
                "min_volatility_20": "0.000055",
                "required_volatility_bucket": "high",
                "breakout_zscore_floor": "0.45",
                "trend_ret_5_min": "0.00008",
                "retest_zscore_limit": "0.26",
                "retest_range_position_floor": "0.63",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Fast Compression Retest Breakout",
            "family": family,
            "entry_style": "compression_retest_breakout",
            "holding_bars": 18,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.5,
            "session_focus": "fast_compression_retest_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Force the compression-retest breakout thesis to prove itself quickly, so the family can add opportunities without letting slow retests degrade into broad balance churn.",
            "setup_summary": "Require the same compressed range, directional break, and live-side retest, but demand a faster continuation resolution once the retest is complete.",
            "entry_summary": "Enter on a fast compression retest breakout when expansion survives the retest, the continuation bar resumes quickly, and range position stays on the live side.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Shorter-hold sibling designed to increase density while failing fast if the breakout cannot resume cleanly.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_range_width_10_pips": "8.0",
                "min_volatility_20": "0.00005",
                "required_volatility_bucket": "high",
                "breakout_zscore_floor": "0.43",
                "trend_ret_5_min": "0.000085",
                "retest_zscore_limit": "0.27",
                "retest_range_position_floor": "0.61",
                "require_recovery_ret_1": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
    ]


def _high_vol_momentum_band_templates() -> list[dict[str, object]]:
    family = "europe_open_high_vol_momentum_band_research"
    return [
        {
            "title": "Europe High-Vol Momentum Band Day Trade",
            "family": family,
            "entry_style": "session_momentum_band",
            "holding_bars": 28,
            "signal_threshold": 0.84,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.6,
            "session_focus": "high_vol_europe_momentum_band",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Trade Europe-open continuation only when a high-volatility directional band is already established and the move persists inside that band without needing a reset, reclaim, or breakout chase.",
            "setup_summary": "Require a Europe-open directional band first, then only continue when short-horizon carry, band location, and mean alignment all support persistence inside the band rather than a one-bar spike.",
            "entry_summary": "Enter on a high-volatility momentum band when return carry remains aligned, z-score stays inside the continuation band, price holds directional band location, and the recovery bar confirms persistence outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Orthogonal Europe-open continuation family that targets persistent directional band behavior instead of pullback resets or raw release extension.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00006",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00008",
                "continuation_zscore_floor": "0.24",
                "continuation_zscore_ceiling": "0.92",
                "continuation_range_position_floor": "0.66",
                "require_mean_location_alignment": "true",
                "require_ret_1_confirmation": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Bridge High-Vol Momentum Band",
            "family": family,
            "entry_style": "session_momentum_band",
            "holding_bars": 24,
            "signal_threshold": 0.82,
            "stop_loss_pips": 5.6,
            "take_profit_pips": 8.2,
            "session_focus": "bridge_to_pre_overlap_high_vol_momentum_band",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Restore the bridge hour to the high-volatility momentum-band thesis, but keep the directional band and mean-alignment gates tight so density rises only if the earlier session state is genuinely persistent.",
            "setup_summary": "Require the band to exist across the bridge-to-pre-overlap block, then only continue when the move stays inside the directional band and still outruns costs without falling back into balance.",
            "entry_summary": "Enter on a bridge high-volatility momentum band when carry remains aligned, z-score stays inside the continuation band, directional band location holds, and the recovery bar confirms persistence outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Density-oriented sibling that broadens the time pocket by one hour without relaxing the persistence band geometry.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "min_volatility_20": "0.00006",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00007",
                "continuation_zscore_floor": "0.22",
                "continuation_zscore_ceiling": "0.90",
                "continuation_range_position_floor": "0.64",
                "require_mean_location_alignment": "true",
                "require_ret_1_confirmation": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Core Cost-Guard Momentum Band",
            "family": family,
            "entry_style": "session_momentum_band",
            "holding_bars": 22,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.9,
            "session_focus": "core_cost_guard_high_vol_momentum_band",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10, 11],
            "thesis": "Keep the high-volatility momentum-band thesis inside the core Europe block and raise the band-quality floor so the family can avoid slow late-window drift and spread-heavy noise.",
            "setup_summary": "Require the band to remain directional inside the core block, then only continue when the move is still carrying with stronger z-score discipline and tighter cost control.",
            "entry_summary": "Enter on a core cost-guard momentum band when short-horizon carry stays aligned, the continuation band is tighter, directional band location holds, and mean alignment still supports persistence.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Cost-guard sibling intended to preserve robustness while still supporting enough density for EA-adjacent progression.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.85",
                "min_volatility_20": "0.000065",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00009",
                "continuation_zscore_floor": "0.28",
                "continuation_zscore_ceiling": "0.88",
                "continuation_range_position_floor": "0.68",
                "require_mean_location_alignment": "true",
                "require_ret_1_confirmation": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Fast-Fail High-Vol Momentum Band",
            "family": family,
            "entry_style": "session_momentum_band",
            "holding_bars": 18,
            "signal_threshold": 0.83,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.4,
            "session_focus": "fast_fail_high_vol_momentum_band",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11],
            "thesis": "Test the same high-volatility momentum-band clue under a faster fail horizon so the family can admit more persistent bands while rejecting slower drift before it leaks into stress failure.",
            "setup_summary": "Require the same directional band and mean alignment, but force the continuation to prove itself quickly instead of surviving on slow persistence through the late Europe block.",
            "entry_summary": "Enter on a fast-fail high-volatility momentum band when carry is aligned, the continuation band remains intact, directional band location holds, and the recovery bar confirms persistence with enough speed to justify the shorter horizon.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Short-horizon sibling that widens opportunity count slightly while demanding faster post-entry confirmation to preserve robustness.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "min_volatility_20": "0.00006",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00008",
                "continuation_zscore_floor": "0.22",
                "continuation_zscore_ceiling": "0.86",
                "continuation_range_position_floor": "0.64",
                "require_mean_location_alignment": "true",
                "require_ret_1_confirmation": "true",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
    ]


def _release_persistence_templates() -> list[dict[str, object]]:
    family = "europe_open_release_persistence_research"
    return [
        {
            "title": "Europe Release Persistence Expansion Day Trade",
            "family": family,
            "entry_style": "volatility_expansion",
            "holding_bars": 24,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.6,
            "take_profit_pips": 8.1,
            "session_focus": "europe_open_release_persistence",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11],
            "thesis": "Trade Europe-open directional continuation only when the initial release is already expanding cleanly, volatility stays elevated, and the move is persisting rather than resetting into a pullback geometry.",
            "setup_summary": "Require a live Europe release first, then only act when directional persistence remains active and the move is still outrunning mean-reversion drift instead of waiting for a retest or reclaim.",
            "entry_summary": "Enter on release persistence when the expansion is already directional, z-score remains above the breakout floor, short-horizon return stays strong, and the move still sits outside blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Orthogonal Europe-open continuation family that targets clean release persistence instead of pullback or reclaim geometry.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00006",
                "required_volatility_bucket": "high",
                "breakout_zscore_floor": "0.52",
                "ret_5_floor": "0.00009",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Bridge Release Persistence Expansion",
            "family": family,
            "entry_style": "volatility_expansion",
            "holding_bars": 22,
            "signal_threshold": 0.86,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.8,
            "session_focus": "bridge_to_pre_overlap_release_persistence",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Restore the bridge hour to the release-persistence thesis, but only when volatility stays high and the move is still extending cleanly enough to justify continuation without waiting for a reset.",
            "setup_summary": "Require a Europe bridge-to-pre-overlap directional release first, then only take the continuation when the move is still expanding with enough quality to outrun costs.",
            "entry_summary": "Enter on bridge release persistence when momentum remains active, z-score stays above the persistence floor, the short-horizon move is still extending, and the path remains outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Density-first sibling that broadens the time block by one hour while keeping the release-persistence thesis strict.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "min_volatility_20": "0.00006",
                "required_volatility_bucket": "high",
                "breakout_zscore_floor": "0.50",
                "ret_5_floor": "0.00008",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Core Cost-Guard Release Persistence",
            "family": family,
            "entry_style": "volatility_expansion",
            "holding_bars": 20,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.5,
            "session_focus": "core_pre_overlap_release_persistence",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Keep the release-persistence thesis inside the core pre-overlap block and raise the expansion quality bar so the family can stay orthogonal to late weak drift and spread-heavy bridge noise.",
            "setup_summary": "Require the Europe release to remain directional inside the core pre-overlap block, then only continue when the move is still expanding with stronger persistence quality and tighter cost control.",
            "entry_summary": "Enter on core release persistence when volatility is high, z-score stays above the stricter breakout floor, the short-horizon return remains strong, and the continuation still avoids blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Cost-guard sibling intended to keep continuation quality high while preserving enough density to matter for EA progression.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.85",
                "min_volatility_20": "0.000065",
                "required_volatility_bucket": "high",
                "breakout_zscore_floor": "0.56",
                "ret_5_floor": "0.00010",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
        {
            "title": "Europe Fast-Fail Release Persistence",
            "family": family,
            "entry_style": "volatility_expansion",
            "holding_bars": 16,
            "signal_threshold": 0.87,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.0,
            "session_focus": "fast_fail_release_persistence",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11],
            "thesis": "Test the same Europe release-persistence clue under a faster fail horizon so the family can admit more live expansions while discarding slower persistence states before they leak stress performance.",
            "setup_summary": "Require the same high-volatility directional release, but force the continuation to prove itself quickly instead of surviving on later drift through the pre-overlap block.",
            "entry_summary": "Enter on fast-fail release persistence when the move is already expanding, z-score remains above the persistence floor, the short-horizon move is still accelerating, and the continuation avoids blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout.",
            "risk_summary": "Short-horizon sibling that trades a broader opportunity set but demands faster post-entry continuation to preserve robustness.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "min_volatility_20": "0.00006",
                "required_volatility_bucket": "high",
                "breakout_zscore_floor": "0.50",
                "ret_5_floor": "0.00008",
                "exclude_context_bucket": "mean_reversion_context",
            },
        },
    ]


def _high_vol_pullback_persistence_templates() -> list[dict[str, object]]:
    family = "europe_open_high_vol_pullback_persistence_research"
    return [
        {
            "title": "Europe High-Vol Pullback Persistence Day Trade",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 22,
            "signal_threshold": 0.92,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.6,
            "session_focus": "full_pre_overlap_high_vol_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Trade high-volatility Europe pre-overlap pullback persistence only when the initial release is already directional, the pullback remains shallow, and the branch keeps the stress-surviving continuation profile seen in the strongest late-window clue while explicitly searching for more density.",
            "setup_summary": "Require a real Europe-morning directional release first, then only take shallow continuation pullbacks that remain inside the high-volatility persistence band instead of slipping into broad retest or reversal behavior.",
            "entry_summary": "Enter on a high-volatility pullback persistence continuation when the release is already active, the pullback stays inside the buffered continuation band, volatility remains high, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Blank-slate high-volatility continuation family aimed at restoring trade density without sacrificing positive expectancy or stress survival.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00007",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00008",
                "pullback_zscore_limit": "0.35",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Bridge-To-Pre-Overlap High-Vol Pullback Persistence",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 22,
            "signal_threshold": 0.91,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.6,
            "session_focus": "bridge_to_pre_overlap_high_vol_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Restore the Europe bridge hour to the high-volatility persistence clue, but keep the same shallow-pullback geometry so density rises only if the earlier high-vol release hour is genuinely supportive.",
            "setup_summary": "Require the same directional Europe release and shallow high-volatility pullback, but allow the earlier bridge hour to contribute if it still behaves like persistence rather than an opening scramble.",
            "entry_summary": "Enter on a high-volatility pullback persistence continuation when the release remains directional through the bridge hour, the pullback stays inside the buffered continuation band, and the recovery bar resumes outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Density-first sibling that widens time coverage by one hour without relaxing the high-volatility context gate.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00007",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00007",
                "pullback_zscore_limit": "0.35",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Buffered Open High-Vol Pullback Persistence",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 24,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.8,
            "session_focus": "open_inclusive_high_vol_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Restore the full Europe pre-overlap block to the high-volatility persistence clue and slightly widen the continuation band, but keep the volatility bucket and cost control tight so density can rise without turning into a broad pullback-release family.",
            "setup_summary": "Require a directional Europe release first, then allow a slightly wider high-volatility continuation pullback as long as the move still resumes cleanly and stays outside mean-reversion context.",
            "entry_summary": "Enter on a buffered high-volatility pullback persistence continuation when the release is already active, the pullback remains inside the widened continuation band, volatility stays high, and the recovery bar resumes direction cleanly.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Density-first sibling that broadens the time pocket and pullback band while keeping the family anchored to high-volatility continuation logic.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "min_volatility_20": "0.000065",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00007",
                "pullback_zscore_limit": "0.38",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Buffered Pre-Overlap High-Vol Pullback Persistence",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 24,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.9,
            "session_focus": "buffered_pre_overlap_high_vol_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Keep the existing pre-overlap window but widen the pullback band and slightly relax directional confirmation, so the family can collect more continuation resets without drifting into weak broad-release behavior.",
            "setup_summary": "Require the same high-volatility directional Europe release, then allow a slightly wider buffered pullback as long as the trend context and recovery bar still confirm continuation.",
            "entry_summary": "Enter on a buffered pre-overlap high-volatility pullback continuation when the pullback remains controlled, volatility stays high, and the recovery bar resumes the established direction outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Density-first sibling that loosens pullback geometry without reopening the earlier bridge hour.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.000065",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00007",
                "pullback_zscore_limit": "0.39",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Short-Hold High-Vol Pullback Persistence",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 18,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.1,
            "take_profit_pips": 7.2,
            "session_focus": "short_hold_high_vol_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Keep the high-volatility persistence clue but shorten time-in-trade so the family can accept slightly more entry opportunities while still demanding fast continuation and strong cost discipline.",
            "setup_summary": "Require a directional Europe release and a shallow high-volatility pullback, then force the branch to prove itself quickly instead of surviving on slow drift through the later pre-overlap window.",
            "entry_summary": "Enter on a short-hold high-volatility pullback persistence continuation when the release remains directional, the pullback stays controlled, and the recovery bar resumes with enough speed to justify the tighter exit horizon.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Density-first sibling that trades a slightly larger opportunity set but demands faster post-entry confirmation to preserve stress survival.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.000065",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00006",
                "pullback_zscore_limit": "0.37",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
    ]


def _high_vol_pullback_reset_templates() -> list[dict[str, object]]:
    family = "europe_open_high_vol_pullback_reset_research"
    return [
        {
            "title": "Europe High-Vol Pullback Reset Day Trade",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 22,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.7,
            "session_focus": "bridge_to_pre_overlap_high_vol_pullback_reset",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Reopen discovery around the high-volatility pullback clue by treating the continuation as a buffered reset rather than a pure persistence branch, so the family can add density without drifting into broad release-chase behavior.",
            "setup_summary": "Require a directional Europe release first, then accept a buffered high-volatility pullback reset across the bridge-to-pre-overlap block as long as the move still resolves back into trend instead of mean reversion.",
            "entry_summary": "Enter on a high-volatility pullback reset continuation when the release remains directional, the reset stays inside a buffered continuation band, volatility stays high, and the recovery bar resumes outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Blank-slate high-volatility reset family aimed at converting the persistence clue into a denser continuation profile without sacrificing cost realism.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.000065",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00007",
                "pullback_zscore_limit": "0.39",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Buffered Core High-Vol Pullback Reset",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 24,
            "signal_threshold": 0.89,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.9,
            "session_focus": "core_pre_overlap_high_vol_pullback_reset",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Keep the same high-volatility pullback clue inside the core pre-overlap window, but widen the reset band so the family can collect more valid continuation re-entries while preserving the stress-surviving context filters.",
            "setup_summary": "Require the same high-volatility directional Europe release, then allow a wider buffered reset inside the core pre-overlap block when the move still looks like continuation rather than a full balance handoff.",
            "entry_summary": "Enter on a buffered core high-volatility pullback reset when the release remains active, the reset stays inside the widened band, and the recovery bar resumes direction outside mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Density-oriented high-volatility reset sibling focused on lifting trade count in the core Europe pre-overlap block.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.000065",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00007",
                "pullback_zscore_limit": "0.40",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Fast Re-Entry High-Vol Pullback Reset",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 18,
            "signal_threshold": 0.89,
            "stop_loss_pips": 5.1,
            "take_profit_pips": 7.3,
            "session_focus": "fast_reentry_high_vol_pullback_reset",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Test whether the high-volatility pullback clue becomes denser when the branch explicitly demands a faster re-entry instead of slower persistence, so the family can open more opportunities while failing quickly when continuation is weak.",
            "setup_summary": "Require the same directional Europe release and high-volatility reset, but emphasize fast re-entry through a shorter hold and slightly tighter stop-target geometry.",
            "entry_summary": "Enter on a fast re-entry high-volatility pullback reset when the release remains directional, the reset stays controlled, and the recovery bar resumes with enough speed to justify the shorter exit horizon.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Density-oriented high-volatility reset sibling that trades a slightly larger opportunity set but still enforces fast continuation and cost discipline.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.000065",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00006",
                "pullback_zscore_limit": "0.38",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
    ]


def _high_vol_pullback_regime_templates() -> list[dict[str, object]]:
    family = "europe_open_high_vol_pullback_regime_research"
    return [
        {
            "title": "Europe High-Vol Pullback Regime Quality",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 22,
            "signal_threshold": 0.89,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.6,
            "session_focus": "core_pre_overlap_high_vol_pullback_regime_quality",
            "volatility_preference": "high_to_persistent",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Reopen the strongest high-volatility Europe pullback clue through regime quality instead of hour pruning, so the branch can admit more persistent continuation resets while explicitly filtering out the weak late-reset states that broke the sparse walk-forward window.",
            "setup_summary": "Require a directional Europe release first, then only accept pullback resets when the immediate regime still has enough realized activity, enough usable range, and enough mean-location alignment to behave like continuation instead of late handoff noise.",
            "entry_summary": "Enter on a high-volatility pullback regime-quality continuation when the directional release is already active, the reset stays shallow inside the live range, current realized activity remains persistent relative to the background window, and the recovery bar resumes on the correct side of the short-term mean.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Regime-conditioned high-volatility continuation family aimed at increasing density without reopening weak pre-overlap reset states.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "0.92",
                "trend_ret_5_min": "0.00006",
                "pullback_zscore_limit": "0.42",
                "pullback_range_position_floor": "0.49",
                "recovery_zscore_floor": "0.0",
                "require_mean_location_alignment": "true",
                "max_spread_to_range_10": "0.42",
                "min_intrabar_range_pips": "1.0",
                "min_range_width_10_pips": "4.8",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Bridge High-Vol Pullback Regime Quality",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 20,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.1,
            "take_profit_pips": 7.4,
            "session_focus": "bridge_to_pre_overlap_high_vol_pullback_regime_quality",
            "volatility_preference": "high_to_persistent",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Add the Europe bridge hour back into the high-volatility pullback clue only when the reset quality still looks like persistent continuation rather than opening scramble, using regime-state guards instead of a blunt hour exclusion.",
            "setup_summary": "Require the same directional Europe release and shallow reset, then admit the bridge hour only when current realized activity remains persistent, the live range is large enough to absorb costs, and the recovery sits on the continuation side of the short-term mean.",
            "entry_summary": "Enter on a bridge-to-pre-overlap high-volatility pullback regime continuation when the release remains active, the reset stays shallow, current realized activity remains elevated versus the background window, and the recovery bar resumes with mean-location alignment.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Bridge-inclusive regime sibling that tries to restore density while still blocking weak opening and weak late-reset states.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "0.98",
                "trend_ret_5_min": "0.000055",
                "pullback_zscore_limit": "0.44",
                "pullback_range_position_floor": "0.48",
                "recovery_zscore_floor": "0.0",
                "require_mean_location_alignment": "true",
                "max_spread_to_range_10": "0.40",
                "min_intrabar_range_pips": "1.0",
                "min_range_width_10_pips": "4.7",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Persistent Reset High-Vol Pullback",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 24,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.8,
            "session_focus": "persistent_reset_high_vol_pullback_regime_quality",
            "volatility_preference": "persistent",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Treat the clue as a persistent-reset problem rather than a strict high-bucket problem, so the family can pick up quieter but still live continuation states in the weak window without drifting back into broad pullback-release behavior.",
            "setup_summary": "Require a directional Europe release first, then accept resets only when current realized activity stays elevated relative to the background window, the local range remains usable, and price still recovers on the continuation side of the short-term mean.",
            "entry_summary": "Enter on a persistent-reset high-volatility pullback continuation when the release is active, the reset remains shallow, current realized activity still dominates the background window, and the recovery resumes with range-position and mean-location alignment.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Persistent-reset sibling intended to lift walk-forward density in the weak window without simply widening the family into medium-volatility drift.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "1.02",
                "trend_ret_5_min": "0.000055",
                "pullback_zscore_limit": "0.45",
                "pullback_range_position_floor": "0.47",
                "recovery_zscore_floor": "0.0",
                "require_mean_location_alignment": "true",
                "max_spread_to_range_10": "0.45",
                "min_intrabar_range_pips": "0.95",
                "min_range_width_10_pips": "4.5",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Short-Hold Regime Quality Pullback",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 18,
            "signal_threshold": 0.91,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.1,
            "session_focus": "short_hold_high_vol_pullback_regime_quality",
            "volatility_preference": "high_to_persistent",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "thesis": "Force the high-volatility pullback clue to prove itself quickly under regime-quality conditions, so the family can admit more resets while still discarding slower continuation states before they leak stress performance.",
            "setup_summary": "Require a directional Europe release, a shallow regime-qualified reset, and a recovery that resumes on the continuation side of the mean quickly enough to justify the shorter hold horizon.",
            "entry_summary": "Enter on a short-hold regime-quality pullback continuation when current realized activity remains live, the reset stays shallow inside the active range, and the recovery bar resumes with mean-location alignment and controlled costs.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Short-hold regime sibling designed to trade a slightly larger opportunity set without allowing slow continuation decay to destroy stress survival.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "0.90",
                "trend_ret_5_min": "0.00006",
                "pullback_zscore_limit": "0.41",
                "pullback_range_position_floor": "0.50",
                "recovery_zscore_floor": "0.0",
                "require_mean_location_alignment": "true",
                "max_spread_to_range_10": "0.40",
                "min_intrabar_range_pips": "1.1",
                "min_range_width_10_pips": "4.8",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
    ]


def _high_vol_pullback_chronology_templates() -> list[dict[str, object]]:
    family = "europe_open_high_vol_pullback_chronology_research"
    return [
        {
            "title": "Europe Window-Two High-Vol Pullback Quality",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 24,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.9,
            "session_focus": "window_two_high_vol_pullback_quality",
            "volatility_preference": "high_to_persistent",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Target the weak middle walk-forward window directly by requiring high-volatility pullbacks to show persistent realized activity, usable range width, and mean-location alignment before continuation is allowed, instead of widening the family through generic pullback geometry.",
            "setup_summary": "Require an established Europe directional release first, then only accept a pullback reset when current realized activity still dominates the background window, the live range stays large enough to absorb costs, and the recovery remains on the continuation side of the mean.",
            "entry_summary": "Enter on a window-two high-volatility pullback continuation when persistence quality stays elevated through the reset, the pullback remains controlled inside the active range, and the recovery bar resumes with mean-location alignment.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Chronology-aware high-volatility pullback family aimed at repairing the weak middle walk-forward window without opening a new hour-only branch.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "max_spread_to_range_10": "0.36",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.05",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00007",
                "pullback_zscore_limit": "0.40",
                "pullback_range_position_floor": "0.50",
                "recovery_zscore_floor": "0.0",
                "require_mean_location_alignment": "true",
                "min_intrabar_range_pips": "1.0",
                "min_range_width_10_pips": "4.8",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Mid-Window Persistent Pullback",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 22,
            "signal_threshold": 0.92,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.5,
            "session_focus": "mid_window_persistent_high_vol_pullback",
            "volatility_preference": "persistent",
            "allowed_hours_utc": [8, 9, 10, 11],
            "thesis": "Treat the bad middle window as a persistence-quality problem by insisting on higher short-vs-background volatility and stronger continuation-side location before a reset is tradable.",
            "setup_summary": "Require the same directional Europe release, then only admit the reset when realized activity remains persistently elevated, spread stays small relative to range, and the pullback does not lose continuation-side location.",
            "entry_summary": "Enter on a persistent mid-window pullback continuation when the reset remains shallow, realized activity still dominates the background window, and the recovery bar resumes with stronger continuation confirmation.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Mid-window sibling intended to keep hour 9 tradable only when the regime quality is materially better than the weak default states.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_spread_to_range_10": "0.34",
                "min_volatility_20": "0.000058",
                "min_volatility_ratio_5_to_20": "1.12",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.000075",
                "pullback_zscore_limit": "0.38",
                "pullback_range_position_floor": "0.54",
                "recovery_zscore_floor": "0.03",
                "require_mean_location_alignment": "true",
                "min_intrabar_range_pips": "1.1",
                "min_range_width_10_pips": "5.0",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Buffered Chronology Pullback",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 26,
            "signal_threshold": 0.89,
            "stop_loss_pips": 5.5,
            "take_profit_pips": 8.0,
            "session_focus": "buffered_chronology_high_vol_pullback",
            "volatility_preference": "high_to_persistent",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "thesis": "Allow a slightly wider reset only when chronology-aware regime filters confirm the continuation state remains healthy, so density can rise without reopening the weak middle-window noise pocket.",
            "setup_summary": "Require a live Europe directional release first, then admit a buffered pullback only when realized activity, range width, and mean-location alignment all remain continuation-friendly.",
            "entry_summary": "Enter on a buffered chronology pullback continuation when the reset stays controlled inside the active range, spread-to-range remains favorable, and the recovery resumes in the correct direction.",
            "exit_summary": "Exit via fixed stop, fixed target, or 26-bar timeout.",
            "risk_summary": "Density-oriented chronology sibling that widens pullback geometry but only inside stronger regime-state conditions.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "max_spread_to_range_10": "0.38",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.0",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00007",
                "pullback_zscore_limit": "0.43",
                "pullback_range_position_floor": "0.49",
                "recovery_zscore_floor": "0.0",
                "require_mean_location_alignment": "true",
                "min_intrabar_range_pips": "1.0",
                "min_range_width_10_pips": "5.1",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
        {
            "title": "Europe Fast Recovery Chronology Pullback",
            "family": family,
            "entry_style": "pullback_continuation",
            "holding_bars": 18,
            "signal_threshold": 0.93,
            "stop_loss_pips": 5.1,
            "take_profit_pips": 7.3,
            "session_focus": "fast_recovery_chronology_high_vol_pullback",
            "volatility_preference": "high_to_persistent",
            "allowed_hours_utc": [8, 9, 10, 11],
            "thesis": "Force the repaired middle-window clue to prove itself quickly, so weak hour-9 resets are filtered out unless the regime recovers with enough speed and persistence to survive stress.",
            "setup_summary": "Require a directional Europe release, then only trade a short-horizon reset when realized activity remains elevated, mean-location alignment holds, and the recovery clears a higher z-score floor quickly.",
            "entry_summary": "Enter on a fast-recovery chronology pullback continuation when the reset remains shallow, regime quality stays high, and the recovery resumes fast enough to justify the shorter hold horizon.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Short-hold chronology sibling aimed at preserving stress pass while targeting additional middle-window density.",
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.85",
                "max_spread_to_range_10": "0.33",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.10",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00008",
                "pullback_zscore_limit": "0.37",
                "pullback_range_position_floor": "0.55",
                "recovery_zscore_floor": "0.05",
                "require_mean_location_alignment": "true",
                "min_intrabar_range_pips": "1.15",
                "min_range_width_10_pips": "5.0",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
        },
    ]


def _draft_from_template(template: dict[str, object], digest, settings: Settings, *, index: int) -> CandidateDraft:
    highlights = list(digest.highlights)
    contradictions = list(digest.contradictions)
    citations = list(digest.source_citations)
    book_prior = _book_prior_assessment(template, digest)
    quality_flags = ["exploration_seed", "corpus_aligned", "new_family_queue"]
    common_notes = [
        "Generated by the Codex-guided day-trading exploration lane with deterministic governed evaluation.",
        "Candidate exploration uses the current path-aware label contract and a family-distinct entry-style template set.",
        f"Book alignment score: {book_prior['book_alignment_score']:.3f}.",
    ]
    if book_prior["book_veto_reasons"]:
        quality_flags.append("book_prior_veto_watch")
        common_notes.append(f"Book-prior veto watch: {', '.join(book_prior['book_veto_reasons'])}.")
    candidate_id = next_candidate_id(settings)
    highlight = (
        highlights[index % len(highlights)]
        if highlights
        else "Corpus digest favors session structure, disciplined exits, and explicit intraday risk control."
    )
    return CandidateDraft(
        candidate_id=candidate_id,
        family=str(template.get("family") or "day_trading"),
        title=template["title"],
        thesis=f'{template["thesis"]} Corpus anchor: {highlight}',
        source_citations=citations or ["SRC-001"],
        strategy_hypothesis=highlight,
        market_context=MarketContextSummary(
            session_focus=template["session_focus"],
            volatility_preference=template["volatility_preference"],
            directional_bias="both",
            execution_notes=[
                "Use canonical OANDA bid/ask data for research.",
                "Keep downstream parity and forward artifacts out of research ranking and queue policy.",
                f'Exploration archetype: {template["entry_style"]}.',
                f"Open-anchor hour UTC: {book_prior['open_anchor_hour_utc']}.",
                "No overnight carry is permitted for these open-anchor momentum families.",
            ],
            allowed_hours_utc=template["allowed_hours_utc"],
        ),
        market_rationale=MarketRationale(
            market_behavior=template["thesis"],
            edge_mechanism=template["entry_summary"],
            persistence_reason=(
                f"Expect the {template['session_focus'].replace('_', ' ')} structure to recur during the "
                "Europe-open anchor phase with a shorter holding horizon than the late-morning persistence families."
            ),
            failure_regimes=[
                "the opening anchor impulse fails to carry beyond the initial phase",
                "costs, spread shock, or realized-volatility decay consume the short-horizon edge",
                "the family only survives one chronological regime and collapses in the middle walk-forward window",
            ],
            validation_focus=[
                "confirm the edge persists across anchored Europe-open phases rather than one isolated hour",
                "verify trade density stays sufficient after spread, realized-volatility, and calendar-risk filters",
                "retire the family if the edge only survives one exceptional market patch or late-morning decay hole",
            ],
        ),
        setup_summary=template["setup_summary"],
        entry_summary=template["entry_summary"],
        exit_summary=template["exit_summary"],
        risk_summary=template["risk_summary"],
        notes=list(common_notes),
        quality_flags=list(quality_flags),
        contradiction_summary=list(contradictions),
        critic_notes=[
            "QuantCritic: prefer candidates that survive broader time exits without losing expectancy to costs.",
            "RiskCritic: reject if wider stop/target geometry simply hides weak trade density or drawdown.",
            "ExecutionRealist: this family must still earn parity through research-stage robustness first.",
        ],
        custom_filters=[
            {"name": name, "rule": rule}
            for name, rule in dict(template.get("custom_filters") or {}).items()
        ],
        enable_news_blackout=bool(template.get("enable_news_blackout")),
        book_alignment_score=book_prior["book_alignment_score"],
        book_veto_reasons=book_prior["book_veto_reasons"],
        open_anchor_hour_utc=book_prior["open_anchor_hour_utc"],
        max_hold_bars=book_prior["max_hold_bars"],
        overnight_allowed=book_prior["overnight_allowed"],
        risk_filter_profile=book_prior["risk_filter_profile"],
        entry_style=template["entry_style"],
        holding_bars=template["holding_bars"],
        signal_threshold=template["signal_threshold"],
        stop_loss_pips=template["stop_loss_pips"],
        take_profit_pips=template["take_profit_pips"],
    )


def _scan_report_path(settings: Settings) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return settings.paths().experiments_dir / f"day_trading_behavior_scan_{timestamp}.json"


def _report_path(settings: Settings) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return settings.paths().experiments_dir / f"day_trading_exploration_{timestamp}.json"
