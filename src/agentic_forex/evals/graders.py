from __future__ import annotations

from agentic_forex.backtesting.models import BacktestArtifact, StressTestReport
from agentic_forex.config import Settings


def grade_candidate(backtest: BacktestArtifact, stress: StressTestReport, settings: Settings) -> dict:
    validation = settings.validation
    walk_forward_ok = (
        len(backtest.walk_forward_summary) >= validation.walk_forward_windows
        and all(bool(window.get("passed")) for window in backtest.walk_forward_summary)
        if backtest.walk_forward_summary
        else False
    )
    return {
        "trade_count_ok": backtest.trade_count >= validation.minimum_test_trade_count,
        "profit_factor_ok": backtest.out_of_sample_profit_factor >= validation.out_of_sample_profit_factor_floor,
        "expectancy_ok": backtest.expectancy_pips > validation.expectancy_floor,
        "drawdown_review": backtest.max_drawdown_pct >= validation.drawdown_review_trigger_pct,
        "stress_ok": stress.passed,
        "walk_forward_ok": walk_forward_ok,
        "ready_for_publish": all(
            [
                backtest.trade_count >= validation.minimum_test_trade_count,
                backtest.out_of_sample_profit_factor >= validation.out_of_sample_profit_factor_floor,
                backtest.expectancy_pips > validation.expectancy_floor,
                stress.passed,
                walk_forward_ok,
            ]
        ),
    }
