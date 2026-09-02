//+------------------------------------------------------------------+
//| TrelabEA.mq5                                                     |
//| トレラボ自動売買。指令ファイルを F3 へ転写し、ゲートが閉じなら停止。 |
//| 売買ロジックは OnTick のゲート通過後に足す。                       |
//+------------------------------------------------------------------+
#property copyright "AIトレーダー"
#property version   "1.2"
#property strict

#include <TradingGate.mqh>

int OnInit()
  {
   EventSetMillisecondTimer(250);
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
   if(!IsTradingAllowed())
      return;
  }
