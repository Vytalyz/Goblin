from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError

from agentic_forex.approval.service import publish_candidate
from agentic_forex.backtesting.engine import run_backtest, run_stress_test
from agentic_forex.config import Settings
from agentic_forex.corpus.catalog import build_digest, catalog_corpus
from agentic_forex.evals.graders import grade_candidate
from agentic_forex.evals.robustness import build_robustness_report
from agentic_forex.forward.service import load_forward_stage_report
from agentic_forex.governance.provenance import build_data_provenance, build_environment_snapshot
from agentic_forex.governance.readiness import required_evidence, resolve_readiness_status
from agentic_forex.governance.trial_ledger import append_trial_entry
from agentic_forex.ml.train import train_models
from agentic_forex.mt5.service import generate_mt5_packet, load_latest_mt5_validation, validate_mt5_practice
from agentic_forex.policy.ftmo import score_ftmo_fit
from agentic_forex.runtime.security import ReadPolicy
from agentic_forex.utils.ids import next_candidate_id
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import (
    AccountModel,
    CandidateDraft,
    CriticNote,
    ExecutionCostModel,
    NewsPolicy,
    ReviewContext,
    RiskEnvelope,
    RouteDecision,
    SessionPolicy,
    SetupLogic,
    ShadowMLPolicy,
    StrategySpec,
    ValidationProfile,
)


def default_execution_cost_fields(
    settings: Settings,
    *,
    family: str,
    session_focus: str,
) -> dict[str, object]:
    is_scalping = family == "scalping"
    default_slippage_pips = 0.05 if is_scalping else 0.0
    default_fill_delay_ms = 250 if is_scalping else 0
    default_broker_fee_model = (
        "oanda_spread_only" if settings.data.canonical_source == "oanda" else "spread_plus_commission"
    )
    notes = [
        "Canonical research source is OANDA bid/ask data.",
        "Versioned execution model for research, parity, and forward-stage evaluation.",
        "OANDA spot FX is modeled as spread-only by default unless a non-zero commission is specified.",
    ]
    if is_scalping:
        notes.append("Scalping defaults include explicit fill-delay and round-turn broker-cost assumptions.")
    return {
        "canonical_source": settings.data.canonical_source,
        "spread_mode": "bid_ask",
        "broker_fee_model": default_broker_fee_model,
        "spread_multiplier": 1.0,
        "slippage_pips": default_slippage_pips,
        "commission_per_standard_lot_usd": 0.0,
        "fill_delay_ms": default_fill_delay_ms,
        "liquidity_session_assumption": session_focus,
        "tick_model_assumption": "oanda_bid_ask_m1",
        "notes": notes,
    }


def build_tool_registry() -> dict[str, object]:
    return {
        "collect_corpus_digest": collect_corpus_digest,
        "route_strategy_family": route_strategy_family,
        "finalize_candidate": finalize_candidate,
        "compile_strategy_spec": compile_strategy_spec_tool,
        "prepare_review_context": prepare_review_context,
        "finalize_review_packet": finalize_review_packet,
        "publish_candidate_manifest": publish_candidate_manifest,
        "generate_mt5_packet": generate_mt5_packet_tool,
        "validate_mt5_practice": validate_mt5_practice_tool,
    }


def collect_corpus_digest(*, payload: dict, settings: Settings, config: dict, read_policy: ReadPolicy) -> dict:
    if not settings.catalog_path.exists():
        mirror_value = payload.get("mirror_path")
        if not mirror_value:
            raise ValueError("mirror_path is required before the corpus has been cataloged.")
        mirror_path = Path(mirror_value)
        catalog_corpus(mirror_path, settings, read_policy)
    digest = build_digest(
        family=payload["candidate_family"],
        settings=settings,
        max_sources=int(payload.get("max_sources", 5)),
    )
    return digest.model_dump(mode="json")


def route_strategy_family(*, payload: dict, settings: Settings, config: dict, read_policy: ReadPolicy) -> dict:
    family = str(payload.get("candidate_family", "")).strip().lower()
    if family not in {"scalping", "day_trading"}:
        family = "scalping" if "scalp" in str(payload).lower() else "day_trading"
    next_node = "scalping_analyst" if family == "scalping" else "day_trading_analyst"
    return RouteDecision(next_node=next_node, payload=payload, rationale=f"Routed to {family} strategist.").model_dump(
        mode="json"
    )


