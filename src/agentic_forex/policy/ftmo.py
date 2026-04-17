from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd

from agentic_forex.backtesting.models import BacktestArtifact, StressTestReport
from agentic_forex.config import Settings
from agentic_forex.workflows.contracts import FTMOFitReport, FTMORuleset, StrategySpec


@dataclass(frozen=True, slots=True)
class _FTMORules:
    ruleset_id: str
    evaluation_label: str
    profit_target_pct: float
    maximum_daily_loss_pct: float
    maximum_loss_pct: float
    best_day_profit_target_share_limit: float
    minimum_trading_days: int
    timezone: str
    notes: tuple[str, ...]


RULESETS = {
    "ftmo_1step_2026_03": _FTMORules(
        ruleset_id="ftmo_1step_2026_03",
        evaluation_label="FTMO 1-Step Evaluation",
        profit_target_pct=10.0,
        maximum_daily_loss_pct=5.0,
        maximum_loss_pct=10.0,
        best_day_profit_target_share_limit=0.5,
        minimum_trading_days=4,
        timezone="Europe/Prague",
        notes=(
            "Soft-fit ruleset based on FTMO public objective language as reviewed on 2026-03-20.",
            "Daily loss and best-day calculations are closed-trade approximations, not floating-equity simulations.",
        ),
    ),
}


def resolve_ftmo_ruleset(settings: Settings) -> FTMORuleset:
    raw = RULESETS[settings.policy.ftmo_ruleset_id]
    return FTMORuleset(
        ruleset_id=raw.ruleset_id,
        evaluation_label=raw.evaluation_label,
        profit_target_pct=raw.profit_target_pct,
        maximum_daily_loss_pct=raw.maximum_daily_loss_pct,
        maximum_loss_pct=raw.maximum_loss_pct,
        best_day_profit_target_share_limit=raw.best_day_profit_target_share_limit,
        minimum_trading_days=raw.minimum_trading_days,
        timezone=raw.timezone,
        notes=list(raw.notes),
    )


