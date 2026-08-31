//+------------------------------------------------------------------+
//|                                                   SiteTestEA.mq5 |
//| サイト連携の確認用。10秒ごとに0.01ロットでエントリーを繰り返す。   |
//+------------------------------------------------------------------+
#property copyright "Generated for integration testing"
#property version   "1.10"
#property strict

#include <Trade/Trade.mqh>
#include <TradingGate.mqh>

input double InpLots             = 0.01;      // Order volume
input int    InpEntryIntervalSec = 10;        // Seconds between entries
input long   InpMagicNumber      = 20260827;  // Magic number
input int    InpDeviationPoints  = 20;        // Maximum price deviation
input bool   InpDemoOnly         = true;      // Refuse trading on real accounts

#define GV_ENTRY_COUNT "AI_ENTRY_COUNT"
#define GV_LAST_ENTRY  "AI_LAST_ENTRY"

CTrade   trade;
bool     next_order_is_buy = true;
datetime g_next_entry_at   = 0;
int      g_entry_count     = 0;

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

bool CloseOwnedPositions()
{
   bool closed_any = false;
   for(int i = PositionsTotal() - 1; i >= 0; --i)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;

      if(PositionGetString(POSITION_SYMBOL) != _Symbol ||
         PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;

      if(trade.PositionClose(ticket))
      {
         Print("SiteTestEA: closed ticket ", ticket);
         closed_any = true;
      }
      else
      {
         Print("SiteTestEA: close failed. Retcode=", trade.ResultRetcode(),
               " Description=", trade.ResultRetcodeDescription());
         return false;
      }
   }
   return closed_any;
}

void MarkEntry()
{
   g_entry_count++;
   GlobalVariableSet(GV_ENTRY_COUNT, (double)g_entry_count);
   GlobalVariableSet(GV_LAST_ENTRY, (double)TimeCurrent());
}

bool OpenTestPosition()
{
   if(HasForeignPositionOnSymbol())
   {
      Print("SiteTestEA: another position exists on ", _Symbol, "; skip entry.");
      return false;
   }

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
   {
      Print("SiteTestEA: failed to read the current tick.");
      return false;
   }

   double requested = GateNumber("AI_LOT", InpLots);
   if(requested <= 0.0)
      requested = InpLots;
   const double volume = NormalizeVolume(requested);

   bool sent = false;
   if(next_order_is_buy)
      sent = trade.Buy(volume, _Symbol, 0.0, 0.0, 0.0, "SiteTestEA BUY");
   else
      sent = trade.Sell(volume, _Symbol, 0.0, 0.0, 0.0, "SiteTestEA SELL");

   if(!sent)
   {
      Print("SiteTestEA: order failed. Retcode=", trade.ResultRetcode(),
            " Description=", trade.ResultRetcodeDescription());
      return false;
   }

   MarkEntry();
   Print("SiteTestEA: entry #", g_entry_count, " opened. Volume=", volume,
         " side=", next_order_is_buy ? "BUY" : "SELL");
   next_order_is_buy = !next_order_is_buy;
   return true;
}

void TryPeriodicEntry()
{
   if(!IsTradingAllowed())
   {
      g_next_entry_at = 0;
      return;
   }

   const datetime now = TimeCurrent();
   if(g_next_entry_at == 0)
      g_next_entry_at = now + InpEntryIntervalSec;

   if(now < g_next_entry_at)
      return;

   g_next_entry_at = now + InpEntryIntervalSec;
   CloseOwnedPositions();
   OpenTestPosition();
}

int OnInit()
{
   if(InpLots <= 0.0 || InpEntryIntervalSec < 1)
   {
      Print("SiteTestEA: invalid input. Lots must be > 0 and interval >= 1 second.");
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

   if(GlobalVariableCheck(GV_ENTRY_COUNT))
      g_entry_count = (int)GlobalVariableGet(GV_ENTRY_COUNT);

   EventSetMillisecondTimer(250);
   SyncGateFileToGlobals();
   Print("SiteTestEA: ", InpEntryIntervalSec, " sec / ", InpLots, " lot repeat test on ", _Symbol);
   Print("Site stop -> panel turns red and entries stop within ", InpEntryIntervalSec, " sec.");
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
   TryPeriodicEntry();
}

void OnTick()
{
   TryPeriodicEntry();
}
//+------------------------------------------------------------------+