def finalize_candidate(*, payload: dict, settings: Settings, config: dict, read_policy: ReadPolicy) -> dict:
    data = dict(payload)
    data["candidate_id"] = data.get("candidate_id") or next_candidate_id(settings)
    candidate = CandidateDraft.model_validate(data)
    existing_candidate_path = settings.paths().reports_dir / candidate.candidate_id / "candidate.json"
    if existing_candidate_path.exists():
        candidate = candidate.model_copy(update={"candidate_id": next_candidate_id(settings)})
    output_path = settings.paths().reports_dir / candidate.candidate_id / "candidate.json"
    write_json(output_path, candidate.model_dump(mode="json"))
    append_trial_entry(
        settings,
        candidate_id=candidate.candidate_id,
        family=candidate.family,
        stage="discovered",
        artifact_paths={"candidate_path": str(output_path)},
    )
    return candidate.model_dump(mode="json")


def compile_strategy_spec_tool(*, payload: dict, settings: Settings, config: dict, read_policy: ReadPolicy) -> dict:
    candidate = CandidateDraft.model_validate(payload)
    candidate_path = settings.paths().reports_dir / candidate.candidate_id / "candidate.json"
    if not candidate_path.exists():
        write_json(candidate_path, candidate.model_dump(mode="json"))
    is_scalping = candidate.family == "scalping"
    currencies = [part for part in settings.data.instrument.split("_") if part]
    session_hours = candidate.market_context.allowed_hours_utc or (
        [7, 8, 9, 10, 11, 12] if is_scalping and candidate.entry_style == "session_breakout" else []
    )
    scalping_volatility_floor = (
        "0.00012"
        if candidate.market_context.volatility_preference.strip().lower() in {"high", "high_only"}
        else "0.00005"
    )
    directional_intraday_filters = _scalping_style_filters(candidate.entry_style, scalping_volatility_floor)
    structured_intraday_filters = _day_trading_style_filters(candidate.entry_style)
    filters = [
        {"name": "volatility_preference", "rule": candidate.market_context.volatility_preference},
        {"name": "quality_flags", "rule": ", ".join(candidate.quality_flags) or "none"},
    ]
    if directional_intraday_filters:
        filters.extend(directional_intraday_filters)
    elif structured_intraday_filters:
        filters.extend(structured_intraday_filters)
    if candidate.custom_filters:
        filters.extend(candidate.custom_filters)
    validation_profile = ValidationProfile(
        minimum_test_trade_count=settings.validation.minimum_test_trade_count,
        out_of_sample_profit_factor_floor=settings.validation.out_of_sample_profit_factor_floor,
        expectancy_floor=settings.validation.expectancy_floor,
        stress_profit_factor_floor=settings.validation.stress_profit_factor_floor,
        drawdown_review_trigger_pct=settings.validation.drawdown_review_trigger_pct,
        stress_spread_multiplier=settings.validation.stress_spread_multiplier,
        stress_slippage_pips=settings.validation.stress_slippage_pips,
        stress_fill_delay_ms=settings.validation.stress_fill_delay_ms,
        walk_forward_windows=settings.validation.walk_forward_windows,
        walk_forward_mode=settings.validation.walk_forward_mode,
        walk_forward_profit_factor_floor=settings.validation.walk_forward_profit_factor_floor,
        walk_forward_min_trades_per_window=settings.validation.walk_forward_min_trades_per_window,
        walk_forward_min_window_days=settings.validation.walk_forward_min_window_days,
        time_split=(0.6, 0.2, 0.2),
    )
    cost_defaults = default_execution_cost_fields(
        settings,
        family=candidate.family,
        session_focus=candidate.market_context.session_focus,
    )
    news_blackout_enabled = is_scalping or candidate.enable_news_blackout
    spec = StrategySpec(
        candidate_id=candidate.candidate_id,
        family=candidate.family,
        benchmark_group_id=candidate.candidate_id,
        variant_name="base",
        instrument=settings.data.instrument,
        execution_granularity=settings.data.execution_granularity,
        context_granularities=["M5", "M15"] if is_scalping else ["M5", "M15", "H1"],
        session_policy=SessionPolicy(
            name="candidate_defined_intraday",
            allowed_sessions=["europe_open_breakout"]
            if is_scalping and candidate.entry_style == "session_breakout"
            else ["intraday_active_windows"],
            allowed_hours_utc=session_hours,
            notes=[candidate.market_context.session_focus] + candidate.market_context.execution_notes,
        ),
        side_policy=candidate.market_context.directional_bias,
        setup_logic=SetupLogic(
            style=candidate.entry_style,
            summary=candidate.setup_summary,
            trigger_conditions=[
                candidate.strategy_hypothesis,
                candidate.entry_summary,
            ],
        ),
        market_rationale=candidate.market_rationale,
        filters=filters,
        entry_logic=[
            candidate.entry_summary,
            f"Signal threshold {candidate.signal_threshold}",
        ],
        exit_logic=[
            candidate.exit_summary,
            f"Time exit after {candidate.holding_bars} bars",
        ]
        + (
            [f"Trailing stop {candidate.trailing_stop_pips} pips"]
            if candidate.trailing_stop_enabled and candidate.trailing_stop_pips
            else []
        ),
        risk_policy={
            "stop_loss_pips": candidate.stop_loss_pips,
            "take_profit_pips": candidate.take_profit_pips,
            "trailing_stop_enabled": candidate.trailing_stop_enabled,
            "trailing_stop_pips": candidate.trailing_stop_pips,
            "max_risk_per_trade_pct": settings.policy.default_risk_per_trade_pct,
            "notes": [candidate.risk_summary],
        },
        account_model=AccountModel(
            initial_balance=settings.policy.default_initial_balance,
            account_currency=settings.policy.default_account_currency,
            risk_per_trade_pct=settings.policy.default_risk_per_trade_pct,
            leverage=settings.policy.default_leverage,
            contract_size=settings.policy.default_contract_size,
            pip_value_per_standard_lot=settings.policy.default_pip_value_per_standard_lot,
            margin_buffer_pct=settings.policy.default_margin_buffer_pct,
            max_total_exposure_lots=settings.policy.default_max_total_exposure_lots,
            notes=[
                "Account model is used for soft policy scoring and risk-aware backtest metrics.",
                "Pair universe support remains deferred until EUR/USD is stable.",
            ],
        ),
        news_policy=NewsPolicy(
            enabled=news_blackout_enabled,
            event_source="economic_calendar",
            minimum_impact=settings.policy.default_news_minimum_impact,
            blackout_minutes_before=settings.policy.default_news_blackout_minutes_before,
            blackout_minutes_after=settings.policy.default_news_blackout_minutes_after,
            currencies=currencies,
            notes=[
                "News blackout windows are a soft best-practice layer and depend on a loaded economic calendar.",
            ],
        ),
        cost_model=cost_defaults,
        execution_cost_model=ExecutionCostModel(**cost_defaults),
        risk_envelope=RiskEnvelope(
            max_daily_loss_pct=5.0,
            max_simultaneous_positions=1,
            max_spread_allowed_pips=2.0,
            session_boundaries_utc=session_hours,
            news_event_policy="calendar_blackout" if news_blackout_enabled else "disabled",
            kill_switch_conditions=[
                "disable entries when spread exceeds max_spread_allowed_pips",
                "disable entries when max daily loss is exceeded",
            ],
            leverage=settings.policy.default_leverage,
            sizing_rule="fixed_fractional",
            margin_buffer_pct=settings.policy.default_margin_buffer_pct,
            notes=["Hard strategy-level risk envelope for research and downstream EA packaging."],
        ),
        validation_profile=validation_profile,
        shadow_ml_policy=ShadowMLPolicy(),
        source_citations=candidate.source_citations,
        notes=candidate.notes + candidate.critic_notes,
        open_anchor_hour_utc=candidate.open_anchor_hour_utc,
        base_granularity=settings.data.base_granularity,
        entry_style=candidate.entry_style,
        holding_bars=candidate.holding_bars,
        signal_threshold=candidate.signal_threshold,
        stop_loss_pips=candidate.stop_loss_pips,
        take_profit_pips=candidate.take_profit_pips,
        trailing_stop_enabled=candidate.trailing_stop_enabled,
        trailing_stop_pips=candidate.trailing_stop_pips,
        spread_multiplier=1.0,
        time_split=validation_profile.time_split,
    )
    spec_path = settings.paths().reports_dir / candidate.candidate_id / "strategy_spec.json"
    write_json(spec_path, spec.model_dump(mode="json"))
    append_trial_entry(
        settings,
        candidate_id=spec.candidate_id,
        family=spec.family,
        stage="ea_spec_complete",
        artifact_paths={"candidate_path": str(candidate_path), "spec_path": str(spec_path)},
    )
    return spec.model_dump(mode="json")