def score_ftmo_fit(
    *,
    spec: StrategySpec,
    backtest: BacktestArtifact,
    stress: StressTestReport,
    trade_ledger: pd.DataFrame,
    settings: Settings,
) -> FTMOFitReport:
    ruleset = resolve_ftmo_ruleset(settings)
    initial_balance = spec.account_model.initial_balance
    if trade_ledger.empty:
        return FTMOFitReport(
            ruleset_id=ruleset.ruleset_id,
            evaluation_label=ruleset.evaluation_label,
            fit_score_0_100=0.0,
            fit_band="poor_fit",
            measured_with="closed_trade_approximation",
            profit_target_progress_pct=0.0,
            daily_loss_observed_pct=0.0,
            overall_drawdown_observed_pct=0.0,
            best_day_profit_share_of_target_pct=0.0,
            trading_days_observed=0,
            leverage_observed=spec.account_model.leverage,
            news_blackout_enabled=spec.news_policy.enabled,
            daily_loss_fit=0.0,
            overall_drawdown_fit=0.0,
            profit_target_fit=0.0,
            best_day_concentration_fit=0.0,
            minimum_trading_days_fit=0.0,
            execution_discipline_fit=0.0,
            real_market_behavior_fit=0.0,
            blockers=["No trades were generated, so FTMO fit cannot be established."],
            strengths=[],
            next_actions=["Increase data coverage or adjust the deterministic setup before using FTMO fit as a signal."],
        )

    ledger = trade_ledger.copy()
    ledger["exit_timestamp_utc"] = pd.to_datetime(ledger["exit_timestamp_utc"], utc=True)
    zone = ZoneInfo(ruleset.timezone)
    ledger["ftmo_day"] = ledger["exit_timestamp_utc"].dt.tz_convert(zone).dt.date
    daily_pnl = ledger.groupby("ftmo_day")["pnl_dollars"].sum()
    best_day_profit = max(float(daily_pnl.max()), 0.0) if not daily_pnl.empty else 0.0
    worst_day_loss = abs(min(float(daily_pnl.min()), 0.0)) if not daily_pnl.empty else 0.0
    final_balance = float(ledger["balance_after"].iloc[-1])
    profit_target_progress_pct = max(((final_balance - initial_balance) / initial_balance) * 100, 0.0)
    daily_loss_observed_pct = (worst_day_loss / initial_balance) * 100 if initial_balance else 0.0
    best_day_profit_target_share_pct = (
        (best_day_profit / (initial_balance * (ruleset.profit_target_pct / 100))) * 100
        if initial_balance and ruleset.profit_target_pct
        else 0.0
    )
    trading_days_observed = int(ledger["ftmo_day"].nunique())
    leverage_observed = spec.account_model.leverage
    max_margin_utilization_pct = float(ledger["margin_utilization_pct"].max()) if "margin_utilization_pct" in ledger.columns else 0.0

    daily_loss_fit = _inverse_fit(daily_loss_observed_pct, ruleset.maximum_daily_loss_pct)
    overall_drawdown_fit = _inverse_fit(backtest.max_drawdown_pct, ruleset.maximum_loss_pct)
    profit_target_fit = _direct_fit(profit_target_progress_pct, ruleset.profit_target_pct)
    best_day_fit = _inverse_fit(best_day_profit_target_share_pct, ruleset.best_day_profit_target_share_limit * 100)
    min_days_fit = min(trading_days_observed / max(ruleset.minimum_trading_days, 1), 1.0) * 100
    execution_fit = _execution_discipline_fit(spec)
    real_market_fit = _real_market_fit(spec, stress, max_margin_utilization_pct)

    weighted = (
        daily_loss_fit * 0.2
        + overall_drawdown_fit * 0.2
        + profit_target_fit * 0.18
        + best_day_fit * 0.12
        + min_days_fit * 0.1
        + execution_fit * 0.1
        + real_market_fit * 0.1
    )

    blockers: list[str] = []
    strengths: list[str] = []
    next_actions: list[str] = []
    if daily_loss_observed_pct > ruleset.maximum_daily_loss_pct:
        blockers.append("Observed daily loss exceeded the FTMO daily loss objective.")
    else:
        strengths.append("Observed daily loss stayed inside the FTMO daily loss objective.")
    if backtest.max_drawdown_pct > ruleset.maximum_loss_pct:
        blockers.append("Observed drawdown exceeded the FTMO maximum loss objective.")
    else:
        strengths.append("Observed drawdown stayed inside the FTMO maximum loss objective.")
    if profit_target_progress_pct < ruleset.profit_target_pct:
        blockers.append("Profit target progress remains below the FTMO objective.")
        next_actions.append("Improve net return per trade or trade count before using FTMO fit as a promotion signal.")
    else:
        strengths.append("Total return meets or exceeds the FTMO profit target objective.")
    if best_day_profit_target_share_pct > ruleset.best_day_profit_target_share_limit * 100:
        blockers.append("A single best day contributes too much of the FTMO profit target.")
        next_actions.append("Reduce concentration by smoothing performance across more sessions.")
    else:
        strengths.append("Best-day concentration remains within the FTMO concentration guideline.")
    if trading_days_observed < ruleset.minimum_trading_days:
        blockers.append("Minimum FTMO trading-day count has not been reached in this sample.")
        next_actions.append("Run the strategy over more valid trading days before using FTMO fit as a decision aid.")
    if not spec.news_policy.enabled:
        blockers.append("News blackout policy is disabled, which weakens real-market discipline.")
        next_actions.append("Load an economic calendar and enable blackout windows for high-impact events.")
    if leverage_observed > 100:
        blockers.append("Configured leverage is higher than a conservative FTMO fit assumption.")
    if max_margin_utilization_pct > 65:
        blockers.append("Margin utilization is too aggressive for a conservative FTMO fit.")

    fit_score = max(min(round(weighted, 2), 100.0), 0.0)
    fit_band = "strong_fit" if fit_score >= 80 else "moderate_fit" if fit_score >= 60 else "weak_fit" if fit_score >= 40 else "poor_fit"

    return FTMOFitReport(
        ruleset_id=ruleset.ruleset_id,
        evaluation_label=ruleset.evaluation_label,
        fit_score_0_100=fit_score,
        fit_band=fit_band,
        measured_with="closed_trade_approximation",
        profit_target_progress_pct=round(profit_target_progress_pct, 4),
        daily_loss_observed_pct=round(daily_loss_observed_pct, 4),
        overall_drawdown_observed_pct=round(backtest.max_drawdown_pct, 4),
        best_day_profit_share_of_target_pct=round(best_day_profit_target_share_pct, 4),
        trading_days_observed=trading_days_observed,
        leverage_observed=round(leverage_observed, 4),
        news_blackout_enabled=spec.news_policy.enabled,
        daily_loss_fit=round(daily_loss_fit, 2),
        overall_drawdown_fit=round(overall_drawdown_fit, 2),
        profit_target_fit=round(profit_target_fit, 2),
        best_day_concentration_fit=round(best_day_fit, 2),
        minimum_trading_days_fit=round(min_days_fit, 2),
        execution_discipline_fit=round(execution_fit, 2),
        real_market_behavior_fit=round(real_market_fit, 2),
        blockers=blockers,
        strengths=strengths,
        next_actions=next_actions,
    )


def _inverse_fit(observed_pct: float, limit_pct: float) -> float:
    if observed_pct <= 0:
        return 100.0
    ratio = observed_pct / max(limit_pct, 1e-9)
    return max(min((2 - ratio) * 100, 100.0), 0.0)


def _direct_fit(progress_pct: float, target_pct: float) -> float:
    return max(min((progress_pct / max(target_pct, 1e-9)) * 100, 100.0), 0.0)


def _execution_discipline_fit(spec: StrategySpec) -> float:
    score = 0.0
    if spec.risk_policy.stop_loss_pips > 0:
        score += 20
    if spec.risk_policy.take_profit_pips > 0:
        score += 20
    if spec.risk_policy.max_risk_per_trade_pct <= 1.0:
        score += 25
    if spec.risk_policy.max_open_positions <= 1:
        score += 20
    if spec.account_model.risk_per_trade_pct <= 1.0:
        score += 15
    return min(score, 100.0)


def _real_market_fit(spec: StrategySpec, stress: StressTestReport, max_margin_utilization_pct: float) -> float:
    score = 100.0
    if not spec.news_policy.enabled:
        score -= 35.0
    if not stress.passed:
        score -= 25.0
    if spec.account_model.leverage > 100:
        score -= 20.0
    if max_margin_utilization_pct > 50:
        score -= min((max_margin_utilization_pct - 50) * 0.8, 20.0)
    return max(score, 0.0)
