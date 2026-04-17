#property strict
#include <Trade/Trade.mqh>

CTrade trade;
datetime g_last_bar_time = 0;
bool g_allowed_hours[24];
bool g_has_open_trade = false;
datetime g_entry_time = 0;
double g_entry_price = 0.0;
string g_entry_side = "";
ulong g_entry_ticket = 0;

input string InpCandidateId = "AF-CAND-0238";
input string InpPacketRunId = "mt5run-20260324T080304Z";
input ulong InpMagicNumber = 200238;
input double InpFixedLots = 5.00;
input double InpSignalThreshold = 0.76000;
input double InpStopLossPips = 7.00000;
input double InpTakeProfitPips = 14.50000;
input double InpMaxSpreadPips = 2.40000;
input double InpMinVolatility20 = 0.00005000;
input double InpBreakoutZscoreFloor = 0.00000;
input double InpMaxRangeWidth10Pips = 0.00000;
input double InpCompressionRangePositionFloor = 0.65000;
input double InpExtensionZscoreFloor = 0.00000;
input double InpReclaimRangePositionFloor = 0.12000;
input double InpReclaimRangePositionCeiling = 0.42000;
input double InpReclaimMomentumCeiling = 4.00000;
input double InpRet5Floor = 0.00000000;
input double InpTrendRet5Min = 0.00007000;
input double InpPullbackZscoreLimit = 0.45000;
input double InpRetestZscoreLimit = 0.35000;
input double InpRetestRangePositionFloor = 0.52000;
input double InpContinuationZscoreFloor = 0.18000;
input double InpContinuationZscoreCeiling = 0.95000;
input double InpContinuationRangePositionFloor = 0.66000;
input double InpFadeRet5Floor = 0.00000000;
input double InpFadeMomentumCeiling = 3.20000;
input bool InpRequireRet5Alignment = false;
input bool InpRequireMeanLocationAlignment = true;
input bool InpRequireRet1Confirmation = false;
input bool InpRequireReclaimRet1 = false;
input bool InpRequireRecoveryRet1 = false;
input bool InpRequireReversalRet1 = false;
input bool InpRequireReversalMomentum = false;
input int InpFillDelayMs = 0;
input int InpHoldingBars = 54;
input string InpAllowedHoursCsv = "14,15,16";
input string InpExcludedContextBucket = "mean_reversion_context";
input string InpRequiredVolatilityBucket = "high";
input string InpEntryStyle = "session_momentum_band";
input string InpAuditRelativePath = "AgenticForex\\Audit\\AF-CAND-0238__mt5run-20260324T080304Z__audit.csv";
input string InpBrokerHistoryRelativePath = "AgenticForex\\Audit\\AF-CAND-0238__broker_history.csv";
input string InpBrokerTimezone = "Europe/Prague";

int OnInit()
{
   ResetAllowedHours();
   ParseAllowedHours(InpAllowedHoursCsv);
   trade.SetExpertMagicNumber(InpMagicNumber);
   CaptureOpenPositionState();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   ExportBrokerHistory();
}

void OnTick()
{
   datetime current_bar = iTime(_Symbol, PERIOD_M1, 0);
   if(current_bar == 0 || current_bar == g_last_bar_time)
      return;
   g_last_bar_time = current_bar;

   if(HasOpenPosition())
   {
      CaptureOpenPositionState();
      if(ShouldTimeExit(current_bar))
         trade.PositionClose(_Symbol);
      return;
   }

   ResetOpenTradeState();

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;

   double spread_pips = (tick.ask - tick.bid) / ((_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point);
   if(spread_pips > InpMaxSpreadPips)
      return;

   int trade_hour = HourUtc(current_bar);
   if(!g_allowed_hours[trade_hour])
      return;

   int signal = GenerateSignal();
   if(signal == 0)
      return;

   if(InpFillDelayMs > 0)
      Sleep(InpFillDelayMs);

   if(!SymbolInfoTick(_Symbol, tick))
      return;

   double pip_size = ((_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point);
   double lots = NormalizeDouble(InpFixedLots, 2);
   bool placed = false;
   if(signal > 0)
   {
      double price = tick.ask;
      double sl = price - (InpStopLossPips * pip_size);
      double tp = price + (InpTakeProfitPips * pip_size);
      placed = trade.Buy(lots, _Symbol, price, sl, tp, InpCandidateId);
   }
   else
   {
      double price = tick.bid;
      double sl = price + (InpStopLossPips * pip_size);
      double tp = price - (InpTakeProfitPips * pip_size);
      placed = trade.Sell(lots, _Symbol, price, sl, tp, InpCandidateId);
   }

   if(placed)
      CaptureOpenPositionState();
}

void OnTradeTransaction(
   const MqlTradeTransaction &trans,
   const MqlTradeRequest &request,
   const MqlTradeResult &result
)
{
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
   {
      g_has_open_trade = true;
      g_entry_ticket = trans.deal;
      g_entry_time = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
      g_entry_price = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
      long deal_type = HistoryDealGetInteger(trans.deal, DEAL_TYPE);
      g_entry_side = (deal_type == DEAL_TYPE_BUY) ? "long" : "short";
      return;
   }

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
   double pip_size = ((_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point);
   if(g_entry_side == "long")
      pnl_pips = (exit_price - g_entry_price) / pip_size;
   else if(g_entry_side == "short")
      pnl_pips = (g_entry_price - exit_price) / pip_size;

   WriteAuditRow(
      g_entry_time,
      exit_time,
      g_entry_side,
      g_entry_price,
      exit_price,
      pnl_pips,
      profit,
      trans.deal
   );
   ResetOpenTradeState();
}

bool HasOpenPosition()
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol)
         return true;
   }
   return false;
}