def prepare_review_context(*, payload: dict, settings: Settings, config: dict, read_policy: ReadPolicy) -> dict:
    spec = StrategySpec.model_validate(payload)
    report_dir = settings.paths().reports_dir / spec.candidate_id
    candidate_path = report_dir / "candidate.json"
    if candidate_path.exists():
        candidate = CandidateDraft.model_validate(read_json(candidate_path))
    else:
        candidate = CandidateDraft(
            candidate_id=spec.candidate_id,
            family=spec.family,
            title=f"{spec.family.replace('_', ' ').title()} Candidate {spec.candidate_id}",
            thesis="Recovered candidate context from compiled strategy specification.",
            source_citations=spec.source_citations,
            strategy_hypothesis="Recovered from deterministic strategy specification.",
            market_context={
                "session_focus": spec.session_policy.name,
                "volatility_preference": "unspecified",
                "directional_bias": spec.side_policy,
                "execution_notes": spec.session_policy.notes,
                "allowed_hours_utc": spec.session_policy.allowed_hours_utc,
            },
            setup_summary=spec.setup_logic.summary,
            entry_summary=" ".join(spec.entry_logic),
            exit_summary=" ".join(spec.exit_logic),
            risk_summary="Recovered from strategy spec risk policy.",
            notes=spec.notes,
            quality_flags=["recovered_candidate_context"],
            contradiction_summary=[],
            critic_notes=[],
            entry_style=spec.entry_style,
            holding_bars=spec.holding_bars,
            signal_threshold=spec.signal_threshold,
            stop_loss_pips=spec.stop_loss_pips,
            take_profit_pips=spec.take_profit_pips,
        )
        write_json(candidate_path, candidate.model_dump(mode="json"))
    artifact = run_backtest(spec, settings)
    stress = run_stress_test(spec, settings)
    grades = grade_candidate(artifact, stress, settings)
    model_metrics_path = report_dir / "model_metrics.json"
    if not model_metrics_path.exists():
        train_models(spec, settings)
    model_metrics = read_json(model_metrics_path) if model_metrics_path.exists() else {}
    trade_ledger = _read_trade_ledger(artifact.trade_ledger_path)
    ftmo_fit = score_ftmo_fit(
        spec=spec,
        backtest=artifact,
        stress=stress,
        trade_ledger=trade_ledger,
        settings=settings,
    )
    data_provenance = build_data_provenance(spec, settings, stage="backtested")
    environment_snapshot = build_environment_snapshot(settings, candidate_id=spec.candidate_id)
    robustness_report = build_robustness_report(
        spec,
        backtest=artifact,
        stress=stress,
        trade_ledger=trade_ledger,
        settings=settings,
    )
    parity_validation = load_latest_mt5_validation(spec.candidate_id, settings)
    forward_report = load_forward_stage_report(spec.candidate_id, settings)
    readiness_status = resolve_readiness_status(
        candidate_id=spec.candidate_id,
        spec_exists=True,
        backtest=artifact,
        stress=stress,
        robustness=robustness_report,
        parity_passed=bool(parity_validation and parity_validation.validation_status == "passed"),
        forward_report=forward_report,
        settings=settings,
    )
    evidence = required_evidence(readiness_status)
    critic_notes = _build_critic_notes(candidate, artifact, stress)
    approval_recommendation = (
        "approve_for_publish"
        if readiness_status in {"review_eligible_provisional", "review_eligible"}
        else "needs_human_review"
    )
    return ReviewContext(
        candidate_id=spec.candidate_id,
        family=spec.family,
        title=candidate.title,
        thesis=candidate.thesis,
        citations=candidate.source_citations,
        contradiction_summary=candidate.contradiction_summary,
        critic_notes=critic_notes,
        quality_flags=candidate.quality_flags,
        readiness_status=readiness_status,
        required_evidence=evidence,
        robustness_mode=robustness_report.mode,
        metrics={
            "family": spec.family,
            "trade_count": artifact.trade_count,
            "profit_factor": artifact.profit_factor,
            "out_of_sample_profit_factor": artifact.out_of_sample_profit_factor,
            "expectancy_pips": artifact.expectancy_pips,
            "max_drawdown_pct": artifact.max_drawdown_pct,
            "split_breakdown": artifact.split_breakdown,
            "regime_breakdown": artifact.regime_breakdown,
            "walk_forward_summary": artifact.walk_forward_summary,
            "stress_scenarios": [scenario.model_dump(mode="json") for scenario in stress.scenarios],
            "stress_passed": stress.passed,
            "shadow_ml_report": model_metrics,
            "account_metrics": artifact.account_metrics,
            "ftmo_fit": ftmo_fit.model_dump(mode="json"),
            "dataset_snapshot": data_provenance.dataset_snapshot.model_dump(mode="json"),
            "feature_build": data_provenance.feature_build.model_dump(mode="json"),
            "data_provenance": data_provenance.model_dump(mode="json"),
            "environment_snapshot": environment_snapshot.model_dump(mode="json"),
            "execution_cost_model": spec.execution_cost_model.model_dump(mode="json"),
            "risk_envelope": spec.risk_envelope.model_dump(mode="json"),
            "robustness_report": robustness_report.model_dump(mode="json"),
            "forward_stage_report": forward_report.model_dump(mode="json") if forward_report else {},
            "parity_validation": parity_validation.model_dump(mode="json") if parity_validation else {},
            "grades": grades,
            "approval_recommendation": approval_recommendation,
            "readiness_status": readiness_status,
            "required_evidence": evidence,
        },
    ).model_dump(mode="json")


