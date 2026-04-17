from __future__ import annotations

from agentic_forex.workflows.contracts import StrategySpec


def render_candidate_ea(
    spec: StrategySpec,
    *,
    audit_relative_path: str = "AgenticForex\\Audit\\candidate_audit.csv",
    broker_history_relative_path: str = "AgenticForex\\Audit\\candidate_broker_history.csv",
    diagnostic_windows_relative_path: str = "",
    diagnostic_ticks_relative_path: str = "",
    runtime_summary_relative_path: str = "",
    signal_trace_relative_path: str = "",
    packet_run_id: str = "packet",
    broker_timezone: str = "UTC",
    shadow_mode_only: bool = False,
) -> str:
    allowed_hours = ",".join(str(hour) for hour in spec.session_policy.allowed_hours_utc)
    filters = {item.name: item.rule for item in spec.filters}
    pip_size = _pip_size_expression(spec.instrument)
    trailing_stop_enabled = getattr(spec, "trailing_stop_enabled", False) and spec.trailing_stop_pips
    trailing_stop_pips_val = spec.trailing_stop_pips if trailing_stop_enabled else 0.0
    max_spread = _float_or_default(filters.get("max_spread_pips"), spec.risk_envelope.max_spread_allowed_pips)
    min_volatility_20 = _float_or_default(filters.get("min_volatility_20"), 0.0)
    breakout_zscore_floor = _float_or_default(filters.get("breakout_zscore_floor"), 0.0)
    max_range_width_10_pips = _float_or_default(filters.get("max_range_width_10_pips"), 0.0)
    compression_range_position_floor = _float_or_default(filters.get("compression_range_position_floor"), 0.65)
    extension_zscore_floor = _float_or_default(filters.get("extension_zscore_floor"), 0.0)
    reclaim_range_position_floor = _float_or_default(filters.get("reclaim_range_position_floor"), 0.12)
    reclaim_range_position_ceiling = _float_or_default(filters.get("reclaim_range_position_ceiling"), 0.42)
    reclaim_momentum_ceiling = _float_or_default(filters.get("reclaim_momentum_ceiling"), 4.0)
    ret_5_floor = _float_or_default(filters.get("ret_5_floor"), 0.0)
    trend_ret_5_min = _float_or_default(filters.get("trend_ret_5_min"), 0.0)
    pullback_zscore_limit = _float_or_default(filters.get("pullback_zscore_limit"), 0.45)
    retest_zscore_limit = _float_or_default(filters.get("retest_zscore_limit"), 0.35)
    retest_range_position_floor = _float_or_default(filters.get("retest_range_position_floor"), 0.52)
    continuation_zscore_floor = _float_or_default(filters.get("continuation_zscore_floor"), 0.08)
    continuation_zscore_ceiling = _float_or_default(filters.get("continuation_zscore_ceiling"), 0.72)
    continuation_range_position_floor = _float_or_default(filters.get("continuation_range_position_floor"), 0.60)
    fade_ret_5_floor = _float_or_default(filters.get("fade_ret_5_floor"), 0.0)
    fade_momentum_ceiling = _float_or_default(filters.get("fade_momentum_ceiling"), 3.2)
    excluded_context = _string_literal(filters.get("exclude_context_bucket", ""))
    required_volatility_bucket = _string_literal(filters.get("required_volatility_bucket", ""))
    require_ret_5_alignment = _bool_literal(filters.get("require_ret_5_alignment"))
    require_mean_location_alignment = _bool_literal(filters.get("require_mean_location_alignment"))
    require_ret_1_confirmation = _bool_literal(filters.get("require_ret_1_confirmation"))
    require_reclaim_ret_1 = _bool_literal(filters.get("require_reclaim_ret_1"))
    require_recovery_ret_1 = _bool_literal(filters.get("require_recovery_ret_1"))
    require_reversal_ret_1 = _bool_literal(filters.get("require_reversal_ret_1"))
    require_reversal_momentum = _bool_literal(filters.get("require_reversal_momentum"))
    fixed_lots = min(spec.account_model.max_total_exposure_lots, 5.0)
    magic_number = _magic_number(spec.candidate_id)
    audit_relative_path_literal = _string_literal(audit_relative_path)
    broker_history_relative_path_literal = _string_literal(broker_history_relative_path)
    diagnostic_windows_relative_path_literal = _string_literal(diagnostic_windows_relative_path)
    diagnostic_ticks_relative_path_literal = _string_literal(diagnostic_ticks_relative_path)
    runtime_summary_relative_path_literal = _string_literal(runtime_summary_relative_path)
    signal_trace_relative_path_literal = _string_literal(signal_trace_relative_path)
    packet_run_id_literal = _string_literal(packet_run_id)
    broker_timezone_literal = _string_literal(broker_timezone)
    shadow_mode_only_literal = "true" if shadow_mode_only else "false"
    return f"""#property strict
#include <Trade/Trade.mqh>

CTrade trade;
datetime g_last_bar_time = 0;
bool g_allowed_hours[24];
bool g_has_open_trade = false;
datetime g_entry_time = 0;
datetime g_entry_bar_time = 0;
datetime g_pending_entry_bar_time = 0;
double g_entry_price = 0.0;
string g_entry_side = "";
ulong g_entry_ticket = 0;
double g_stop_loss_price = 0.0;
double g_take_profit_price = 0.0;
bool g_timeout_exit_pending = false;
double g_trailing_extreme = 0.0;
long g_trailing_stop_adjustments = 0;
long g_bars_processed = 0;
long g_allowed_hour_bars = 0;
long g_spread_blocked_bars = 0;
long g_filter_blocked_bars = 0;
long g_no_signal_bars = 0;
long g_long_signals = 0;
long g_short_signals = 0;
long g_order_attempts = 0;
long g_order_successes = 0;
long g_order_failures = 0;
long g_open_position_recoveries = 0;
long g_audit_rows_written = 0;
long g_audit_write_failures = 0;
long g_symbol_tick_failures = 0;
long g_copyrates_failures = 0;
long g_last_order_retcode = 0;

input string InpCandidateId = "{spec.candidate_id}";
input string InpPacketRunId = {packet_run_id_literal};
input ulong InpMagicNumber = {magic_number};
input double InpFixedLots = {fixed_lots:.2f};
input double InpSignalThreshold = {spec.signal_threshold:.5f};
input double InpStopLossPips = {spec.stop_loss_pips:.5f};
input double InpTakeProfitPips = {spec.take_profit_pips:.5f};
input bool InpTrailingStopEnabled = {"true" if trailing_stop_enabled else "false"};
input double InpTrailingStopPips = {trailing_stop_pips_val:.5f};
input double InpMaxSpreadPips = {max_spread:.5f};
input double InpMinVolatility20 = {min_volatility_20:.8f};
input double InpBreakoutZscoreFloor = {breakout_zscore_floor:.5f};
input double InpMaxRangeWidth10Pips = {max_range_width_10_pips:.5f};
input double InpCompressionRangePositionFloor = {compression_range_position_floor:.5f};
input double InpExtensionZscoreFloor = {extension_zscore_floor:.5f};
input double InpReclaimRangePositionFloor = {reclaim_range_position_floor:.5f};
input double InpReclaimRangePositionCeiling = {reclaim_range_position_ceiling:.5f};
input double InpReclaimMomentumCeiling = {reclaim_momentum_ceiling:.5f};
input double InpRet5Floor = {ret_5_floor:.8f};
input double InpTrendRet5Min = {trend_ret_5_min:.8f};
input double InpPullbackZscoreLimit = {pullback_zscore_limit:.5f};
input double InpRetestZscoreLimit = {retest_zscore_limit:.5f};
input double InpRetestRangePositionFloor = {retest_range_position_floor:.5f};
input double InpContinuationZscoreFloor = {continuation_zscore_floor:.5f};
input double InpContinuationZscoreCeiling = {continuation_zscore_ceiling:.5f};
input double InpContinuationRangePositionFloor = {continuation_range_position_floor:.5f};
input double InpFadeRet5Floor = {fade_ret_5_floor:.8f};
input double InpFadeMomentumCeiling = {fade_momentum_ceiling:.5f};
input bool InpRequireRet5Alignment = {require_ret_5_alignment};
input bool InpRequireMeanLocationAlignment = {require_mean_location_alignment};
input bool InpRequireRet1Confirmation = {require_ret_1_confirmation};
input bool InpRequireReclaimRet1 = {require_reclaim_ret_1};
input bool InpRequireRecoveryRet1 = {require_recovery_ret_1};
input bool InpRequireReversalRet1 = {require_reversal_ret_1};
input bool InpRequireReversalMomentum = {require_reversal_momentum};
input int InpFillDelayMs = {int(spec.execution_cost_model.fill_delay_ms)};
input int InpHoldingBars = {int(spec.holding_bars)};
input string InpAllowedHoursCsv = "{allowed_hours}";
input string InpExcludedContextBucket = {excluded_context};
input string InpRequiredVolatilityBucket = {required_volatility_bucket};
input string InpEntryStyle = "{spec.entry_style}";
input string InpAuditRelativePath = {audit_relative_path_literal};
input string InpBrokerHistoryRelativePath = {broker_history_relative_path_literal};
input string InpDiagnosticWindowsRelativePath = {diagnostic_windows_relative_path_literal};
input string InpDiagnosticTicksRelativePath = {diagnostic_ticks_relative_path_literal};
input string InpRuntimeSummaryRelativePath = {runtime_summary_relative_path_literal};
input string InpSignalTraceRelativePath = {signal_trace_relative_path_literal};
input string InpBrokerTimezone = {broker_timezone_literal};
input bool InpShadowModeOnly = {shadow_mode_only_literal};

int OnInit()
{{
   ResetAllowedHours();
   ParseAllowedHours(InpAllowedHoursCsv);
   trade.SetExpertMagicNumber(InpMagicNumber);
   CaptureOpenPositionState();
   Print("[INIT] ", InpCandidateId, " | shadow=", InpShadowModeOnly, " | style=", InpEntryStyle, " | hours=", InpAllowedHoursCsv);
   return INIT_SUCCEEDED;
}}

void OnDeinit(const int reason)
{{
   Print("[DEINIT] ", InpCandidateId, " | reason=", reason, " | bars=", g_bars_processed, " | signals=", g_long_signals + g_short_signals, " | orders=", g_order_successes);
   ExportRuntimeSummary(reason);
   ExportDiagnosticTicks();
   ExportBrokerHistory();
}}

void OnTick()
{{
   datetime current_bar = iTime(_Symbol, PERIOD_M1, 0);
   if(current_bar == 0 || current_bar == g_last_bar_time)
      return;
   g_last_bar_time = current_bar;
   g_bars_processed++;

   int bar_hour_utc = HourUtc(current_bar);
   Comment(InpCandidateId, " | ", (InpShadowModeOnly ? "SHADOW" : "LIVE"),
      "\\nBars: ", g_bars_processed, " | UTC hour: ", bar_hour_utc,
      "\\nSignals: ", g_long_signals + g_short_signals, " (L:", g_long_signals, " S:", g_short_signals, ")",
      "\\nOrders: ", g_order_successes, " | Spread blocked: ", g_spread_blocked_bars,
      "\\nLast bar: ", TimeToString(current_bar, TIME_DATE | TIME_MINUTES));

   if(HasOpenPosition())
   {{
      CaptureOpenPositionState();
      if(InpTrailingStopEnabled && InpTrailingStopPips > 0 && g_has_open_trade)
      {{
         MqlTick trail_tick;
         if(SymbolInfoTick(_Symbol, trail_tick))
         {{
            double pip_sz = {pip_size};
            if(g_entry_side == "long")
            {{
               if(trail_tick.bid > g_trailing_extreme)
                  g_trailing_extreme = trail_tick.bid;
               double new_sl = g_trailing_extreme - InpTrailingStopPips * pip_sz;
               double fixed_sl = g_entry_price - InpStopLossPips * pip_sz;
               if(new_sl > fixed_sl && new_sl > g_stop_loss_price + 0.1 * pip_sz)
               {{
                  if(trade.PositionModify(_Symbol, NormalizeDouble(new_sl, _Digits), g_take_profit_price))
                  {{
                     g_stop_loss_price = new_sl;
                     g_trailing_stop_adjustments++;
                  }}
               }}
            }}
            else if(g_entry_side == "short")
            {{
               if(g_trailing_extreme == 0.0 || trail_tick.ask < g_trailing_extreme)
                  g_trailing_extreme = trail_tick.ask;
               double new_sl = g_trailing_extreme + InpTrailingStopPips * pip_sz;
               double fixed_sl = g_entry_price + InpStopLossPips * pip_sz;
               if(new_sl < fixed_sl && new_sl < g_stop_loss_price - 0.1 * pip_sz)
               {{
                  if(trade.PositionModify(_Symbol, NormalizeDouble(new_sl, _Digits), g_take_profit_price))
                  {{
                     g_stop_loss_price = new_sl;
                     g_trailing_stop_adjustments++;
                  }}
               }}
            }}
         }}
      }}
      if(ShouldTimeExit(current_bar))
      {{
         g_timeout_exit_pending = true;
         trade.PositionClose(_Symbol);
      }}
      return;
   }}

   ResetOpenTradeState();

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
   {{
      g_symbol_tick_failures++;
      return;
   }}

   double spread_pips = (tick.ask - tick.bid) / {pip_size};
   if(spread_pips > InpMaxSpreadPips)
   {{
      g_spread_blocked_bars++;
      Print("[BAR ", g_bars_processed, "] spread=", DoubleToString(spread_pips, 2), " > max=", DoubleToString(InpMaxSpreadPips, 2), " \u2014 BLOCKED");
      return;
   }}

   int trade_hour = HourUtc(current_bar);
   if(!g_allowed_hours[trade_hour])
   {{
      Print("[BAR ", g_bars_processed, "] UTC hour=", trade_hour, " \u2014 outside allowed hours");
      return;
   }}
   g_allowed_hour_bars++;
   Print("[BAR ", g_bars_processed, "] UTC hour=", trade_hour, " \u2014 IN WINDOW | spread=", DoubleToString(spread_pips, 2));

   int signal = GenerateSignal();
   if(signal == 0)
   {{
      g_no_signal_bars++;
      Print("[BAR ", g_bars_processed, "] no signal");
      return;
   }}
   if(signal > 0)
      g_long_signals++;
   else
      g_short_signals++;
   Print("[BAR ", g_bars_processed, "] >>> SIGNAL: ", (signal > 0 ? "LONG" : "SHORT"), " | total_signals=", g_long_signals + g_short_signals);
   WriteSignalTraceRow(current_bar, signal, spread_pips);

   if(InpFillDelayMs > 0)
      Sleep(InpFillDelayMs);

   if(!SymbolInfoTick(_Symbol, tick))
   {{
      g_symbol_tick_failures++;
      return;
   }}

   double pip_size = {pip_size};
   double lots = NormalizeDouble(InpFixedLots, 2);
   bool placed = false;
   g_pending_entry_bar_time = current_bar;
   g_order_attempts++;
   if(InpShadowModeOnly)
   {{
      g_order_successes++;
      Print("[BAR ", g_bars_processed, "] SHADOW ORDER: ", (signal > 0 ? "BUY" : "SELL"), " ", DoubleToString(lots, 2), " lots @ ", DoubleToString(signal > 0 ? tick.ask : tick.bid, _Digits), " \u2014 NOT PLACED (shadow mode)");
   }}
   else
   {{
      if(signal > 0)
      {{
         double price = tick.ask;
         double sl = price - (InpStopLossPips * pip_size);
         double tp = price + (InpTakeProfitPips * pip_size);
         placed = trade.Buy(lots, _Symbol, price, sl, tp, InpCandidateId);
      }}
      else
      {{
         double price = tick.bid;
         double sl = price + (InpStopLossPips * pip_size);
         double tp = price - (InpTakeProfitPips * pip_size);
         placed = trade.Sell(lots, _Symbol, price, sl, tp, InpCandidateId);
      }}

      g_last_order_retcode = (long)trade.ResultRetcode();
      if(placed)
      {{
         g_order_successes++;
         g_entry_bar_time = current_bar;
         CaptureOpenPositionState();
      }}
      else
      {{
         g_pending_entry_bar_time = 0;
         g_order_failures++;
      }}
   }}
}}

void OnTradeTransaction(
   const MqlTradeTransaction &trans,
   const MqlTradeRequest &request,
   const MqlTradeResult &result
)
{{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;
   if(trans.symbol != _Symbol)
      return;
   if(!HistoryDealSelect(trans.deal))
      return;

   long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
   if((ulong)magic != InpMagicNumber)
      return;

   long entry_type = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry_type == DEAL_ENTRY_IN)
   {{
      g_has_open_trade = true;
      g_entry_ticket = trans.deal;
      g_entry_time = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
      g_entry_bar_time = g_pending_entry_bar_time > 0 ? g_pending_entry_bar_time : NormalizeBarOpen(g_entry_time);
      g_entry_price = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
      long deal_type = HistoryDealGetInteger(trans.deal, DEAL_TYPE);
      g_entry_side = (deal_type == DEAL_TYPE_BUY) ? "long" : "short";
      if(g_entry_side == "long")
      {{
         g_stop_loss_price = g_entry_price - (InpStopLossPips * {pip_size});
         g_take_profit_price = g_entry_price + (InpTakeProfitPips * {pip_size});
      }}
      else
      {{
         g_stop_loss_price = g_entry_price + (InpStopLossPips * {pip_size});
         g_take_profit_price = g_entry_price - (InpTakeProfitPips * {pip_size});
      }}
      g_timeout_exit_pending = false;
      g_trailing_extreme = g_entry_price;
      g_pending_entry_bar_time = 0;
      return;
   }}

   if(entry_type != DEAL_ENTRY_OUT && entry_type != DEAL_ENTRY_OUT_BY)
      return;
   if(!g_has_open_trade)
      return;

   datetime exit_time = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
   double exit_price = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
      + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
      + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   double pnl_pips = 0.0;
   double pip_size = {pip_size};
   if(g_entry_side == "long")
      pnl_pips = (exit_price - g_entry_price) / pip_size;
   else if(g_entry_side == "short")
      pnl_pips = (g_entry_price - exit_price) / pip_size;
   string exit_reason = MapExitReason((int)HistoryDealGetInteger(trans.deal, DEAL_REASON));
   if(g_timeout_exit_pending && exit_reason == "expert")
      exit_reason = "timeout";
   bool same_bar_collision = ExitBarCollision(g_entry_side, g_stop_loss_price, g_take_profit_price, exit_time);

   WriteAuditRow(
      g_entry_bar_time,
      exit_time,
      g_entry_side,
      g_entry_price,
      exit_price,
      pnl_pips,
      profit,
      exit_reason,
      g_stop_loss_price,
      g_take_profit_price,
      same_bar_collision,
      trans.deal
   );
   ResetOpenTradeState();
}}

bool HasOpenPosition()
{{
   for(int i = 0; i < PositionsTotal(); i++)
   {{
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol)
         return true;
   }}
   return false;
}}

bool ShouldTimeExit(datetime current_bar)
{{
   if(!g_has_open_trade || InpHoldingBars <= 0)
      return false;
   datetime anchor_bar = g_entry_bar_time > 0 ? g_entry_bar_time : NormalizeBarOpen(g_entry_time);
   int bars_since_entry = iBarShift(_Symbol, PERIOD_M1, anchor_bar, true);
   int current_shift = iBarShift(_Symbol, PERIOD_M1, current_bar, true);
   if(bars_since_entry < 0 || current_shift < 0)
      return false;
   return (bars_since_entry - current_shift) >= InpHoldingBars;
}}

datetime NormalizeBarOpen(datetime value)
{{
   if(value <= 0)
      return 0;
   int shift = iBarShift(_Symbol, PERIOD_M1, value, false);
   if(shift < 0)
      return value;
   datetime bar_open = iTime(_Symbol, PERIOD_M1, shift);
   return bar_open > 0 ? bar_open : value;
}}

void CaptureOpenPositionState()
{{
   if(!PositionSelect(_Symbol))
   {{
      ResetOpenTradeState();
      return;
   }}
   if(!g_has_open_trade)
      g_open_position_recoveries++;
   g_has_open_trade = true;
   g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
   if(g_entry_bar_time <= 0)
      g_entry_bar_time = g_pending_entry_bar_time > 0 ? g_pending_entry_bar_time : NormalizeBarOpen(g_entry_time);
   g_entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
   long position_type = PositionGetInteger(POSITION_TYPE);
   g_entry_side = (position_type == POSITION_TYPE_BUY) ? "long" : "short";
   g_entry_ticket = (ulong)PositionGetInteger(POSITION_TICKET);
    g_stop_loss_price = PositionGetDouble(POSITION_SL);
    g_take_profit_price = PositionGetDouble(POSITION_TP);
}}

void ResetOpenTradeState()
{{
   g_has_open_trade = false;
   g_entry_time = 0;
   g_entry_bar_time = 0;
   g_pending_entry_bar_time = 0;
   g_entry_price = 0.0;
   g_entry_side = "";
   g_entry_ticket = 0;
    g_stop_loss_price = 0.0;
    g_take_profit_price = 0.0;
    g_timeout_exit_pending = false;
    g_trailing_extreme = 0.0;
}}

void ResetAllowedHours()
{{
   for(int hour = 0; hour < 24; hour++)
      g_allowed_hours[hour] = false;
}}

void ParseAllowedHours(string csv)
{{
   string parts[];
   int count = StringSplit(csv, ',', parts);
   for(int i = 0; i < count; i++)
   {{
      int hour = (int)StringToInteger(parts[i]);
      if(hour >= 0 && hour < 24)
         g_allowed_hours[hour] = true;
   }}
}}

int GenerateSignal()
{{
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int bars_copied = CopyRates(_Symbol, PERIOD_M1, 0, 40, rates);
   if(bars_copied < 25)
   {{
      g_copyrates_failures++;
      return 0;
   }}

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(point <= 0.0)
      point = {pip_size} / 10.0;

   double closes[];
   double highs[];
   double lows[];
   ArrayResize(closes, bars_copied);
   ArrayResize(highs, bars_copied);
   ArrayResize(lows, bars_copied);
   for(int i = 0; i < bars_copied; i++)
   {{
      double mid_offset = ((double)MathMax((long)rates[i].spread, 0) * point) / 2.0;
      closes[i] = rates[i].close + mid_offset;
      highs[i] = rates[i].high + mid_offset;
      lows[i] = rates[i].low + mid_offset;
   }}

   double c1 = closes[1];
   double c2 = closes[2];
   double c6 = closes[6];
   double c13 = closes[13];

   double ret_1 = c2 == 0.0 ? 0.0 : (c1 / c2) - 1.0;
   double ret_5 = c6 == 0.0 ? 0.0 : (c1 / c6) - 1.0;
   double rolling_mean_10 = Mean(closes, 1, 10);
   double rolling_std_10 = StdDev(closes, 1, 10);
   if(rolling_std_10 <= 0.0)
      rolling_std_10 = 1e-9;
   double zscore_10 = (c1 - rolling_mean_10) / rolling_std_10;
   double range_high_10 = MaxValue(highs, 1, 10);
   double range_low_10 = MinValue(lows, 1, 10);
   double range_width_10_pips = (range_high_10 - range_low_10) / {pip_size};
   double range_position_10 = 0.5;
   if(range_high_10 > range_low_10)
      range_position_10 = (c1 - range_low_10) / (range_high_10 - range_low_10);
   double momentum_12 = (c1 - c13) * 10000.0;
   double volatility_20 = ReturnStdDev(closes, 1, 20);
   string context_bucket = ContextBucket(zscore_10, momentum_12);

   if(!PassesCommonFilters(spread_pips_current(), volatility_20, context_bucket))
   {{
      g_filter_blocked_bars++;
      return 0;
   }}

   if(InpEntryStyle == "session_breakout")
   {{
      if(momentum_12 >= InpSignalThreshold)
      {{
         if(InpRequireRet5Alignment && ret_5 <= 0.0)
            return 0;
         if(InpRet5Floor > 0.0 && ret_5 < InpRet5Floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpBreakoutZscoreFloor > 0.0 && zscore_10 < InpBreakoutZscoreFloor)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -InpSignalThreshold)
      {{
         if(InpRequireRet5Alignment && ret_5 >= 0.0)
            return 0;
         if(InpRet5Floor > 0.0 && ret_5 > -InpRet5Floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpBreakoutZscoreFloor > 0.0 && zscore_10 > -InpBreakoutZscoreFloor)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "volatility_breakout")
   {{
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.55;
      if(momentum_12 >= InpSignalThreshold)
      {{
         if(InpRequireRet5Alignment && ret_5 <= 0.0)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(zscore_10 < breakout_floor)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -InpSignalThreshold)
      {{
         if(InpRequireRet5Alignment && ret_5 >= 0.0)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(zscore_10 > -breakout_floor)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "volatility_expansion")
   {{
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : MathMax(InpSignalThreshold * 0.85, 0.65);
      double minimum_ret_5 = InpRet5Floor > 0.0 ? InpRet5Floor : 0.00006;
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00003))
         return 0;
      if(momentum_12 >= InpSignalThreshold && zscore_10 >= breakout_floor)
      {{
         if(ret_5 < minimum_ret_5)
            return 0;
         if(ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -InpSignalThreshold && zscore_10 <= -breakout_floor)
      {{
         if(ret_5 > -minimum_ret_5)
            return 0;
         if(ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "volatility_retest_breakout" || InpEntryStyle == "overlap_event_retest_breakout")
   {{
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.55;
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00008;
      double retest_limit = InpRetestZscoreLimit > 0.0 ? InpRetestZscoreLimit : 0.35;
      double retest_position_floor = InpRetestRangePositionFloor > 0.0 ? InpRetestRangePositionFloor : 0.55;
      double momentum_floor = MathMax(InpSignalThreshold * 0.65, 0.55);
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00004))
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {{
         if(!(zscore_10 >= -retest_limit && zscore_10 <= breakout_floor))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {{
         if(!(zscore_10 >= -breakout_floor && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "overlap_persistence_band")
   {{
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00008;
      double continuation_floor = InpContinuationZscoreFloor > 0.0 ? InpContinuationZscoreFloor : 0.08;
      double continuation_ceiling = InpContinuationZscoreCeiling > 0.0 ? InpContinuationZscoreCeiling : 0.72;
      double continuation_position_floor = InpContinuationRangePositionFloor > 0.0 ? InpContinuationRangePositionFloor : 0.60;
      double momentum_floor = MathMax(InpSignalThreshold * 0.70, 0.60);
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00005))
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {{
         if(!(zscore_10 >= continuation_floor && zscore_10 <= continuation_ceiling))
            return 0;
         if(range_position_10 < continuation_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {{
         if(!(zscore_10 >= -continuation_ceiling && zscore_10 <= -continuation_floor))
            return 0;
         if(range_position_10 > (1.0 - continuation_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "session_momentum_band")
   {{
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00007;
      double continuation_floor = InpContinuationZscoreFloor > 0.0 ? InpContinuationZscoreFloor : 0.20;
      double continuation_ceiling = InpContinuationZscoreCeiling > 0.0 ? InpContinuationZscoreCeiling : 1.05;
      double continuation_position_floor = InpContinuationRangePositionFloor > 0.0 ? InpContinuationRangePositionFloor : 0.64;
      double momentum_floor = MathMax(InpSignalThreshold, 0.75);
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00004))
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {{
         if(!(zscore_10 >= continuation_floor && zscore_10 <= continuation_ceiling))
            return 0;
         if(range_position_10 < continuation_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRet1Confirmation && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {{
         if(!(zscore_10 >= -continuation_ceiling && zscore_10 <= -continuation_floor))
            return 0;
         if(range_position_10 > (1.0 - continuation_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRet1Confirmation && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "compression_breakout")
   {{
      double compression_ceiling = InpMaxRangeWidth10Pips > 0.0 ? InpMaxRangeWidth10Pips : 9.0;
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.45;
      double range_position_floor = InpCompressionRangePositionFloor > 0.0 ? InpCompressionRangePositionFloor : 0.65;
      if(range_width_10_pips > compression_ceiling)
         return 0;
      if(momentum_12 >= InpSignalThreshold)
      {{
         if(zscore_10 < breakout_floor)
            return 0;
         if(range_position_10 < range_position_floor)
            return 0;
         if(InpRequireRet1Confirmation && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -InpSignalThreshold)
      {{
         if(zscore_10 > -breakout_floor)
            return 0;
         if(range_position_10 > (1.0 - range_position_floor))
            return 0;
         if(InpRequireRet1Confirmation && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "compression_retest_breakout")
   {{
      double compression_ceiling = InpMaxRangeWidth10Pips > 0.0 ? InpMaxRangeWidth10Pips : 8.5;
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.40;
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00008;
      double retest_limit = InpRetestZscoreLimit > 0.0 ? InpRetestZscoreLimit : 0.30;
      double retest_position_floor = InpRetestRangePositionFloor > 0.0 ? InpRetestRangePositionFloor : 0.56;
      double momentum_floor = MathMax(InpSignalThreshold * 0.7, 0.55);
      if(range_width_10_pips > compression_ceiling)
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {{
         if(!(zscore_10 >= -retest_limit && zscore_10 <= breakout_floor))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {{
         if(!(zscore_10 >= -breakout_floor && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "range_reclaim")
   {{
      double extension_floor = InpExtensionZscoreFloor > 0.0 ? InpExtensionZscoreFloor : 1.05;
      double reclaim_floor = InpReclaimRangePositionFloor > 0.0 ? InpReclaimRangePositionFloor : 0.12;
      double reclaim_ceiling = InpReclaimRangePositionCeiling > 0.0 ? InpReclaimRangePositionCeiling : 0.42;
      double momentum_ceiling = InpReclaimMomentumCeiling > 0.0 ? InpReclaimMomentumCeiling : 4.0;
      if(zscore_10 <= -extension_floor)
      {{
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         if(!(range_position_10 >= reclaim_floor && range_position_10 <= reclaim_ceiling))
            return 0;
         if(InpRequireReclaimRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(zscore_10 >= extension_floor)
      {{
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         if(!(range_position_10 >= (1.0 - reclaim_ceiling) && range_position_10 <= (1.0 - reclaim_floor)))
            return 0;
         if(InpRequireReclaimRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "pullback_continuation")
   {{
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00008;
      double pullback_limit = InpPullbackZscoreLimit > 0.0 ? InpPullbackZscoreLimit : 0.45;
      if(momentum_12 >= InpSignalThreshold && ret_5 >= trend_floor)
      {{
         if(!(zscore_10 >= -pullback_limit && zscore_10 <= 0.15))
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -InpSignalThreshold && ret_5 <= -trend_floor)
      {{
         if(!(zscore_10 >= -0.15 && zscore_10 <= pullback_limit))
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "overlap_persistence_retest")
   {{
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.57;
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00009;
      double retest_limit = InpRetestZscoreLimit > 0.0 ? InpRetestZscoreLimit : 0.32;
      double retest_position_floor = InpRetestRangePositionFloor > 0.0 ? InpRetestRangePositionFloor : 0.58;
      double momentum_floor = MathMax(InpSignalThreshold * 0.70, 0.60);
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00006))
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {{
         if(!(zscore_10 >= -retest_limit && zscore_10 <= breakout_floor))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {{
         if(!(zscore_10 >= -breakout_floor && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "high_vol_overlap_persistence_retest")
   {{
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.57;
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00009;
      double retest_limit = InpRetestZscoreLimit > 0.0 ? InpRetestZscoreLimit : 0.32;
      double retest_position_floor = InpRetestRangePositionFloor > 0.0 ? InpRetestRangePositionFloor : 0.58;
      double momentum_floor = MathMax(InpSignalThreshold * 0.70, 0.60);
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00006))
         return 0;
      if(VolatilityBucket(volatility_20) != "high")
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {{
         if(!(zscore_10 >= -retest_limit && zscore_10 <= breakout_floor))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {{
         if(!(zscore_10 >= -breakout_floor && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "trend_retest")
   {{
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00012;
      double retest_limit = InpRetestZscoreLimit > 0.0 ? InpRetestZscoreLimit : 0.35;
      double retest_position_floor = InpRetestRangePositionFloor > 0.0 ? InpRetestRangePositionFloor : 0.52;
      if(momentum_12 >= InpSignalThreshold && ret_5 >= trend_floor)
      {{
         if(!(zscore_10 >= -retest_limit && zscore_10 <= 0.25))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -InpSignalThreshold && ret_5 <= -trend_floor)
      {{
         if(!(zscore_10 >= -0.25 && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "trend_pullback_retest")
   {{
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00005;
      double pullback_limit = InpPullbackZscoreLimit > 0.0 ? InpPullbackZscoreLimit : 0.55;
      if(ret_5 >= trend_floor && ret_1 > 0.0 && zscore_10 >= -pullback_limit && zscore_10 <= 0.35)
      {{
         if(momentum_12 < InpSignalThreshold * 0.5)
            return 0;
         return 1;
      }}
      if(ret_5 <= -trend_floor && ret_1 < 0.0 && zscore_10 <= pullback_limit && zscore_10 >= -0.35)
      {{
         if(momentum_12 > -InpSignalThreshold * 0.5)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "failed_break_fade")
   {{
      double fade_floor = InpFadeRet5Floor > 0.0 ? InpFadeRet5Floor : 0.00005;
      double momentum_ceiling = InpFadeMomentumCeiling > 0.0 ? InpFadeMomentumCeiling : 3.2;
      if(zscore_10 <= -MathAbs(InpSignalThreshold))
      {{
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         if(ret_5 >= -fade_floor)
            return 0;
         if(InpRequireReversalRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(zscore_10 >= MathAbs(InpSignalThreshold))
      {{
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         if(ret_5 <= fade_floor)
            return 0;
         if(InpRequireReversalRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "session_extreme_reversion")
   {{
      double extreme_floor = MathMax(MathAbs(InpSignalThreshold), 0.65);
      double fade_floor = InpFadeRet5Floor > 0.0 ? InpFadeRet5Floor : 0.00004;
      double momentum_ceiling = InpFadeMomentumCeiling > 0.0 ? InpFadeMomentumCeiling : 4.0;
      if(zscore_10 <= -extreme_floor)
      {{
         if(ret_5 > -fade_floor)
            return 0;
         if(ret_1 <= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return 1;
      }}
      if(zscore_10 >= extreme_floor)
      {{
         if(ret_5 < fade_floor)
            return 0;
         if(ret_1 >= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "compression_reversion")
   {{
      double compression_ceiling = InpMaxRangeWidth10Pips > 0.0 ? InpMaxRangeWidth10Pips : 8.0;
      double extreme_floor = MathMax(MathAbs(InpSignalThreshold), 0.9);
      double reclaim_floor = InpReclaimRangePositionFloor > 0.0 ? InpReclaimRangePositionFloor : 0.18;
      double reclaim_ceiling = InpReclaimRangePositionCeiling > 0.0 ? InpReclaimRangePositionCeiling : 0.45;
      double momentum_ceiling = InpReclaimMomentumCeiling > 0.0 ? InpReclaimMomentumCeiling : 3.6;
      if(range_width_10_pips > compression_ceiling)
         return 0;
      if(zscore_10 <= -extreme_floor)
      {{
         if(!(range_position_10 >= reclaim_floor && range_position_10 <= reclaim_ceiling))
            return 0;
         if(InpRequireReversalRet1 && ret_1 <= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return 1;
      }}
      if(zscore_10 >= extreme_floor)
      {{
         if(!(range_position_10 >= (1.0 - reclaim_ceiling) && range_position_10 <= (1.0 - reclaim_floor)))
            return 0;
         if(InpRequireReversalRet1 && ret_1 >= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "drift_reclaim")
   {{
      double extension_floor = MathMax(MathAbs(InpSignalThreshold) * 0.95, 0.85);
      double drift_floor = 0.00005;
      double reclaim_floor = 0.30;
      double reclaim_ceiling = 0.58;
      double momentum_ceiling = 5.0;
      if(zscore_10 <= -extension_floor)
      {{
         if(ret_5 > -drift_floor)
            return 0;
         if(!(range_position_10 >= reclaim_floor && range_position_10 <= reclaim_ceiling))
            return 0;
         if(ret_1 <= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return 1;
      }}
      if(zscore_10 >= extension_floor)
      {{
         if(ret_5 < drift_floor)
            return 0;
         if(!(range_position_10 >= (1.0 - reclaim_ceiling) && range_position_10 <= (1.0 - reclaim_floor)))
            return 0;
         if(ret_1 >= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "balance_area_breakout")
   {{
      double compression_ceiling = 8.5;
      double breakout_floor = MathMax(InpSignalThreshold * 0.7, 0.45);
      double range_position_floor = 0.60;
      double momentum_floor = InpSignalThreshold * 0.8;
      if(range_width_10_pips > compression_ceiling)
         return 0;
      if(momentum_12 >= momentum_floor)
      {{
         if(zscore_10 < breakout_floor)
            return 0;
         if(range_position_10 < range_position_floor)
            return 0;
         if(ret_5 <= 0.0 || ret_1 <= 0.0)
            return 0;
         return 1;
      }}
      if(momentum_12 <= -momentum_floor)
      {{
         if(zscore_10 > -breakout_floor)
            return 0;
         if(range_position_10 > (1.0 - range_position_floor))
            return 0;
         if(ret_5 >= 0.0 || ret_1 >= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   if(InpEntryStyle == "mean_reversion_pullback")
   {{
      if(zscore_10 <= -MathAbs(InpSignalThreshold))
      {{
         if(InpRequireReversalRet1 && ret_1 <= 0.0)
            return 0;
         if(InpRequireReversalMomentum && momentum_12 >= 0.0)
            return 0;
         return 1;
      }}
      if(zscore_10 >= MathAbs(InpSignalThreshold))
      {{
         if(InpRequireReversalRet1 && ret_1 >= 0.0)
            return 0;
         if(InpRequireReversalMomentum && momentum_12 <= 0.0)
            return 0;
         return -1;
      }}
      return 0;
   }}

   return 0;
}}

bool PassesCommonFilters(double spread_pips, double volatility_20, string context_bucket)
{{
   if(spread_pips > InpMaxSpreadPips)
      return false;
   if(InpMinVolatility20 > 0.0 && volatility_20 < InpMinVolatility20)
      return false;
   if(InpRequiredVolatilityBucket != "" && VolatilityBucket(volatility_20) != InpRequiredVolatilityBucket)
      return false;
   if(InpExcludedContextBucket != "" && context_bucket == InpExcludedContextBucket)
      return false;
   return true;
}}

double spread_pips_current()
{{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return 0.0;
   return (tick.ask - tick.bid) / {pip_size};
}}

double Mean(const double &values[], int start, int count)
{{
   double total = 0.0;
   for(int i = start; i < start + count; i++)
      total += values[i];
   return total / count;
}}

double StdDev(const double &values[], int start, int count)
{{
   double mean = Mean(values, start, count);
   double total = 0.0;
   for(int i = start; i < start + count; i++)
   {{
      double diff = values[i] - mean;
      total += diff * diff;
   }}
   return MathSqrt(total / count);
}}

double MaxValue(const double &values[], int start, int count)
{{
   double value = values[start];
   for(int i = start + 1; i < start + count; i++)
   {{
      if(values[i] > value)
         value = values[i];
   }}
   return value;
}}

double MinValue(const double &values[], int start, int count)
{{
   double value = values[start];
   for(int i = start + 1; i < start + count; i++)
   {{
      if(values[i] < value)
         value = values[i];
   }}
   return value;
}}

double ReturnStdDev(const double &values[], int start, int count)
{{
   double returns[];
   ArrayResize(returns, count);
   for(int i = 0; i < count; i++)
   {{
      double previous = values[start + i + 1];
      double current = values[start + i];
      returns[i] = previous == 0.0 ? 0.0 : (current / previous) - 1.0;
   }}
   return StdDev(returns, 0, count);
}}

string ContextBucket(double zscore_10, double momentum_12)
{{
   if(MathAbs(zscore_10) >= 1.2)
      return "mean_reversion_context";
   if(MathAbs(momentum_12) >= 0.8)
      return "trend_context";
   return "neutral_context";
}}

string VolatilityBucket(double volatility_20)
{{
   if(volatility_20 <= 0.00005)
      return "low";
   if(volatility_20 <= 0.00012)
      return "medium";
   return "high";
}}

int HourUtc(datetime value)
{{
   MqlDateTime parts;
   TimeToStruct(ConvertBrokerTimeToUtc(value), parts);
   return parts.hour;
}}

datetime ConvertBrokerTimeToUtc(datetime value)
{{
   return value - BrokerUtcOffsetSeconds(value);
}}

int BrokerUtcOffsetSeconds(datetime value)
{{
   if(InpBrokerTimezone == "Europe/Prague")
      return PragueUtcOffsetSeconds(value);
   return 0;
}}

int PragueUtcOffsetSeconds(datetime server_time)
{{
   MqlDateTime parts;
   TimeToStruct(server_time, parts);
   datetime dst_start = MakeDateTime(parts.year, 3, LastSundayOfMonth(parts.year, 3), 2, 0, 0);
   datetime dst_end = MakeDateTime(parts.year, 10, LastSundayOfMonth(parts.year, 10), 3, 0, 0);
   if(server_time >= dst_start && server_time < dst_end)
      return 2 * 60 * 60;
   return 1 * 60 * 60;
}}

datetime MakeDateTime(int year, int month, int day, int hour, int minute, int second)
{{
   MqlDateTime parts;
   parts.year = year;
   parts.mon = month;
   parts.day = day;
   parts.hour = hour;
   parts.min = minute;
   parts.sec = second;
   parts.day_of_week = 0;
   parts.day_of_year = 0;
   return StructToTime(parts);
}}

int LastSundayOfMonth(int year, int month)
{{
   int last_day = DaysInMonth(year, month);
   datetime value = MakeDateTime(year, month, last_day, 0, 0, 0);
   MqlDateTime parts;
   TimeToStruct(value, parts);
   return last_day - parts.day_of_week;
}}

int DaysInMonth(int year, int month)
{{
   if(month == 2)
   {{
      bool leap = ((year % 4) == 0 && (year % 100) != 0) || ((year % 400) == 0);
      return leap ? 29 : 28;
   }}
   if(month == 4 || month == 6 || month == 9 || month == 11)
      return 30;
   return 31;
}}

bool EnsureAuditDirectory()
{{
   return EnsureCommonFileDirectory(InpAuditRelativePath);
}}

bool EnsureBrokerHistoryDirectory()
{{
   return EnsureCommonFileDirectory(InpBrokerHistoryRelativePath);
}}

bool EnsureCommonFileDirectory(string relative_path)
{{
   string parts[];
   int count = StringSplit(relative_path, '\\\\', parts);
   if(count <= 1)
      return true;
   string current = "";
   for(int index = 0; index < count - 1; index++)
   {{
      if(parts[index] == "")
         continue;
      if(current == "")
         current = parts[index];
      else
         current = current + "\\\\" + parts[index];
      FolderCreate(current, FILE_COMMON);
   }}
   return true;
}}

bool AuditFileExists()
{{
   int handle = FileOpen(InpAuditRelativePath, FILE_READ | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
      return false;
   FileClose(handle);
   return true;
}}

string FormatUtc(datetime value)
{{
   return TimeToString(ConvertBrokerTimeToUtc(value), TIME_DATE | TIME_SECONDS) + "Z";
}}

string MapExitReason(int deal_reason)
{{
   if(deal_reason == DEAL_REASON_SL)
      return "stop_loss";
   if(deal_reason == DEAL_REASON_TP)
      return "take_profit";
   if(deal_reason == DEAL_REASON_SO)
      return "stop_out";
   if(deal_reason == DEAL_REASON_EXPERT)
      return "expert";
   if(deal_reason == DEAL_REASON_CLIENT || deal_reason == DEAL_REASON_MOBILE || deal_reason == DEAL_REASON_WEB)
      return "manual";
   return "unknown";
}}

bool ExitBarCollision(string side, double stop_price, double take_profit_price, datetime exit_time)
{{
   if(stop_price <= 0.0 || take_profit_price <= 0.0)
      return false;
   int shift = iBarShift(_Symbol, PERIOD_M1, exit_time, false);
   if(shift < 0)
      return false;
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   if(CopyRates(_Symbol, PERIOD_M1, shift, 1, rates) <= 0)
      return false;
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(point <= 0.0)
      point = _Point;
   double spread_points = (double)MathMax((long)rates[0].spread, 0);
   double spread_price = spread_points * point;
   double ask_high = rates[0].high + spread_price;
   double ask_low = rates[0].low + spread_price;
   if(side == "long")
      return rates[0].low <= stop_price && rates[0].high >= take_profit_price;
   if(side == "short")
      return ask_high >= stop_price && ask_low <= take_profit_price;
   return false;
}}

struct ExportMinuteBar
{{
   datetime minute;
   double bid_o;
   double bid_h;
   double bid_l;
   double bid_c;
   double ask_o;
   double ask_h;
   double ask_l;
   double ask_c;
   long tick_count;
}};

void InitExportMinuteBar(ExportMinuteBar &bar, datetime minute, double bid, double ask)
{{
   bar.minute = minute;
   bar.bid_o = bid;
   bar.bid_h = bid;
   bar.bid_l = bid;
   bar.bid_c = bid;
   bar.ask_o = ask;
   bar.ask_h = ask;
   bar.ask_l = ask;
   bar.ask_c = ask;
   bar.tick_count = 1;
}}

void AccumulateExportMinuteBar(ExportMinuteBar &bar, double bid, double ask)
{{
   if(bid > bar.bid_h)
      bar.bid_h = bid;
   if(bid < bar.bid_l)
      bar.bid_l = bid;
   if(ask > bar.ask_h)
      bar.ask_h = ask;
   if(ask < bar.ask_l)
      bar.ask_l = ask;
   bar.bid_c = bid;
   bar.ask_c = ask;
   bar.tick_count++;
}}

int BuildTickMinuteBars(datetime start_time, datetime end_time, int max_bars, ExportMinuteBar &bars[])
{{
   if(max_bars <= 0)
      return 0;
   ArrayResize(bars, max_bars);
   int bar_count = 0;
   double last_bid = 0.0;
   double last_ask = 0.0;
   datetime effective_end = end_time + 60;
   for(datetime chunk_start = start_time; chunk_start <= effective_end; chunk_start += 86400)
   {{
      datetime chunk_end = chunk_start + 86400;
      if(chunk_end > effective_end)
         chunk_end = effective_end;
      MqlTick ticks[];
      long from_msc = (long)chunk_start * 1000;
      long to_msc = ((long)chunk_end * 1000) - 1;
      int tick_count = CopyTicksRange(_Symbol, ticks, COPY_TICKS_ALL, from_msc, to_msc);
      if(tick_count <= 0)
         continue;
      ArraySetAsSeries(ticks, false);
      for(int index = 0; index < tick_count; index++)
      {{
         double bid = ticks[index].bid > 0.0 ? ticks[index].bid : last_bid;
         double ask = ticks[index].ask > 0.0 ? ticks[index].ask : last_ask;
         if(bid <= 0.0 || ask <= 0.0)
         {{
            if(ticks[index].bid > 0.0)
               last_bid = ticks[index].bid;
            if(ticks[index].ask > 0.0)
               last_ask = ticks[index].ask;
            continue;
         }}
         last_bid = bid;
         last_ask = ask;
         datetime minute = ticks[index].time - (ticks[index].time % 60);
         if(bar_count == 0 || bars[bar_count - 1].minute != minute)
         {{
            if(bar_count >= max_bars)
               break;
            InitExportMinuteBar(bars[bar_count], minute, bid, ask);
            bar_count++;
         }}
         else
         {{
            AccumulateExportMinuteBar(bars[bar_count - 1], bid, ask);
         }}
      }}
      if(bar_count >= max_bars)
         break;
   }}
   ArrayResize(bars, bar_count);
   return bar_count;
}}

bool EnsureDiagnosticTicksDirectory()
{{
   if(InpDiagnosticTicksRelativePath == "")
      return false;
   return EnsureCommonFileDirectory(InpDiagnosticTicksRelativePath);
}}

void ExportTicksForWindow(
   int handle,
   string window_id,
   datetime start_time,
   datetime end_time,
   string expected_exit_utc,
   string actual_exit_utc,
   string likely_cause
)
{{
   MqlTick ticks[];
   long from_msc = (long)start_time * 1000;
   long to_msc = ((long)(end_time + 1)) * 1000 - 1;
   int tick_count = CopyTicksRange(_Symbol, ticks, COPY_TICKS_ALL, from_msc, to_msc);
   if(tick_count <= 0)
      return;
   ArraySetAsSeries(ticks, false);
   for(int index = 0; index < tick_count; index++)
   {{
      FileWrite(
         handle,
         window_id,
         FormatUtc(ticks[index].time),
         DoubleToString(ticks[index].bid, _Digits),
         DoubleToString(ticks[index].ask, _Digits),
         DoubleToString(ticks[index].last, _Digits),
         (string)ticks[index].volume,
         (string)ticks[index].flags,
         expected_exit_utc,
         actual_exit_utc,
         likely_cause
      );
   }}
}}

void ExportDiagnosticTicks()
{{
   if(InpDiagnosticWindowsRelativePath == "" || InpDiagnosticTicksRelativePath == "")
      return;
   int windows_handle = FileOpen(InpDiagnosticWindowsRelativePath, FILE_READ | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(windows_handle == INVALID_HANDLE)
      return;
   if(!EnsureDiagnosticTicksDirectory())
   {{
      FileClose(windows_handle);
      return;
   }}
   int ticks_handle = FileOpen(InpDiagnosticTicksRelativePath, FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(ticks_handle == INVALID_HANDLE)
   {{
      FileClose(windows_handle);
      return;
   }}
   FileWrite(
      ticks_handle,
      "window_id",
      "timestamp_utc",
      "bid",
      "ask",
      "last",
      "volume",
      "flags",
      "expected_exit_utc",
      "actual_exit_utc",
      "likely_cause"
   );
   while(!FileIsEnding(windows_handle))
   {{
      string window_id = FileReadString(windows_handle);
      string start_broker = FileReadString(windows_handle);
      string end_broker = FileReadString(windows_handle);
      string expected_exit_utc = FileReadString(windows_handle);
      string actual_exit_utc = FileReadString(windows_handle);
      string likely_cause = FileReadString(windows_handle);
      if(window_id == "" || window_id == "window_id")
         continue;
      datetime start_time = StringToTime(start_broker);
      datetime end_time = StringToTime(end_broker);
      if(start_time <= 0 || end_time <= 0 || end_time < start_time)
         continue;
      ExportTicksForWindow(
         ticks_handle,
         window_id,
         start_time,
         end_time,
         expected_exit_utc,
         actual_exit_utc,
         likely_cause
      );
   }}
   FileClose(windows_handle);
   FileClose(ticks_handle);
}}

bool EnsureRuntimeSummaryDirectory()
{{
   if(InpRuntimeSummaryRelativePath == "")
      return false;
   return EnsureCommonFileDirectory(InpRuntimeSummaryRelativePath);
}}

bool EnsureSignalTraceDirectory()
{{
   if(InpSignalTraceRelativePath == "")
      return false;
   return EnsureCommonFileDirectory(InpSignalTraceRelativePath);
}}

bool SignalTraceFileExists()
{{
   if(InpSignalTraceRelativePath == "")
      return false;
   int handle = FileOpen(InpSignalTraceRelativePath, FILE_READ | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
      return false;
   FileClose(handle);
   return true;
}}

void WriteSignalTraceRow(datetime bar_time, int signal, double spread_pips)
{{
   if(InpSignalTraceRelativePath == "")
      return;
   if(!EnsureSignalTraceDirectory())
      return;
   bool existing = SignalTraceFileExists();
   int handle = FileOpen(InpSignalTraceRelativePath, FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
      return;
   FileSeek(handle, 0, SEEK_END);
   if(!existing || FileTell(handle) == 0)
   {{
      FileWrite(handle, "timestamp_utc", "candidate_id", "run_id", "signal", "spread_pips", "bars_processed");
   }}
   FileWrite(
      handle,
      FormatUtc(bar_time),
      InpCandidateId,
      InpPacketRunId,
      (string)signal,
      DoubleToString(spread_pips, 6),
      (string)g_bars_processed
   );
   FileClose(handle);
}}

string JsonEscape(string value)
{{
   StringReplace(value, "\\\\", "\\\\\\\\");
   StringReplace(value, "\\\"", "\\\\\\\"");
   return value;
}}

string JsonPairString(string key, string value)
{{
   return "\\\"" + key + "\\\":\\\"" + JsonEscape(value) + "\\\"";
}}

string JsonPairLong(string key, long value)
{{
   return "\\\"" + key + "\\\":" + (string)value;
}}

void ExportRuntimeSummary(int reason)
{{
   if(InpRuntimeSummaryRelativePath == "")
      return;
   if(!EnsureRuntimeSummaryDirectory())
      return;
   int handle = FileOpen(InpRuntimeSummaryRelativePath, FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return;
   string json = "{{";
   json += JsonPairString("candidate_id", InpCandidateId) + ",";
   json += JsonPairString("run_id", InpPacketRunId) + ",";
   json += JsonPairString("symbol", _Symbol) + ",";
   json += JsonPairLong("deinit_reason", reason) + ",";
   json += JsonPairLong("bars_processed", g_bars_processed) + ",";
   json += JsonPairLong("allowed_hour_bars", g_allowed_hour_bars) + ",";
   json += JsonPairLong("spread_blocked_bars", g_spread_blocked_bars) + ",";
   json += JsonPairLong("filter_blocked_bars", g_filter_blocked_bars) + ",";
   json += JsonPairLong("no_signal_bars", g_no_signal_bars) + ",";
   json += JsonPairLong("long_signals", g_long_signals) + ",";
   json += JsonPairLong("short_signals", g_short_signals) + ",";
   json += JsonPairLong("order_attempts", g_order_attempts) + ",";
   json += JsonPairLong("order_successes", g_order_successes) + ",";
   json += JsonPairLong("order_failures", g_order_failures) + ",";
   json += JsonPairLong("open_position_recoveries", g_open_position_recoveries) + ",";
   json += JsonPairLong("audit_rows_written", g_audit_rows_written) + ",";
   json += JsonPairLong("audit_write_failures", g_audit_write_failures) + ",";
   json += JsonPairLong("symbol_tick_failures", g_symbol_tick_failures) + ",";
   json += JsonPairLong("copyrates_failures", g_copyrates_failures) + ",";
   json += JsonPairLong("trailing_stop_adjustments", g_trailing_stop_adjustments) + ",";
   json += "\\\"last_order_retcode\\\":" + (string)g_last_order_retcode;
   json += "}}";
   FileWriteString(handle, json);
   FileClose(handle);
}}

void ExportBrokerHistory()
{{
   if(!EnsureBrokerHistoryDirectory())
      return;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int total_bars = Bars(_Symbol, PERIOD_M1);
   if(total_bars <= 0)
      return;

   int bars_copied = CopyRates(_Symbol, PERIOD_M1, 0, total_bars, rates);
   if(bars_copied <= 0)
      return;

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(point <= 0.0)
      point = _Point;
   double pip_size = {pip_size};
   ExportMinuteBar tick_bars[];
   int tick_bar_count = BuildTickMinuteBars(rates[bars_copied - 1].time, rates[0].time, bars_copied, tick_bars);
   int tick_index = 0;

   int handle = FileOpen(InpBrokerHistoryRelativePath, FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
      return;

   FileWrite(
      handle,
      "timestamp_utc",
      "bid_o",
      "bid_h",
      "bid_l",
      "bid_c",
      "ask_o",
      "ask_h",
      "ask_l",
      "ask_c",
      "mid_o",
      "mid_h",
      "mid_l",
      "mid_c",
      "volume",
      "spread_pips"
   );

   for(int index = bars_copied - 1; index >= 0; index--)
   {{
      datetime minute = rates[index].time;
      while(tick_index < tick_bar_count && tick_bars[tick_index].minute < minute)
         tick_index++;
      bool use_tick_bar = tick_index < tick_bar_count && tick_bars[tick_index].minute == minute;
      double bid_o = rates[index].open;
      double bid_h = rates[index].high;
      double bid_l = rates[index].low;
      double bid_c = rates[index].close;
      double ask_o = 0.0;
      double ask_h = 0.0;
      double ask_l = 0.0;
      double ask_c = 0.0;
      double mid_o = 0.0;
      double mid_h = 0.0;
      double mid_l = 0.0;
      double mid_c = 0.0;
      double spread_pips = 0.0;
      long volume = (long)rates[index].tick_volume;
      if(use_tick_bar)
      {{
         bid_o = tick_bars[tick_index].bid_o;
         bid_h = tick_bars[tick_index].bid_h;
         bid_l = tick_bars[tick_index].bid_l;
         bid_c = tick_bars[tick_index].bid_c;
         ask_o = tick_bars[tick_index].ask_o;
         ask_h = tick_bars[tick_index].ask_h;
         ask_l = tick_bars[tick_index].ask_l;
         ask_c = tick_bars[tick_index].ask_c;
         volume = tick_bars[tick_index].tick_count;
         tick_index++;
      }}
      else
      {{
         double spread_points = (double)MathMax((long)rates[index].spread, 0);
         double spread_price = spread_points * point;
         ask_o = bid_o + spread_price;
         ask_h = bid_h + spread_price;
         ask_l = bid_l + spread_price;
         ask_c = bid_c + spread_price;
      }}
      mid_o = (bid_o + ask_o) / 2.0;
      mid_h = (bid_h + ask_h) / 2.0;
      mid_l = (bid_l + ask_l) / 2.0;
      mid_c = (bid_c + ask_c) / 2.0;
      spread_pips = pip_size <= 0.0 ? 0.0 : (ask_o - bid_o) / pip_size;

      FileWrite(
         handle,
         FormatUtc(minute),
         DoubleToString(bid_o, _Digits),
         DoubleToString(bid_h, _Digits),
         DoubleToString(bid_l, _Digits),
         DoubleToString(bid_c, _Digits),
         DoubleToString(ask_o, _Digits),
         DoubleToString(ask_h, _Digits),
         DoubleToString(ask_l, _Digits),
         DoubleToString(ask_c, _Digits),
         DoubleToString(mid_o, _Digits),
         DoubleToString(mid_h, _Digits),
         DoubleToString(mid_l, _Digits),
         DoubleToString(mid_c, _Digits),
         (string)volume,
         DoubleToString(spread_pips, 6)
      );
   }}

   FileClose(handle);
}}

void WriteAuditRow(
   datetime entry_time,
   datetime exit_time,
   string side,
   double entry_price,
   double exit_price,
   double pnl_pips,
   double pnl_dollars,
   string exit_reason,
   double stop_loss_price,
   double take_profit_price,
   bool same_bar_collision,
   ulong ticket
)
{{
   EnsureAuditDirectory();
   bool existing = AuditFileExists();
   int flags = FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI;
   int handle = FileOpen(InpAuditRelativePath, flags, ',');
   if(handle == INVALID_HANDLE)
   {{
      g_audit_write_failures++;
      return;
   }}
   FileSeek(handle, 0, SEEK_END);
   if(!existing || FileTell(handle) == 0)
   {{
      FileWrite(
         handle,
         "timestamp_utc",
         "exit_timestamp_utc",
         "side",
         "entry_price",
         "exit_price",
         "pnl_pips",
         "pnl_dollars",
         "candidate_id",
         "run_id",
         "magic_number",
         "ticket",
         "exit_reason",
         "stop_loss_price",
         "take_profit_price",
         "same_bar_collision"
      );
   }}
   FileWrite(
      handle,
      FormatUtc(entry_time),
      FormatUtc(exit_time),
      side,
      DoubleToString(entry_price, _Digits),
      DoubleToString(exit_price, _Digits),
      DoubleToString(pnl_pips, 5),
      DoubleToString(pnl_dollars, 2),
      InpCandidateId,
      InpPacketRunId,
      (string)InpMagicNumber,
      (string)ticket,
      exit_reason,
      DoubleToString(stop_loss_price, _Digits),
      DoubleToString(take_profit_price, _Digits),
      same_bar_collision ? "true" : "false"
   );
   g_audit_rows_written++;
   FileClose(handle);
}}
"""


def _float_or_default(value: str | None, default: float) -> float:
    if value is None:
        return float(default)
    try:
        return float(value)
    except ValueError:
        return float(default)


def _bool_literal(value: str | None) -> str:
    truthy = {"1", "true", "yes", "on", "required"}
    return "true" if (value or "").strip().lower() in truthy else "false"


def _string_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _magic_number(candidate_id: str) -> int:
    digits = "".join(character for character in candidate_id if character.isdigit())
    if not digits:
        return 240321
    return 200000 + int(digits[-5:])


def _pip_size_expression(instrument: str) -> str:
    if instrument.endswith("_JPY"):
        return "(_Digits == 3 ? _Point * 10.0 : _Point)"
    return "((_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point)"