bool ShouldTimeExit(datetime current_bar)
{
   if(!g_has_open_trade || InpHoldingBars <= 0)
      return false;
   int bars_since_entry = iBarShift(_Symbol, PERIOD_M1, g_entry_time, true);
   int current_shift = iBarShift(_Symbol, PERIOD_M1, current_bar, true);
   if(bars_since_entry < 0 || current_shift < 0)
      return false;
   return (bars_since_entry - current_shift) >= InpHoldingBars;
}

void CaptureOpenPositionState()
{
   if(!PositionSelect(_Symbol))
   {
      ResetOpenTradeState();
      return;
   }
   g_has_open_trade = true;
   g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
   g_entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
   long position_type = PositionGetInteger(POSITION_TYPE);
   g_entry_side = (position_type == POSITION_TYPE_BUY) ? "long" : "short";
   g_entry_ticket = (ulong)PositionGetInteger(POSITION_TICKET);
}

void ResetOpenTradeState()
{
   g_has_open_trade = false;
   g_entry_time = 0;
   g_entry_price = 0.0;
   g_entry_side = "";
   g_entry_ticket = 0;
}

void ResetAllowedHours()
{
   for(int hour = 0; hour < 24; hour++)
      g_allowed_hours[hour] = false;
}

void ParseAllowedHours(string csv)
{
   string parts[];
   int count = StringSplit(csv, ',', parts);
   for(int i = 0; i < count; i++)
   {
      int hour = (int)StringToInteger(parts[i]);
      if(hour >= 0 && hour < 24)
         g_allowed_hours[hour] = true;
   }
}