def finalize_review_packet(*, payload: dict, settings: Settings, config: dict, read_policy: ReadPolicy) -> dict:
    review_path = settings.paths().reports_dir / payload["candidate_id"] / "review_packet.json"
    write_json(review_path, payload)
    append_trial_entry(
        settings,
        candidate_id=payload["candidate_id"],
        family=str((payload.get("metrics") or {}).get("family") or "scalping"),
        stage="review",
        artifact_paths={"review_packet_path": str(review_path)},
        gate_outcomes={
            "readiness": payload.get("readiness"),
            "approval_recommendation": payload.get("approval_recommendation"),
        },
    )
    return payload


def publish_candidate_manifest(*, payload: dict, settings: Settings, config: dict, read_policy: ReadPolicy) -> dict:
    manifest = publish_candidate(payload["candidate_id"], settings)
    return manifest.model_dump(mode="json")


def generate_mt5_packet_tool(*, payload: dict, settings: Settings, config: dict, read_policy: ReadPolicy) -> dict:
    packet = generate_mt5_packet(payload["candidate_id"], settings)
    return packet.model_dump(mode="json")


def validate_mt5_practice_tool(*, payload: dict, settings: Settings, config: dict, read_policy: ReadPolicy) -> dict:
    audit_csv = Path(payload["audit_csv"]) if payload.get("audit_csv") else None
    report = validate_mt5_practice(payload["candidate_id"], settings, audit_csv)
    return report.model_dump(mode="json")


