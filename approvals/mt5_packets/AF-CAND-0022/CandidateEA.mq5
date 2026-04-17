#property strict
#include <Trade/Trade.mqh>

CTrade trade;
datetime g_last_bar_time = 0;
bool g_allowed_hours[24];

input string InpCandidateId = "AF-CAND-0022";
input ulong InpMagicNumber = 200022;
input double InpFixedLots = 5.00;
input double InpSignalThreshold = 0.96000;
input double InpStopLossPips = 4.20000;
input double InpTakeProfitPips = 7.40000;
input double InpMaxSpreadPips = 1.80000;
input double InpMinVolatility20 = 0.00012000;
input double InpBreakoutZscoreFloor = 0.32000;
input double InpRet5Floor = 0.00005000;
input double InpTrendRet5Min = 0.00000000;
input double InpPullbackZscoreLimit = 0.45000;
input double InpFadeRet5Floor = 0.00000000;
input double InpFadeMomentumCeiling = 3.20000;
input bool InpRequireRet5Alignment = true;
input bool InpRequireMeanLocationAlignment = true;
input bool InpRequireRecoveryRet1 = false;
input bool InpRequireReversalRet1 = false;
input bool InpRequireReversalMomentum = false;
input int InpFillDelayMs = 250;
input string InpAllowedHoursCsv = "6,7,8,9,10,11,12";
input string InpExcludedContextBucket = "";
input string InpEntryStyle = "session_breakout";

int OnInit()
{
   ResetAllowedHours();
   ParseAllowedHours(InpAllowedHoursCsv);
   trade.SetExpertMagicNumber(InpMagicNumber);
   return INIT_SUCCEEDED;
}

void OnTick()
{
   datetime current_bar = iTime(_Symbol, PERIOD_M1, 0);
   if(current_bar == 0 || current_bar == g_last_bar_time)
      return;
   g_last_bar_time = current_bar;

   if(HasOpenPosition())
      return;

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;

   double spread_pips = (tick.ask - tick.bid) / ((_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point);
   if(spread_pips > InpMaxSpreadPips)
      return;

   int trade_hour = HourOf(current_bar);
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
   if(signal > 0)
   {
      double price = tick.ask;
      double sl = price - (InpStopLossPips * pip_size);
      double tp = price + (InpTakeProfitPips * pip_size);
      trade.Buy(lots, _Symbol, price, sl, tp, InpCandidateId);
      return;
   }

   double price = tick.bid;
   double sl = price + (InpStopLossPips * pip_size);
   double tp = price - (InpTakeProfitPips * pip_size);
   trade.Sell(lots, _Symbol, price, sl, tp, InpCandidateId);
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
   double closes[];
   ArraySetAsSeries(closes, true);
   if(CopyClose(_Symbol, PERIOD_M1, 0, 40, closes) < 25)
      return 0;

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

int HourOf(datetime value)
{
   MqlDateTime parts;
   TimeToStruct(value, parts);
   return parts.hour;
}
