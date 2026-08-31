//+------------------------------------------------------------------+
//| TrelabGate.mq5                                                   |
//| 指令ファイルを読み、チャートに連携パネルを出す。                     |
//+------------------------------------------------------------------+
#property strict
#property version   "1.1"

#include <TradingGate.mqh>

input int InpTimerMs = 250;

int OnInit()
  {
   EventSetMillisecondTimer(MathMax(100, InpTimerMs));
   SyncGateFileToGlobals();
   return(INIT_SUCCEEDED);
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
  }