def _build_critic_notes(candidate: CandidateDraft, artifact, stress) -> list[CriticNote]:
    worst_scenario = min(stress.scenarios, key=lambda item: item.profit_factor) if stress.scenarios else None
    notes = [
        CriticNote(
            critic_name="QuantCritic",
            severity="medium" if artifact.out_of_sample_profit_factor >= 1.0 else "high",
            finding="Out-of-sample performance must remain stronger than narrative appeal.",
            recommendation="Reject promotion if OOS PF fails the validation floor.",
        ),
        CriticNote(
            critic_name="RiskCritic",
            severity="medium" if artifact.max_drawdown_pct < 12 else "high",
            finding="Risk tolerance is governed by explicit drawdown review triggers.",
            recommendation="Escalate if drawdown exceeds the configured review threshold.",
        ),
        CriticNote(
            critic_name="ExecutionRealist",
            severity="medium" if stress.passed else "high",
            finding=(
                f"Worst stress scenario PF was {worst_scenario.profit_factor:.3f}."
                if worst_scenario
                else "Stress scenario results are missing."
            ),
            recommendation="Keep MT5 strictly as parity validation and never as canonical research input.",
        ),
    ]
    for note in candidate.critic_notes:
        notes.append(
            CriticNote(
                critic_name="DiscoveryCritic",
                severity="low",
                finding=note,
                recommendation="Preserve critic findings in the review packet.",
            )
        )
    return notes


