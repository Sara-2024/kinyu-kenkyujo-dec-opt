//+------------------------------------------------------------------+
//|                                                   SiteTestEA.mq5 |
//| A minimal Expert Advisor for testing MT5 integrations.           |
//+------------------------------------------------------------------+
#property copyright "Generated for integration testing"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>
#include <TradingGate.mqh>

input double InpLots             = 0.01;      // Order volume
input int    InpHoldBars         = 2;         // Bars to hold a position
input int    InpStopLossPoints   = 500;       // Stop loss (points, 0 = disabled)
input int    InpTakeProfitPoints = 500;       // Take profit (points, 0 = disabled)
input long   InpMagicNumber      = 20260827;  // Magic number
input int    InpDeviationPoints  = 20;        // Maximum price deviation
input bool   InpDemoOnly         = true;      // Refuse trading on real accounts

CTrade   trade;
datetime last_bar_time = 0;
bool     next_order_is_buy = true;
int      held_bars = 0;

// Normalize the requested volume to the symbol's allowed range and step.
double NormalizeVolume(const double requested)
{
   const double min_volume = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   const double max_volume = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   const double step       = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(step <= 0.0)
      return min_volume;

   double volume = MathMax(min_volume, MathMin(max_volume, requested));
   volume = min_volume + MathFloor((volume - min_volume) / step + 0.5) * step;
   return NormalizeDouble(volume, 8);
}

// Find a position created by this EA. Returns its ticket, or 0 if none exists.
ulong FindOwnedPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; --i)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;

      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         return ticket;
   }

   return 0;
}

// Avoid interfering with positions opened manually or by another EA.
bool HasForeignPositionOnSymbol()
{
   for(int i = PositionsTotal() - 1; i >= 0; --i)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;

      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         return true;
   }

   return false;
}

bool OpenTestPosition()
{
   if(HasForeignPositionOnSymbol())
   {
      Print("SiteTestEA: another position exists on ", _Symbol, "; no order sent.");
      return false;
   }

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
   {
      Print("SiteTestEA: failed to read the current tick.");
      return false;
   }

   const int    digits     = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   const int    stops      = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   const double min_dist   = stops * _Point;
   const double sl_dist    = InpStopLossPoints > 0
                             ? MathMax(InpStopLossPoints * _Point, min_dist)
                             : 0.0;
   const double tp_dist    = InpTakeProfitPoints > 0
                             ? MathMax(InpTakeProfitPoints * _Point, min_dist)
                             : 0.0;
   const double volume     = NormalizeVolume(InpLots);

   double sl = 0.0;
   double tp = 0.0;
   bool sent = false;

   if(next_order_is_buy)
   {
      if(sl_dist > 0.0) sl = NormalizeDouble(tick.ask - sl_dist, digits);
      if(tp_dist > 0.0) tp = NormalizeDouble(tick.ask + tp_dist, digits);
      sent = trade.Buy(volume, _Symbol, 0.0, sl, tp, "SiteTestEA BUY");
   }
   else
   {
      if(sl_dist > 0.0) sl = NormalizeDouble(tick.bid + sl_dist, digits);
      if(tp_dist > 0.0) tp = NormalizeDouble(tick.bid - tp_dist, digits);
      sent = trade.Sell(volume, _Symbol, 0.0, sl, tp, "SiteTestEA SELL");
   }

   if(!sent)
   {
      Print("SiteTestEA: order failed. Retcode=", trade.ResultRetcode(),
            " Description=", trade.ResultRetcodeDescription());
      return false;
   }

   Print("SiteTestEA: order opened. Order=", trade.ResultOrder(),
         " Deal=", trade.ResultDeal(), " Volume=", volume);
   next_order_is_buy = !next_order_is_buy;
   held_bars = 0;
   return true;
}

int OnInit()
{
   if(InpLots <= 0.0 || InpHoldBars < 1)
   {
      Print("SiteTestEA: invalid input. Lots must be > 0 and HoldBars must be >= 1.");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(InpDemoOnly &&
      (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO)
   {
      Alert("SiteTestEA is demo-only. Set InpDemoOnly=false only if you intentionally want live trading.");
      return INIT_FAILED;
   }

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpDeviationPoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   EventSetMillisecondTimer(250);
   SyncGateFileToGlobals();
   Print("SiteTestEA initialized on ", _Symbol, " / ", EnumToString((ENUM_TIMEFRAMES)_Period));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   RemoveGateStatus();
}

void OnTimer()
{
   SyncGateFileToGlobals();
}

void OnTick()
{
   if(!IsTradingAllowed())
      return;

   const datetime current_bar_time = iTime(_Symbol, _Period, 0);
   if(current_bar_time <= 0 || current_bar_time == last_bar_time)
      return;

   last_bar_time = current_bar_time;
   const ulong position_ticket = FindOwnedPosition();

   if(position_ticket == 0)
   {
      OpenTestPosition();
      return;
   }

   held_bars++;
   if(held_bars < InpHoldBars)
      return;

   if(!trade.PositionClose(position_ticket))
   {
      Print("SiteTestEA: close failed. Retcode=", trade.ResultRetcode(),
            " Description=", trade.ResultRetcodeDescription());
      return;
   }

   Print("SiteTestEA: position closed. Ticket=", position_ticket);
   held_bars = 0;
}
//+------------------------------------------------------------------+
