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
     {
      DrawGateStatus();
      return;
     }
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
   DrawGateStatus();
  }

double GateNumber(const string name, const double fallback)
  {
   if(GlobalVariableCheck(name))
      return GlobalVariableGet(name);
   return fallback;
  }

void DrawGateStatus()
  {
   const bool allowed = IsTradingAllowedRaw();
   const double lot = GateNumber("AI_LOT", 0);
   const double maxp = GateNumber("AI_MAX_POSITIONS", 0);
   const double dayl = GateNumber("AI_DAY_LOSS_LIMIT", 0);

   string line1 = allowed ? "システム  稼働中" : "システム  停止中（サイトから停止）";
   string line2 = StringFormat("ロット %.2f    同時 %.0f    1日上限 %.0f", lot, maxp, dayl);

   PutLabel("TrelabGate_1", 12, 18, 16, allowed ? clrLime : clrOrangeRed, line1);
   PutLabel("TrelabGate_2", 12, 42, 12, clrSilver, line2);
  }

bool IsTradingAllowedRaw()
  {
   if(!GlobalVariableCheck(InpGateVariable))
      return InpAllowWhenMissing;
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED) || !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return false;
   return(GlobalVariableGet(InpGateVariable) >= 0.5);
  }

void PutLabel(const string id, const int x, const int y, const int size, const color clr, const string text)
  {
   if(ObjectFind(0, id) < 0)
     {
      ObjectCreate(0, id, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, id, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, id, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
      ObjectSetInteger(0, id, OBJPROP_BACK, false);
      ObjectSetInteger(0, id, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, id, OBJPROP_HIDDEN, true);
     }
   ObjectSetInteger(0, id, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, id, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, id, OBJPROP_FONTSIZE, size);
   ObjectSetInteger(0, id, OBJPROP_COLOR, clr);
   ObjectSetString(0, id, OBJPROP_FONT, "Meiryo UI");
   ObjectSetString(0, id, OBJPROP_TEXT, text);
  }

void RemoveGateStatus()
  {
   ObjectDelete(0, "TrelabGate_1");
   ObjectDelete(0, "TrelabGate_2");
  }

bool IsTradingAllowed()
  {
   SyncGateFileToGlobals();
   return IsTradingAllowedRaw();
  }

//--- 使い方 -------------------------------------------------------
// void OnTick()
//   {
//    if(!IsTradingAllowed())
//       return;              // 新規エントリーを見送る（決済ロジックは別途)
//    ...
//   }
//------------------------------------------------------------------
