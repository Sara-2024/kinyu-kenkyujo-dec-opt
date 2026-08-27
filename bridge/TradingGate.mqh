//+------------------------------------------------------------------+
//| TradingGate.mqh                                                  |
//| ブリッジが書き換えるグローバル変数を読んで売買可否を判断する。       |
//| EA の OnTick() の先頭で IsTradingAllowed() を呼ぶだけでよい。      |
//+------------------------------------------------------------------+
#property strict

input string InpGateVariable = "AI_TRADING_ALLOWED";

//--- 変数が無い場合の既定値。true なら「変数が無ければ売買してよい」
input bool   InpAllowWhenMissing = false;

void SyncGateFileToGlobals()
  {
   int handle = FileOpen("trelab_gate.ini", FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(handle == INVALID_HANDLE)
      return;
   while(!FileIsEnding(handle))
     {
      string line = FileReadString(handle);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) == 0)
         continue;
      int eq = StringFind(line, "=");
      if(eq <= 0)
         continue;
      GlobalVariableSet(StringSubstr(line, 0, eq), StringToDouble(StringSubstr(line, eq + 1)));
     }
   FileClose(handle);
  }

bool IsTradingAllowed()
  {
   double value = 0.0;
   SyncGateFileToGlobals();

   // 変数が存在しない＝ブリッジがまだ書いていない、または消えた
   if(!GlobalVariableCheck(InpGateVariable))
     {
      static datetime lastWarn = 0;
      if(TimeCurrent() - lastWarn > 60)
        {
         PrintFormat("[Gate] グローバル変数 %s がありません。売買=%s",
                     InpGateVariable, InpAllowWhenMissing ? "許可" : "停止");
         lastWarn = TimeCurrent();
        }
      return(InpAllowWhenMissing);
     }

   value = GlobalVariableGet(InpGateVariable);

   // ターミナル側の自動売買スイッチも併せて確認する
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED) || !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return(false);

   return(value >= 0.5);
  }

//--- 使い方 -------------------------------------------------------
// void OnTick()
//   {
//    if(!IsTradingAllowed())
//       return;              // 新規エントリーを見送る（決済ロジックは別途)
//    ...
//   }
//------------------------------------------------------------------
