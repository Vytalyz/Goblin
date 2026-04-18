"""Phase 0 tests: ATR/RSI features and trailing-stop exit logic."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pandas as pd

from agentic_forex.backtesting.engine import _scan_trailing_exit
from agentic_forex.features.service import build_features
from agentic_forex.workflows.contracts import (
    CandidateDraft,
    MarketContextSummary,
    RiskPolicy,
    SessionPolicy,
    SetupLogic,
    StrategySpec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_frame(rows: int = 100, *, trend: float = 0.0) -> pd.DataFrame:
    """Build a minimal OHLC + spread DataFrame for feature/engine tests."""
    start = datetime(2025, 6, 1, 8, 0, tzinfo=UTC)
    records = []
    price = 1.10000
    for i in range(rows):
        ts = start + timedelta(minutes=i)
        close = price + trend * i + 0.00050 * math.sin(i / 6)
        high = close + 0.00015
        low = close - 0.00015
        records.append(
            {
                "timestamp_utc": ts.isoformat().replace("+00:00", "Z"),
                "mid_o": round(price, 6),
                "mid_h": round(high, 6),
                "mid_l": round(low, 6),
                "mid_c": round(close, 6),
                "spread_pips": 0.8,
            }
        )
        price = close
    return pd.DataFrame.from_records(records)


def _make_trailing_frame(prices: list[float]) -> pd.DataFrame:
    """Build a DataFrame from explicit mid_c values with small intrabar range."""
    start = datetime(2025, 6, 1, 8, 0, tzinfo=UTC)
    records = []
    for i, p in enumerate(prices):
        records.append(
            {
                "timestamp_utc": (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
                "mid_o": p,
                "mid_h": p + 0.00005,
                "mid_l": p - 0.00005,
                "mid_c": p,
                "spread_pips": 0.8,
            }
        )
    return pd.DataFrame.from_records(records)


def _minimal_spec(
    *,
    trailing_stop_enabled: bool = False,
    trailing_stop_pips: float | None = None,
    stop_loss_pips: float = 10.0,
    take_profit_pips: float = 20.0,
    holding_bars: int = 30,
) -> StrategySpec:
    return StrategySpec(
        candidate_id="AF-TEST-TRAIL",
        family="test_trailing",
        instrument="EUR_USD",
        execution_granularity="M1",
        session_policy=SessionPolicy(name="test", allowed_hours_utc=list(range(24))),
        setup_logic=SetupLogic(style="session_breakout", summary="test"),
        risk_policy=RiskPolicy(
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=take_profit_pips,
            trailing_stop_enabled=trailing_stop_enabled,
            trailing_stop_pips=trailing_stop_pips,
        ),
        source_citations=["test"],
        entry_style="session_breakout",
        holding_bars=holding_bars,
        signal_threshold=0.0,
        stop_loss_pips=stop_loss_pips,
        take_profit_pips=take_profit_pips,
        trailing_stop_enabled=trailing_stop_enabled,
        trailing_stop_pips=trailing_stop_pips,
    )


# ---------------------------------------------------------------------------
# ATR tests
# ---------------------------------------------------------------------------


class TestATRFeature:
    def test_atr_14_column_exists(self):
        frame = _make_frame(50)
        features = build_features(frame)
        assert "atr_14" in features.columns

    def test_atr_14_values_positive(self):
        frame = _make_frame(50)
        features = build_features(frame)
        assert (features["atr_14"] > 0).all()

    def test_atr_14_known_value(self):
        """Verify ATR against manual true-range calculation for a flat-price series."""
        rows = 30
        records = []
        start = datetime(2025, 1, 1, tzinfo=UTC)
        for i in range(rows):
            records.append(
                {
                    "timestamp_utc": (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
                    "mid_o": 1.10,
                    "mid_h": 1.1002,
                    "mid_l": 1.0998,
                    "mid_c": 1.10,
                    "spread_pips": 0.8,
                }
            )
        frame = pd.DataFrame.from_records(records)
        features = build_features(frame)
        # True range for every bar should be H-L = 0.0004
        # ATR-14 should converge to 0.0004 after 14+ bars
        assert abs(features["atr_14"].iloc[-1] - 0.0004) < 0.0001


# ---------------------------------------------------------------------------
# RSI tests
# ---------------------------------------------------------------------------


class TestRSIFeature:
    def test_rsi_14_column_exists(self):
        frame = _make_frame(50)
        features = build_features(frame)
        assert "rsi_14" in features.columns

    def test_rsi_14_bounded(self):
        frame = _make_frame(50)
        features = build_features(frame)
        assert (features["rsi_14"] >= 0).all()
        assert (features["rsi_14"] <= 100).all()

    def test_rsi_14_uptrend_above_50(self):
        """In a strong uptrend, RSI should be well above 50."""
        frame = _make_frame(60, trend=0.00010)
        features = build_features(frame)
        # After warmup, RSI should be consistently high
        late_rsi = features["rsi_14"].iloc[30:]
        assert late_rsi.mean() > 60

    def test_rsi_14_downtrend_below_50(self):
        """In a strong downtrend, RSI should be below 50."""
        frame = _make_frame(60, trend=-0.00010)
        features = build_features(frame)
        late_rsi = features["rsi_14"].iloc[30:]
        assert late_rsi.mean() < 40


# ---------------------------------------------------------------------------
# Trailing stop scan tests
# ---------------------------------------------------------------------------


class TestTrailingStopScan:
    def test_trailing_stop_disabled_returns_none(self):
        """When trailing_stop_enabled is False, scan returns None."""
        prices = [1.1000 + i * 0.0001 for i in range(50)]
        frame = _make_trailing_frame(prices)
        features = build_features(frame)
        spec = _minimal_spec(trailing_stop_enabled=False, trailing_stop_pips=5.0)
        result = _scan_trailing_exit(features, 5, 40, 1, spec)
        assert result is None

    def test_trailing_stop_none_pips_returns_none(self):
        """When trailing_stop_pips is None, scan returns None."""
        prices = [1.1000 + i * 0.0001 for i in range(50)]
        frame = _make_trailing_frame(prices)
        features = build_features(frame)
        spec = _minimal_spec(trailing_stop_enabled=True, trailing_stop_pips=None)
        result = _scan_trailing_exit(features, 5, 40, 1, spec)
        assert result is None

    def test_long_trailing_stop_triggers(self):
        """Long: price rises 10 pips then drops — trailing stop should trigger."""
        # Entry at bar 5: price 1.1000
        # Bars 6-15: price rises to 1.1010 (+10 pips)
        # Bars 16-25: price drops back toward 1.1000
        # Trailing stop at 5 pips means trail level = peak - 5 pips = 1.1010 - 0.0005 = 1.1005
        # Should trigger when price drops to 1.1005
        prices = []
        for i in range(30):
            if i <= 5:
                prices.append(1.10000)
            elif i <= 15:
                prices.append(1.10000 + (i - 5) * 0.0001)  # rises to 1.1010
            else:
                prices.append(1.10100 - (i - 15) * 0.0002)  # drops 2 pips/bar
        frame = _make_trailing_frame(prices)
        features = build_features(frame)
        spec = _minimal_spec(
            trailing_stop_enabled=True,
            trailing_stop_pips=5.0,
            stop_loss_pips=15.0,
            take_profit_pips=20.0,
            holding_bars=20,
        )
        result = _scan_trailing_exit(features, 5, 25, 1, spec)
        assert result is not None
        exit_idx, exit_reason, gross_pips = result
        assert exit_reason == "trailing_stop"
        # Trail level should be around peak (1.1010) - 5 pips (0.0005) = 1.1005
        # That's +5 pips from entry. Gross pips should be positive.
        assert gross_pips > 0

    def test_short_trailing_stop_triggers(self):
        """Short: price drops then bounces — trailing stop should trigger."""
        prices = []
        for i in range(30):
            if i <= 5:
                prices.append(1.10000)
            elif i <= 15:
                prices.append(1.10000 - (i - 5) * 0.0001)  # drops to 1.0990
            else:
                prices.append(1.09900 + (i - 15) * 0.0002)  # rises 2 pips/bar
        frame = _make_trailing_frame(prices)
        features = build_features(frame)
        spec = _minimal_spec(
            trailing_stop_enabled=True,
            trailing_stop_pips=5.0,
            stop_loss_pips=15.0,
            take_profit_pips=20.0,
            holding_bars=20,
        )
        result = _scan_trailing_exit(features, 5, 25, -1, spec)
        assert result is not None
        exit_idx, exit_reason, gross_pips = result
        assert exit_reason == "trailing_stop"
        assert gross_pips > 0

    def test_fixed_sl_is_absolute_floor(self):
        """If price crashes through both trail and SL, fixed SL wins."""
        # Entry at 1.1000, SL at 5 pips (1.0995)
        # Price rises 3 pips then drops 15 pips in one bar
        prices = [1.10000] * 6  # bars 0-5
        prices.append(1.10030)  # bar 6: small rise
        prices.append(1.08500)  # bar 7: crash through everything
        prices += [1.08500] * 10
        frame = _make_trailing_frame(prices)
        features = build_features(frame)
        spec = _minimal_spec(
            trailing_stop_enabled=True,
            trailing_stop_pips=2.0,
            stop_loss_pips=5.0,
            take_profit_pips=20.0,
            holding_bars=12,
        )
        result = _scan_trailing_exit(features, 5, 17, 1, spec)
        assert result is not None
        exit_idx, exit_reason, gross_pips = result
        assert exit_reason == "stop_loss"
        assert gross_pips == -5.0

    def test_take_profit_still_works_with_trailing(self):
        """TP should fire before trailing stop if price goes straight up."""
        prices = [1.10000] * 6
        for i in range(20):
            prices.append(1.10000 + (i + 1) * 0.0003)  # +3 pips/bar
        frame = _make_trailing_frame(prices)
        features = build_features(frame)
        spec = _minimal_spec(
            trailing_stop_enabled=True,
            trailing_stop_pips=5.0,
            stop_loss_pips=10.0,
            take_profit_pips=8.0,
            holding_bars=15,
        )
        result = _scan_trailing_exit(features, 5, 20, 1, spec)
        assert result is not None
        exit_idx, exit_reason, gross_pips = result
        assert exit_reason == "take_profit"
        assert gross_pips == 8.0

    def test_no_early_exit_returns_none(self):
        """If price stays flat, no early exit triggers."""
        prices = [1.10000] * 30
        frame = _make_trailing_frame(prices)
        features = build_features(frame)
        spec = _minimal_spec(
            trailing_stop_enabled=True,
            trailing_stop_pips=5.0,
            stop_loss_pips=10.0,
            take_profit_pips=20.0,
            holding_bars=20,
        )
        result = _scan_trailing_exit(features, 5, 25, 1, spec)
        assert result is None


# ---------------------------------------------------------------------------
# Contract model tests
# ---------------------------------------------------------------------------


class TestTrailingStopContracts:
    def test_strategy_spec_trailing_fields_default(self):
        spec = _minimal_spec()
        assert spec.trailing_stop_enabled is False
        assert spec.trailing_stop_pips is None

    def test_strategy_spec_trailing_fields_set(self):
        spec = _minimal_spec(trailing_stop_enabled=True, trailing_stop_pips=7.5)
        assert spec.trailing_stop_enabled is True
        assert spec.trailing_stop_pips == 7.5

    def test_candidate_draft_trailing_fields(self):
        draft = CandidateDraft(
            candidate_id="AF-TEST-01",
            family="test",
            title="Test",
            thesis="Test thesis",
            source_citations=["test"],
            strategy_hypothesis="Test",
            market_context=MarketContextSummary(
                session_focus="europe_open",
                volatility_preference="moderate",
                directional_bias="both",
            ),
            setup_summary="test",
            entry_summary="test",
            exit_summary="test",
            risk_summary="test",
            entry_style="session_breakout",
            holding_bars=60,
            signal_threshold=1.0,
            stop_loss_pips=10.0,
            take_profit_pips=15.0,
            trailing_stop_enabled=True,
            trailing_stop_pips=6.0,
        )
        assert draft.trailing_stop_enabled is True
        assert draft.trailing_stop_pips == 6.0

    def test_risk_policy_trailing_fields(self):
        rp = RiskPolicy(
            stop_loss_pips=10.0,
            take_profit_pips=15.0,
            trailing_stop_enabled=True,
            trailing_stop_pips=5.0,
        )
        assert rp.trailing_stop_enabled is True
        assert rp.trailing_stop_pips == 5.0


# ---------------------------------------------------------------------------
# EA generator trailing stop output
# ---------------------------------------------------------------------------


class TestEATrailingStop:
    def test_ea_includes_trailing_inputs_when_enabled(self):
        from agentic_forex.mt5.ea_generator import render_candidate_ea

        spec = _minimal_spec(trailing_stop_enabled=True, trailing_stop_pips=5.0)
        ea_source = render_candidate_ea(spec)
        assert "InpTrailingStopEnabled" in ea_source
        assert "InpTrailingStopPips" in ea_source
        assert "g_trailing_extreme" in ea_source
        assert "PositionModify" in ea_source

    def test_ea_trailing_disabled_by_default(self):
        from agentic_forex.mt5.ea_generator import render_candidate_ea

        spec = _minimal_spec(trailing_stop_enabled=False)
        ea_source = render_candidate_ea(spec)
        assert "InpTrailingStopEnabled = false" in ea_source


# ---------------------------------------------------------------------------
# Existing features still present
# ---------------------------------------------------------------------------


class TestExistingFeaturesUnchanged:
    def test_all_original_features_present(self):
        frame = _make_frame(50)
        features = build_features(frame)
        expected = [
            "ret_1",
            "ret_5",
            "rolling_mean_10",
            "rolling_std_10",
            "zscore_10",
            "momentum_12",
            "volatility_5",
            "volatility_20",
            "volatility_ratio_5_to_20",
            "intrabar_range_pips",
            "range_width_10_pips",
            "net_change_10_pips",
            "range_efficiency_10",
            "range_position_10",
            "spread_to_range_10",
            "spread_shock_20",
            "hour",
        ]
        for col in expected:
            assert col in features.columns, f"Missing feature: {col}"