int GenerateSignal()
{
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int bars_copied = CopyRates(_Symbol, PERIOD_M1, 0, 40, rates);
   if(bars_copied < 25)
      return 0;

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(point <= 0.0)
      point = ((_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point) / 10.0;

   double closes[];
   double highs[];
   double lows[];
   ArrayResize(closes, bars_copied);
   ArrayResize(highs, bars_copied);
   ArrayResize(lows, bars_copied);
   for(int i = 0; i < bars_copied; i++)
   {
      double mid_offset = ((double)MathMax((long)rates[i].spread, 0) * point) / 2.0;
      closes[i] = rates[i].close + mid_offset;
      highs[i] = rates[i].high + mid_offset;
      lows[i] = rates[i].low + mid_offset;
   }

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
   double range_width_10_pips = (range_high_10 - range_low_10) / ((_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point);
   double range_position_10 = 0.5;
   if(range_high_10 > range_low_10)
      range_position_10 = (c1 - range_low_10) / (range_high_10 - range_low_10);
   double momentum_12 = (c1 - c13) * 10000.0;
   double volatility_20 = ReturnStdDev(closes, 1, 20);
   string context_bucket = ContextBucket(zscore_10, momentum_12);

   if(!PassesCommonFilters(spread_pips_current(), volatility_20, context_bucket))
      return 0;

   if(InpEntryStyle == "session_breakout")
   {
      if(momentum_12 >= InpSignalThreshold)
      {
         if(InpRequireRet5Alignment && ret_5 <= 0.0)
            return 0;
         if(InpRet5Floor > 0.0 && ret_5 < InpRet5Floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpBreakoutZscoreFloor > 0.0 && zscore_10 < InpBreakoutZscoreFloor)
            return 0;
         return 1;
      }
      if(momentum_12 <= -InpSignalThreshold)
      {
         if(InpRequireRet5Alignment && ret_5 >= 0.0)
            return 0;
         if(InpRet5Floor > 0.0 && ret_5 > -InpRet5Floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpBreakoutZscoreFloor > 0.0 && zscore_10 > -InpBreakoutZscoreFloor)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "volatility_breakout")
   {
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.55;
      if(momentum_12 >= InpSignalThreshold)
      {
         if(InpRequireRet5Alignment && ret_5 <= 0.0)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(zscore_10 < breakout_floor)
            return 0;
         return 1;
      }
      if(momentum_12 <= -InpSignalThreshold)
      {
         if(InpRequireRet5Alignment && ret_5 >= 0.0)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(zscore_10 > -breakout_floor)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "volatility_expansion")
   {
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : MathMax(InpSignalThreshold * 0.85, 0.65);
      double minimum_ret_5 = InpRet5Floor > 0.0 ? InpRet5Floor : 0.00006;
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00003))
         return 0;
      if(momentum_12 >= InpSignalThreshold && zscore_10 >= breakout_floor)
      {
         if(ret_5 < minimum_ret_5)
            return 0;
         if(ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -InpSignalThreshold && zscore_10 <= -breakout_floor)
      {
         if(ret_5 > -minimum_ret_5)
            return 0;
         if(ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "volatility_retest_breakout" || InpEntryStyle == "overlap_event_retest_breakout")
   {
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.55;
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00008;
      double retest_limit = InpRetestZscoreLimit > 0.0 ? InpRetestZscoreLimit : 0.35;
      double retest_position_floor = InpRetestRangePositionFloor > 0.0 ? InpRetestRangePositionFloor : 0.55;
      double momentum_floor = MathMax(InpSignalThreshold * 0.65, 0.55);
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00004))
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {
         if(!(zscore_10 >= -retest_limit && zscore_10 <= breakout_floor))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {
         if(!(zscore_10 >= -breakout_floor && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "overlap_persistence_band")
   {
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00008;
      double continuation_floor = InpContinuationZscoreFloor > 0.0 ? InpContinuationZscoreFloor : 0.08;
      double continuation_ceiling = InpContinuationZscoreCeiling > 0.0 ? InpContinuationZscoreCeiling : 0.72;
      double continuation_position_floor = InpContinuationRangePositionFloor > 0.0 ? InpContinuationRangePositionFloor : 0.60;
      double momentum_floor = MathMax(InpSignalThreshold * 0.70, 0.60);
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00005))
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {
         if(!(zscore_10 >= continuation_floor && zscore_10 <= continuation_ceiling))
            return 0;
         if(range_position_10 < continuation_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {
         if(!(zscore_10 >= -continuation_ceiling && zscore_10 <= -continuation_floor))
            return 0;
         if(range_position_10 > (1.0 - continuation_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "session_momentum_band")
   {
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00007;
      double continuation_floor = InpContinuationZscoreFloor > 0.0 ? InpContinuationZscoreFloor : 0.20;
      double continuation_ceiling = InpContinuationZscoreCeiling > 0.0 ? InpContinuationZscoreCeiling : 1.05;
      double continuation_position_floor = InpContinuationRangePositionFloor > 0.0 ? InpContinuationRangePositionFloor : 0.64;
      double momentum_floor = MathMax(InpSignalThreshold, 0.75);
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00004))
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {
         if(!(zscore_10 >= continuation_floor && zscore_10 <= continuation_ceiling))
            return 0;
         if(range_position_10 < continuation_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRet1Confirmation && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {
         if(!(zscore_10 >= -continuation_ceiling && zscore_10 <= -continuation_floor))
            return 0;
         if(range_position_10 > (1.0 - continuation_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRet1Confirmation && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "compression_breakout")
   {
      double compression_ceiling = InpMaxRangeWidth10Pips > 0.0 ? InpMaxRangeWidth10Pips : 9.0;
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.45;
      double range_position_floor = InpCompressionRangePositionFloor > 0.0 ? InpCompressionRangePositionFloor : 0.65;
      if(range_width_10_pips > compression_ceiling)
         return 0;
      if(momentum_12 >= InpSignalThreshold)
      {
         if(zscore_10 < breakout_floor)
            return 0;
         if(range_position_10 < range_position_floor)
            return 0;
         if(InpRequireRet1Confirmation && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -InpSignalThreshold)
      {
         if(zscore_10 > -breakout_floor)
            return 0;
         if(range_position_10 > (1.0 - range_position_floor))
            return 0;
         if(InpRequireRet1Confirmation && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "compression_retest_breakout")
   {
      double compression_ceiling = InpMaxRangeWidth10Pips > 0.0 ? InpMaxRangeWidth10Pips : 8.5;
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.40;
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00008;
      double retest_limit = InpRetestZscoreLimit > 0.0 ? InpRetestZscoreLimit : 0.30;
      double retest_position_floor = InpRetestRangePositionFloor > 0.0 ? InpRetestRangePositionFloor : 0.56;
      double momentum_floor = MathMax(InpSignalThreshold * 0.7, 0.55);
      if(range_width_10_pips > compression_ceiling)
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {
         if(!(zscore_10 >= -retest_limit && zscore_10 <= breakout_floor))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {
         if(!(zscore_10 >= -breakout_floor && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "range_reclaim")
   {
      double extension_floor = InpExtensionZscoreFloor > 0.0 ? InpExtensionZscoreFloor : 1.05;
      double reclaim_floor = InpReclaimRangePositionFloor > 0.0 ? InpReclaimRangePositionFloor : 0.12;
      double reclaim_ceiling = InpReclaimRangePositionCeiling > 0.0 ? InpReclaimRangePositionCeiling : 0.42;
      double momentum_ceiling = InpReclaimMomentumCeiling > 0.0 ? InpReclaimMomentumCeiling : 4.0;
      if(zscore_10 <= -extension_floor)
      {
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         if(!(range_position_10 >= reclaim_floor && range_position_10 <= reclaim_ceiling))
            return 0;
         if(InpRequireReclaimRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(zscore_10 >= extension_floor)
      {
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         if(!(range_position_10 >= (1.0 - reclaim_ceiling) && range_position_10 <= (1.0 - reclaim_floor)))
            return 0;
         if(InpRequireReclaimRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "pullback_continuation")
   {
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00008;
      double pullback_limit = InpPullbackZscoreLimit > 0.0 ? InpPullbackZscoreLimit : 0.45;
      if(momentum_12 >= InpSignalThreshold && ret_5 >= trend_floor)
      {
         if(!(zscore_10 >= -pullback_limit && zscore_10 <= 0.15))
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -InpSignalThreshold && ret_5 <= -trend_floor)
      {
         if(!(zscore_10 >= -0.15 && zscore_10 <= pullback_limit))
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "overlap_persistence_retest")
   {
      double breakout_floor = InpBreakoutZscoreFloor > 0.0 ? InpBreakoutZscoreFloor : 0.57;
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00009;
      double retest_limit = InpRetestZscoreLimit > 0.0 ? InpRetestZscoreLimit : 0.32;
      double retest_position_floor = InpRetestRangePositionFloor > 0.0 ? InpRetestRangePositionFloor : 0.58;
      double momentum_floor = MathMax(InpSignalThreshold * 0.70, 0.60);
      if(volatility_20 < MathMax(InpMinVolatility20, 0.00006))
         return 0;
      if(momentum_12 >= momentum_floor && ret_5 >= trend_floor)
      {
         if(!(zscore_10 >= -retest_limit && zscore_10 <= breakout_floor))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {
         if(!(zscore_10 >= -breakout_floor && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "high_vol_overlap_persistence_retest")
   {
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
      {
         if(!(zscore_10 >= -retest_limit && zscore_10 <= breakout_floor))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(InpRequireMeanLocationAlignment && c1 <= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -momentum_floor && ret_5 <= -trend_floor)
      {
         if(!(zscore_10 >= -breakout_floor && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(InpRequireMeanLocationAlignment && c1 >= rolling_mean_10)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "trend_retest")
   {
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00012;
      double retest_limit = InpRetestZscoreLimit > 0.0 ? InpRetestZscoreLimit : 0.35;
      double retest_position_floor = InpRetestRangePositionFloor > 0.0 ? InpRetestRangePositionFloor : 0.52;
      if(momentum_12 >= InpSignalThreshold && ret_5 >= trend_floor)
      {
         if(!(zscore_10 >= -retest_limit && zscore_10 <= 0.25))
            return 0;
         if(range_position_10 < retest_position_floor)
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -InpSignalThreshold && ret_5 <= -trend_floor)
      {
         if(!(zscore_10 >= -0.25 && zscore_10 <= retest_limit))
            return 0;
         if(range_position_10 > (1.0 - retest_position_floor))
            return 0;
         if(InpRequireRecoveryRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "trend_pullback_retest")
   {
      double trend_floor = InpTrendRet5Min > 0.0 ? InpTrendRet5Min : 0.00005;
      double pullback_limit = InpPullbackZscoreLimit > 0.0 ? InpPullbackZscoreLimit : 0.55;
      if(ret_5 >= trend_floor && ret_1 > 0.0 && zscore_10 >= -pullback_limit && zscore_10 <= 0.35)
      {
         if(momentum_12 < InpSignalThreshold * 0.5)
            return 0;
         return 1;
      }
      if(ret_5 <= -trend_floor && ret_1 < 0.0 && zscore_10 <= pullback_limit && zscore_10 >= -0.35)
      {
         if(momentum_12 > -InpSignalThreshold * 0.5)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "failed_break_fade")
   {
      double fade_floor = InpFadeRet5Floor > 0.0 ? InpFadeRet5Floor : 0.00005;
      double momentum_ceiling = InpFadeMomentumCeiling > 0.0 ? InpFadeMomentumCeiling : 3.2;
      if(zscore_10 <= -MathAbs(InpSignalThreshold))
      {
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         if(ret_5 >= -fade_floor)
            return 0;
         if(InpRequireReversalRet1 && ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(zscore_10 >= MathAbs(InpSignalThreshold))
      {
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         if(ret_5 <= fade_floor)
            return 0;
         if(InpRequireReversalRet1 && ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "session_extreme_reversion")
   {
      double extreme_floor = MathMax(MathAbs(InpSignalThreshold), 0.65);
      double fade_floor = InpFadeRet5Floor > 0.0 ? InpFadeRet5Floor : 0.00004;
      double momentum_ceiling = InpFadeMomentumCeiling > 0.0 ? InpFadeMomentumCeiling : 4.0;
      if(zscore_10 <= -extreme_floor)
      {
         if(ret_5 > -fade_floor)
            return 0;
         if(ret_1 <= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return 1;
      }
      if(zscore_10 >= extreme_floor)
      {
         if(ret_5 < fade_floor)
            return 0;
         if(ret_1 >= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "compression_reversion")
   {
      double compression_ceiling = 8.0;
      double extreme_floor = MathMax(MathAbs(InpSignalThreshold), 0.9);
      double reclaim_floor = 0.18;
      double reclaim_ceiling = 0.45;
      double momentum_ceiling = 3.6;
      if(range_width_10_pips > compression_ceiling)
         return 0;
      if(zscore_10 <= -extreme_floor)
      {
         if(!(range_position_10 >= reclaim_floor && range_position_10 <= reclaim_ceiling))
            return 0;
         if(ret_1 <= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return 1;
      }
      if(zscore_10 >= extreme_floor)
      {
         if(!(range_position_10 >= (1.0 - reclaim_ceiling) && range_position_10 <= (1.0 - reclaim_floor)))
            return 0;
         if(ret_1 >= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "drift_reclaim")
   {
      double extension_floor = MathMax(MathAbs(InpSignalThreshold) * 0.95, 0.85);
      double drift_floor = 0.00005;
      double reclaim_floor = 0.30;
      double reclaim_ceiling = 0.58;
      double momentum_ceiling = 5.0;
      if(zscore_10 <= -extension_floor)
      {
         if(ret_5 > -drift_floor)
            return 0;
         if(!(range_position_10 >= reclaim_floor && range_position_10 <= reclaim_ceiling))
            return 0;
         if(ret_1 <= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return 1;
      }
      if(zscore_10 >= extension_floor)
      {
         if(ret_5 < drift_floor)
            return 0;
         if(!(range_position_10 >= (1.0 - reclaim_ceiling) && range_position_10 <= (1.0 - reclaim_floor)))
            return 0;
         if(ret_1 >= 0.0)
            return 0;
         if(MathAbs(momentum_12) > momentum_ceiling)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "balance_area_breakout")
   {
      double compression_ceiling = 8.5;
      double breakout_floor = MathMax(InpSignalThreshold * 0.7, 0.45);
      double range_position_floor = 0.60;
      double momentum_floor = InpSignalThreshold * 0.8;
      if(range_width_10_pips > compression_ceiling)
         return 0;
      if(momentum_12 >= momentum_floor)
      {
         if(zscore_10 < breakout_floor)
            return 0;
         if(range_position_10 < range_position_floor)
            return 0;
         if(ret_5 <= 0.0 || ret_1 <= 0.0)
            return 0;
         return 1;
      }
      if(momentum_12 <= -momentum_floor)
      {
         if(zscore_10 > -breakout_floor)
            return 0;
         if(range_position_10 > (1.0 - range_position_floor))
            return 0;
         if(ret_5 >= 0.0 || ret_1 >= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   if(InpEntryStyle == "mean_reversion_pullback")
   {
      if(zscore_10 <= -MathAbs(InpSignalThreshold))
      {
         if(InpRequireReversalRet1 && ret_1 <= 0.0)
            return 0;
         if(InpRequireReversalMomentum && momentum_12 >= 0.0)
            return 0;
         return 1;
      }
      if(zscore_10 >= MathAbs(InpSignalThreshold))
      {
         if(InpRequireReversalRet1 && ret_1 >= 0.0)
            return 0;
         if(InpRequireReversalMomentum && momentum_12 <= 0.0)
            return 0;
         return -1;
      }
      return 0;
   }

   return 0;
}

bool PassesCommonFilters(double spread_pips, double volatility_20, string context_bucket)
{
   if(spread_pips > InpMaxSpreadPips)
      return false;
   if(InpMinVolatility20 > 0.0 && volatility_20 < InpMinVolatility20)
      return false;
   if(InpRequiredVolatilityBucket != "" && VolatilityBucket(volatility_20) != InpRequiredVolatilityBucket)
      return false;
   if(InpExcludedContextBucket != "" && context_bucket == InpExcludedContextBucket)
      return false;
   return true;
}

double spread_pips_current()
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return 0.0;
   return (tick.ask - tick.bid) / ((_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point);
}

double Mean(const double &values[], int start, int count)
{
   double total = 0.0;
   for(int i = start; i < start + count; i++)
      total += values[i];
   return total / count;
}

double StdDev(const double &values[], int start, int count)
{
   double mean = Mean(values, start, count);
   double total = 0.0;
   for(int i = start; i < start + count; i++)
   {
      double diff = values[i] - mean;
      total += diff * diff;
   }
   return MathSqrt(total / count);
}

double MaxValue(const double &values[], int start, int count)
{
   double value = values[start];
   for(int i = start + 1; i < start + count; i++)
   {
      if(values[i] > value)
         value = values[i];
   }
   return value;
}

double MinValue(const double &values[], int start, int count)
{
   double value = values[start];
   for(int i = start + 1; i < start + count; i++)
   {
      if(values[i] < value)
         value = values[i];
   }
   return value;
}

double ReturnStdDev(const double &values[], int start, int count)
{
   double returns[];
   ArrayResize(returns, count);
   for(int i = 0; i < count; i++)
   {
      double previous = values[start + i + 1];
      double current = values[start + i];
      returns[i] = previous == 0.0 ? 0.0 : (current / previous) - 1.0;
   }
   return StdDev(returns, 0, count);
}

string ContextBucket(double zscore_10, double momentum_12)
{
   if(MathAbs(zscore_10) >= 1.2)
      return "mean_reversion_context";
   if(MathAbs(momentum_12) >= 0.8)
      return "trend_context";
   return "neutral_context";
}

string VolatilityBucket(double volatility_20)
{
   if(volatility_20 <= 0.00005)
      return "low";
   if(volatility_20 <= 0.00012)
      return "medium";
   return "high";
}

int HourUtc(datetime value)
{
   MqlDateTime parts;
   TimeToStruct(ConvertBrokerTimeToUtc(value), parts);
   return parts.hour;
}

datetime ConvertBrokerTimeToUtc(datetime value)
{
   return value - BrokerUtcOffsetSeconds(value);
}

int BrokerUtcOffsetSeconds(datetime value)
{
   if(InpBrokerTimezone == "Europe/Prague")
      return PragueUtcOffsetSeconds(value);
   return 0;
}

int PragueUtcOffsetSeconds(datetime server_time)
{
   MqlDateTime parts;
   TimeToStruct(server_time, parts);
   datetime dst_start = MakeDateTime(parts.year, 3, LastSundayOfMonth(parts.year, 3), 2, 0, 0);
   datetime dst_end = MakeDateTime(parts.year, 10, LastSundayOfMonth(parts.year, 10), 3, 0, 0);
   if(server_time >= dst_start && server_time < dst_end)
      return 2 * 60 * 60;
   return 1 * 60 * 60;
}

datetime MakeDateTime(int year, int month, int day, int hour, int minute, int second)
{
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
}

int LastSundayOfMonth(int year, int month)
{
   int last_day = DaysInMonth(year, month);
   datetime value = MakeDateTime(year, month, last_day, 0, 0, 0);
   MqlDateTime parts;
   TimeToStruct(value, parts);
   return last_day - parts.day_of_week;
}

int DaysInMonth(int year, int month)
{
   if(month == 2)
   {
      bool leap = ((year % 4) == 0 && (year % 100) != 0) || ((year % 400) == 0);
      return leap ? 29 : 28;
   }
   if(month == 4 || month == 6 || month == 9 || month == 11)
      return 30;
   return 31;
}

bool EnsureAuditDirectory()
{
   return EnsureCommonFileDirectory(InpAuditRelativePath);
}

bool EnsureBrokerHistoryDirectory()
{
   return EnsureCommonFileDirectory(InpBrokerHistoryRelativePath);
}

bool EnsureCommonFileDirectory(string relative_path)
{
   string parts[];
   int count = StringSplit(relative_path, '\\', parts);
   if(count <= 1)
      return true;
   string current = "";
   for(int index = 0; index < count - 1; index++)
   {
      if(parts[index] == "")
         continue;
      if(current == "")
         current = parts[index];
      else
         current = current + "\\" + parts[index];
      FolderCreate(current, FILE_COMMON);
   }
   return true;
}

bool AuditFileExists()
{
   int handle = FileOpen(InpAuditRelativePath, FILE_READ | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
      return false;
   FileClose(handle);
   return true;
}

string FormatUtc(datetime value)
{
   return TimeToString(ConvertBrokerTimeToUtc(value), TIME_DATE | TIME_SECONDS) + "Z";
}

void ExportBrokerHistory()
{
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
   double pip_size = ((_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point);

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
   {
      double spread_points = (double)MathMax((long)rates[index].spread, 0);
      double spread_price = spread_points * point;
      double ask_o = rates[index].open + spread_price;
      double ask_h = rates[index].high + spread_price;
      double ask_l = rates[index].low + spread_price;
      double ask_c = rates[index].close + spread_price;
      double mid_o = (rates[index].open + ask_o) / 2.0;
      double mid_h = (rates[index].high + ask_h) / 2.0;
      double mid_l = (rates[index].low + ask_l) / 2.0;
      double mid_c = (rates[index].close + ask_c) / 2.0;
      double spread_pips = pip_size <= 0.0 ? 0.0 : spread_price / pip_size;

      FileWrite(
         handle,
         FormatUtc(rates[index].time),
         DoubleToString(rates[index].open, _Digits),
         DoubleToString(rates[index].high, _Digits),
         DoubleToString(rates[index].low, _Digits),
         DoubleToString(rates[index].close, _Digits),
         DoubleToString(ask_o, _Digits),
         DoubleToString(ask_h, _Digits),
         DoubleToString(ask_l, _Digits),
         DoubleToString(ask_c, _Digits),
         DoubleToString(mid_o, _Digits),
         DoubleToString(mid_h, _Digits),
         DoubleToString(mid_l, _Digits),
         DoubleToString(mid_c, _Digits),
         (string)rates[index].tick_volume,
         DoubleToString(spread_pips, 6)
      );
   }

   FileClose(handle);
}

void WriteAuditRow(
   datetime entry_time,
   datetime exit_time,
   string side,
   double entry_price,
   double exit_price,
   double pnl_pips,
   double pnl_dollars,
   ulong ticket
)
{
   EnsureAuditDirectory();
   bool existing = AuditFileExists();
   int flags = FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI;
   int handle = FileOpen(InpAuditRelativePath, flags, ',');
   if(handle == INVALID_HANDLE)
      return;
   FileSeek(handle, 0, SEEK_END);
   if(!existing || FileTell(handle) == 0)
   {
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
         "ticket"
      );
   }
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
      (string)ticket
   );
   FileClose(handle);
}
