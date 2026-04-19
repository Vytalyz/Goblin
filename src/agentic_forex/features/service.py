from __future__ import annotations

import pandas as pd


def pip_scale_for_instrument(instrument: str) -> float:
    """Return the pip scale factor for a given instrument symbol.

    Standard forex pairs use 10000.0 (1 pip = 0.0001 price units).
    JPY cross pairs use 100.0 (1 pip = 0.01 price units).
    """
    normalized = instrument.replace("/", "_").upper()
    if normalized.endswith("_JPY"):
        return 100.0
    return 10000.0


def build_features(frame: pd.DataFrame, pip_scale: float = 10_000.0) -> pd.DataFrame:
    """Build the feature matrix from a normalised OHLC frame.

    Args:
        frame: Normalised price frame with mid_c, mid_h, mid_l, spread_pips,
            timestamp_utc columns.
        pip_scale: Instrument pip conversion factor.  Use
            ``pip_scale_for_instrument(instrument)`` to derive this from the
            symbol name.  Defaults to 10 000 (standard 4-decimal pairs such as
            EURUSD).  JPY crosses require 100.
    """
    data = frame.copy()
    mid_high = data["mid_h"] if "mid_h" in data.columns else data["mid_c"]
    mid_low = data["mid_l"] if "mid_l" in data.columns else data["mid_c"]
    spread_mean_20 = data["spread_pips"].rolling(20).mean().replace(0, 1e-9).bfill()
    data["ret_1"] = data["mid_c"].pct_change().fillna(0.0)
    data["ret_5"] = data["mid_c"].pct_change(5).fillna(0.0)
    data["rolling_mean_10"] = data["mid_c"].rolling(10).mean().bfill()
    data["rolling_std_10"] = data["mid_c"].rolling(10).std().replace(0, 1e-9).bfill()
    rolling_high_10 = mid_high.rolling(10).max().bfill()
    rolling_low_10 = mid_low.rolling(10).min().bfill()
    rolling_range_10 = (rolling_high_10 - rolling_low_10).replace(0, 1e-9)
    data["zscore_10"] = (data["mid_c"] - data["rolling_mean_10"]) / data["rolling_std_10"]
    data["momentum_12"] = data["mid_c"].diff(12).fillna(0.0) * pip_scale
    data["volatility_5"] = data["ret_1"].rolling(5).std().bfill()
    data["volatility_20"] = data["ret_1"].rolling(20).std().bfill()
    data["volatility_ratio_5_to_20"] = (data["volatility_5"] / data["volatility_20"].replace(0, 1e-9)).clip(
        lower=0.0, upper=5.0
    )
    data["intrabar_range_pips"] = (mid_high - mid_low) * pip_scale
    data["range_width_10_pips"] = rolling_range_10 * pip_scale
    data["net_change_10_pips"] = data["mid_c"].diff(10).fillna(0.0) * pip_scale
    data["range_efficiency_10"] = (
        data["net_change_10_pips"].abs() / data["range_width_10_pips"].replace(0, 1e-9)
    ).clip(lower=0.0, upper=2.0)
    data["range_position_10"] = ((data["mid_c"] - rolling_low_10) / rolling_range_10).clip(0.0, 1.0)
    data["spread_to_range_10"] = data["spread_pips"] / data["range_width_10_pips"].replace(0, 1e-9)
    data["spread_shock_20"] = (data["spread_pips"] / spread_mean_20).clip(lower=0.0, upper=5.0)
    data["hour"] = pd.to_datetime(data["timestamp_utc"], utc=True).dt.hour

    # ATR-14: Average True Range (uses high, low, prev close)
    prev_close = data["mid_c"].shift(1)
    tr1 = mid_high - mid_low
    tr2 = (mid_high - prev_close).abs()
    tr3 = (mid_low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    data["atr_14"] = true_range.rolling(14).mean().bfill()

    # RSI-14: Relative Strength Index (Wilder's smoothed)
    delta = data["mid_c"].diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    data["rsi_14"] = (100.0 - 100.0 / (1.0 + rs)).bfill().clip(0.0, 100.0)

    # GMM regime label (ML-P1.6): trained on volatility/momentum features.
    # Import here to avoid circular imports at module level.
    from agentic_forex.ml.regime import REGIME_FEATURES, fit_regime_classifier, predict_regime_labels

    has_regime_features = all(col in data.columns for col in REGIME_FEATURES)
    if has_regime_features and len(data.dropna(subset=REGIME_FEATURES)) >= 40:
        gmm = fit_regime_classifier(data, n_components=4)
        data["regime_label"] = predict_regime_labels(gmm, data)
    else:
        data["regime_label"] = -1

    return data