def _read_trade_ledger(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame(
            columns=[
                "timestamp_utc",
                "exit_timestamp_utc",
                "pnl_dollars",
                "balance_after",
                "margin_utilization_pct",
            ]
        )


def _scalping_style_filters(entry_style: str, volatility_floor: str) -> list[dict[str, str]]:
    style = entry_style.strip().lower()
    if style == "session_breakout":
        return [
            {"name": "max_spread_pips", "rule": "2.0"},
            {"name": "min_volatility_20", "rule": volatility_floor},
            {"name": "require_ret_5_alignment", "rule": "true"},
            {"name": "require_mean_location_alignment", "rule": "true"},
        ]
    if style == "volatility_breakout":
        return [
            {"name": "max_spread_pips", "rule": "1.8"},
            {"name": "min_volatility_20", "rule": "0.00014"},
            {"name": "require_ret_5_alignment", "rule": "true"},
            {"name": "require_mean_location_alignment", "rule": "true"},
            {"name": "breakout_zscore_floor", "rule": "0.55"},
        ]
    if style == "pullback_continuation":
        return [
            {"name": "max_spread_pips", "rule": "2.0"},
            {"name": "min_volatility_20", "rule": "0.00008"},
            {"name": "trend_ret_5_min", "rule": "0.00008"},
            {"name": "pullback_zscore_limit", "rule": "0.45"},
            {"name": "require_recovery_ret_1", "rule": "true"},
        ]
    if style == "failed_break_fade":
        return [
            {"name": "max_spread_pips", "rule": "2.0"},
            {"name": "min_volatility_20", "rule": "0.00009"},
            {"name": "fade_ret_5_floor", "rule": "0.00005"},
            {"name": "fade_momentum_ceiling", "rule": "3.2"},
            {"name": "require_reversal_ret_1", "rule": "true"},
        ]
    if style == "mean_reversion_pullback":
        return [
            {"name": "max_spread_pips", "rule": "2.5"},
            {"name": "min_volatility_20", "rule": "0.00008"},
            {"name": "require_reversal_ret_1", "rule": "true"},
        ]
    return []


def _day_trading_style_filters(entry_style: str) -> list[dict[str, str]]:
    style = entry_style.strip().lower()
    if style == "compression_reversion":
        return [
            {"name": "max_spread_pips", "rule": "2.2"},
            {"name": "max_range_width_10_pips", "rule": "7.8"},
            {"name": "reclaim_range_position_floor", "rule": "0.18"},
            {"name": "reclaim_range_position_ceiling", "rule": "0.45"},
            {"name": "reclaim_momentum_ceiling", "rule": "3.6"},
            {"name": "require_reversal_ret_1", "rule": "true"},
        ]
    if style == "compression_breakout":
        return [
            {"name": "max_spread_pips", "rule": "2.8"},
            {"name": "max_range_width_10_pips", "rule": "9.0"},
            {"name": "breakout_zscore_floor", "rule": "0.45"},
            {"name": "compression_range_position_floor", "rule": "0.65"},
            {"name": "require_ret_1_confirmation", "rule": "true"},
        ]
    if style == "volatility_retest_breakout":
        return [
            {"name": "max_spread_pips", "rule": "2.5"},
            {"name": "min_volatility_20", "rule": "0.00005"},
            {"name": "breakout_zscore_floor", "rule": "0.55"},
            {"name": "trend_ret_5_min", "rule": "0.00008"},
            {"name": "retest_zscore_limit", "rule": "0.35"},
            {"name": "retest_range_position_floor", "rule": "0.55"},
            {"name": "require_mean_location_alignment", "rule": "true"},
            {"name": "require_recovery_ret_1", "rule": "true"},
        ]
    if style == "overlap_event_retest_breakout":
        return [
            {"name": "max_spread_pips", "rule": "2.5"},
            {"name": "min_volatility_20", "rule": "0.00005"},
            {"name": "required_volatility_bucket", "rule": "high"},
            {"name": "breakout_zscore_floor", "rule": "0.55"},
            {"name": "trend_ret_5_min", "rule": "0.00008"},
            {"name": "retest_zscore_limit", "rule": "0.34"},
            {"name": "retest_range_position_floor", "rule": "0.55"},
            {"name": "require_mean_location_alignment", "rule": "true"},
            {"name": "require_recovery_ret_1", "rule": "true"},
        ]
    if style == "overlap_persistence_retest":
        return [
            {"name": "max_spread_pips", "rule": "2.3"},
            {"name": "min_volatility_20", "rule": "0.00006"},
            {"name": "breakout_zscore_floor", "rule": "0.57"},
            {"name": "trend_ret_5_min", "rule": "0.00009"},
            {"name": "retest_zscore_limit", "rule": "0.32"},
            {"name": "retest_range_position_floor", "rule": "0.58"},
            {"name": "require_mean_location_alignment", "rule": "true"},
            {"name": "require_recovery_ret_1", "rule": "true"},
            {"name": "exclude_context_bucket", "rule": "mean_reversion_context"},
        ]
    if style == "high_vol_overlap_persistence_retest":
        return [
            {"name": "max_spread_pips", "rule": "2.3"},
            {"name": "min_volatility_20", "rule": "0.00006"},
            {"name": "required_volatility_bucket", "rule": "high"},
            {"name": "breakout_zscore_floor", "rule": "0.57"},
            {"name": "trend_ret_5_min", "rule": "0.00009"},
            {"name": "retest_zscore_limit", "rule": "0.32"},
            {"name": "retest_range_position_floor", "rule": "0.58"},
            {"name": "require_mean_location_alignment", "rule": "true"},
            {"name": "require_recovery_ret_1", "rule": "true"},
            {"name": "exclude_context_bucket", "rule": "mean_reversion_context"},
        ]
    if style == "compression_retest_breakout":
        return [
            {"name": "max_spread_pips", "rule": "2.6"},
            {"name": "min_volatility_20", "rule": "0.00004"},
            {"name": "max_range_width_10_pips", "rule": "8.5"},
            {"name": "breakout_zscore_floor", "rule": "0.40"},
            {"name": "trend_ret_5_min", "rule": "0.00008"},
            {"name": "retest_zscore_limit", "rule": "0.30"},
            {"name": "retest_range_position_floor", "rule": "0.56"},
            {"name": "require_recovery_ret_1", "rule": "true"},
        ]
    if style == "range_reclaim":
        return [
            {"name": "max_spread_pips", "rule": "3.0"},
            {"name": "extension_zscore_floor", "rule": "1.05"},
            {"name": "reclaim_range_position_floor", "rule": "0.12"},
            {"name": "reclaim_range_position_ceiling", "rule": "0.42"},
            {"name": "reclaim_momentum_ceiling", "rule": "4.0"},
            {"name": "require_reclaim_ret_1", "rule": "true"},
        ]
    if style == "trend_retest":
        return [
            {"name": "max_spread_pips", "rule": "2.6"},
            {"name": "trend_ret_5_min", "rule": "0.00012"},
            {"name": "retest_zscore_limit", "rule": "0.35"},
            {"name": "retest_range_position_floor", "rule": "0.52"},
            {"name": "require_recovery_ret_1", "rule": "true"},
        ]
    return []
