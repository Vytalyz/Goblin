from __future__ import annotations

import numpy as np
import pandas as pd

PIP_SCALE = 10000.0


def build_labels(
    frame: pd.DataFrame,
    holding_bars: int,
    *,
    stop_loss_pips: float,
    take_profit_pips: float,
) -> pd.DataFrame:
    if holding_bars <= 0:
        raise ValueError("holding_bars must be positive for path-aware labeling.")
    if stop_loss_pips <= 0 or take_profit_pips <= 0:
        raise ValueError("stop_loss_pips and take_profit_pips must be positive for path-aware labeling.")

    data = frame.copy()
    close = data["mid_c"].to_numpy(dtype="float64")
    open_ = _price_array(data, "mid_o")
    high = _price_array(data, "mid_h")
    low = _price_array(data, "mid_l")

    future_price = np.full(len(data), np.nan, dtype="float64")
    if holding_bars < len(data):
        future_price[:-holding_bars] = close[holding_bars:]
    data["future_return_pips"] = (future_price - close) * PIP_SCALE
    data["timeout_return_pips"] = data["future_return_pips"]

    long_outcome_pips, long_exit_reason, long_event_bar_offset = _path_outcomes(
        open_=open_,
        close=close,
        high=high,
        low=low,
        holding_bars=holding_bars,
        stop_loss_pips=stop_loss_pips,
        take_profit_pips=take_profit_pips,
        side="long",
    )
    short_outcome_pips, short_exit_reason, short_event_bar_offset = _path_outcomes(
        open_=open_,
        close=close,
        high=high,
        low=low,
        holding_bars=holding_bars,
        stop_loss_pips=stop_loss_pips,
        take_profit_pips=take_profit_pips,
        side="short",
    )

    data["long_outcome_pips"] = long_outcome_pips
    data["short_outcome_pips"] = short_outcome_pips
    data["long_exit_reason"] = pd.Series(long_exit_reason, index=data.index, dtype="object")
    data["short_exit_reason"] = pd.Series(short_exit_reason, index=data.index, dtype="object")
    data["long_event_bar_offset"] = long_event_bar_offset
    data["short_event_bar_offset"] = short_event_bar_offset

    data["label_up"] = pd.Series(pd.array([pd.NA] * len(data), dtype="Int64"), index=data.index)
    data["label_down"] = pd.Series(pd.array([pd.NA] * len(data), dtype="Int64"), index=data.index)
    valid_long = ~np.isnan(long_outcome_pips)
    valid_short = ~np.isnan(short_outcome_pips)
    data.loc[valid_long, "label_up"] = (long_outcome_pips[valid_long] > 0).astype(int)
    data.loc[valid_short, "label_down"] = (short_outcome_pips[valid_short] > 0).astype(int)
    return data


def _path_outcomes(
    *,
    open_: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    holding_bars: int,
    stop_loss_pips: float,
    take_profit_pips: float,
    side: str,
) -> tuple[np.ndarray, list[str | None], np.ndarray]:
    outcome_pips = np.full(len(close), np.nan, dtype="float64")
    event_bar_offset = np.full(len(close), np.nan, dtype="float64")
    exit_reason: list[str | None] = [None] * len(close)
    stop_distance = stop_loss_pips / PIP_SCALE
    target_distance = take_profit_pips / PIP_SCALE

    for index in range(0, max(len(close) - holding_bars, 0)):
        entry_price = close[index]
        timeout_index = index + holding_bars
        target_price = entry_price + target_distance if side == "long" else entry_price - target_distance
        stop_price = entry_price - stop_distance if side == "long" else entry_price + stop_distance

        resolved = False
        for offset, lookahead_index in enumerate(range(index + 1, timeout_index + 1), start=1):
            target_hit = high[lookahead_index] >= target_price if side == "long" else low[lookahead_index] <= target_price
            stop_hit = low[lookahead_index] <= stop_price if side == "long" else high[lookahead_index] >= stop_price
            if not target_hit and not stop_hit:
                continue
            if target_hit and stop_hit:
                resolution = _resolve_same_bar_hit(
                    side=side,
                    bar_open=open_[lookahead_index],
                    bar_close=close[lookahead_index],
                )
            else:
                resolution = "take_profit" if target_hit else "stop_loss"
            outcome_pips[index] = take_profit_pips if resolution == "take_profit" else -stop_loss_pips
            event_bar_offset[index] = float(offset)
            exit_reason[index] = resolution
            resolved = True
            break

        if resolved:
            continue

        timeout_return_pips = (close[timeout_index] - entry_price) * PIP_SCALE
        if side == "short":
            timeout_return_pips *= -1
        outcome_pips[index] = timeout_return_pips
        event_bar_offset[index] = float(holding_bars)
        exit_reason[index] = "time_exit"

    return outcome_pips, exit_reason, event_bar_offset


def _resolve_same_bar_hit(*, side: str, bar_open: float, bar_close: float) -> str:
    # Use the bar direction as a deterministic tie-break when both barriers print in the same bar.
    if side == "long":
        return "take_profit" if bar_close >= bar_open else "stop_loss"
    return "take_profit" if bar_close <= bar_open else "stop_loss"


def _price_array(data: pd.DataFrame, column: str) -> np.ndarray:
    if column in data.columns:
        return data[column].to_numpy(dtype="float64")
    if column == "mid_o":
        return data["mid_c"].shift(1).fillna(data["mid_c"]).to_numpy(dtype="float64")
    return data["mid_c"].to_numpy(dtype="float64")
