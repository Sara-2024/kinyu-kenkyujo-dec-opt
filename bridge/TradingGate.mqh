//+------------------------------------------------------------------+
//| TradingGate.mqh                                                  |
//| サイトからの指令をチャート上で見えるようにする。                     |
//+------------------------------------------------------------------+
#property strict

input string InpGateVariable = "AI_TRADING_ALLOWED";
input bool   InpAllowWhenMissing = false;

#define TG_BG     "TrelabGate_bg"
#define TG_TITLE  "TrelabGate_title"
#define TG_STATE  "TrelabGate_state"
#define TG_LINE3  "TrelabGate_line3"
#define TG_LINE4  "TrelabGate_line4"
#define TG_LINE5  "TrelabGate_line5"

bool     g_gate_file_ok = false;
datetime g_gate_mtime   = 0;

void SyncGateFileToGlobals()
  {
   int handle = FileOpen("trelab_gate.ini", FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(handle == INVALID_HANDLE)
     {
      g_gate_file_ok = false;
      DrawGateStatus();
      return;
     }
   g_gate_file_ok = true;
   g_gate_mtime   = (datetime)FileGetInteger(handle, FILE_MODIFY_DATE);
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

bool IsTradingAllowedRaw()
  {
   if(!GlobalVariableCheck(InpGateVariable))
      return InpAllowWhenMissing;
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED) || !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return false;
   return(GlobalVariableGet(InpGateVariable) >= 0.5);
  }

void PutRect(const string id, const int x, const int y, const int w, const int h, const color fill, const color border)
  {
   if(ObjectFind(0, id) < 0)
     {
      ObjectCreate(0, id, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, id, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, id, OBJPROP_BACK, false);
      ObjectSetInteger(0, id, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, id, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, id, OBJPROP_BORDER_TYPE, BORDER_FLAT);
      ObjectSetInteger(0, id, OBJPROP_ZORDER, 1000);
     }
   ObjectSetInteger(0, id, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, id, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, id, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, id, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, id, OBJPROP_BGCOLOR, fill);
   ObjectSetInteger(0, id, OBJPROP_COLOR, border);
   ObjectSetInteger(0, id, OBJPROP_WIDTH, 2);
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
      ObjectSetInteger(0, id, OBJPROP_ZORDER, 1001);
     }
   ObjectSetInteger(0, id, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, id, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, id, OBJPROP_FONTSIZE, size);
   ObjectSetInteger(0, id, OBJPROP_COLOR, clr);
   ObjectSetString(0, id, OBJPROP_FONT, "Meiryo UI");
   ObjectSetString(0, id, OBJPROP_TEXT, text);
  }

void DrawGateStatus()
  {
   const bool autotrading = (MQLInfoInteger(MQL_TRADE_ALLOWED) && TerminalInfoInteger(TERMINAL_TRADE_ALLOWED));
   const bool allowed     = IsTradingAllowedRaw();
   const double lot       = GateNumber("AI_LOT", 0);
   const double maxp      = GateNumber("AI_MAX_POSITIONS", 0);
   const double dayl      = GateNumber("AI_DAY_LOSS_LIMIT", 0);
   const long   login     = AccountInfoInteger(ACCOUNT_LOGIN);
   const string server    = AccountInfoString(ACCOUNT_SERVER);

   color fill   = C'12,22,38';
   color border = C'80,160,200';
   color statec = clrSilver;
   string state = "指令待ち";

   if(!g_gate_file_ok)
     {
      fill   = C'40,28,8';
      border = clrOrange;
      statec = clrOrange;
      state  = "未接続（接続ツールを起動）";
     }
   else if(!autotrading)
     {
      fill   = C'48,20,8';
      border = clrOrange;
      statec = clrOrange;
      state  = "自動売買ボタンがオフ";
     }
   else if(allowed)
     {
      fill   = C'6,42,28';
      border = clrLime;
      statec = clrLime;
      state  = "稼働中（サイトと連携）";
     }
   else
     {
      fill   = C'52,12,12';
      border = clrOrangeRed;
      statec = clrOrangeRed;
      state  = "停止中（サイトから停止）";
     }

   static string last_state = "";
   if(state != last_state)
     {
      Print("システム表示: ", state);
      last_state = state;
     }

   PutRect(TG_BG, 10, 22, 460, 168, fill, border);
   PutLabel(TG_TITLE, 24, 32, 13, clrSilver, "トレード研究所  システム連携");
   PutLabel(TG_STATE, 24, 56, 22, statec, state);
   PutLabel(TG_LINE3, 24, 92, 14, clrWhite,
            "口座  " + IntegerToString(login) + "   " + server);

   string lot_s  = (lot > 0)  ? StringFormat("%.2f", lot)  : "未受信";
   string max_s  = (maxp > 0) ? StringFormat("%.0f", maxp) : "未受信";
   string day_s  = (dayl > 0) ? StringFormat("%.0f", dayl) : "未受信";
   PutLabel(TG_LINE4, 24, 118, 14, clrWhite,
            StringFormat("ロット %s    同時 %s    1日上限 %s", lot_s, max_s, day_s));

   string beat = TimeToString(TimeLocal(), TIME_SECONDS);
   const double entry_n = GateNumber("AI_ENTRY_COUNT", 0);
   const datetime last_e = (datetime)GateNumber("AI_LAST_ENTRY", 0);
   string entry_info = "エントリー待機中";
   if(entry_n > 0)
      entry_info = StringFormat("エントリー %d回  直近 %s", (int)entry_n, TimeToString(last_e, TIME_SECONDS));
   else if(allowed && g_gate_file_ok && autotrading)
      entry_info = "稼働中 — 最初のエントリーを待っています";
   PutLabel(TG_LINE5, 24, 144, 13, clrSilver, beat + "  " + entry_info);

   ChartRedraw(0);
  }

void RemoveGateStatus()
  {
   ObjectDelete(0, TG_BG);
   ObjectDelete(0, TG_TITLE);
   ObjectDelete(0, TG_STATE);
   ObjectDelete(0, TG_LINE3);
   ObjectDelete(0, TG_LINE4);
   ObjectDelete(0, TG_LINE5);
  }

bool IsTradingAllowed()
  {
   SyncGateFileToGlobals();
   return IsTradingAllowedRaw();
  }
