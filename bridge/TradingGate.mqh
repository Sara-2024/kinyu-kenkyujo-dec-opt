//+------------------------------------------------------------------+
//| TradingGate.mqh                                                  |
//| サイトからの指令をチャート上で見えるようにする。                     |
//|   ・稼働／停止（AI_TRADING_ALLOWED）・ロット・同時保有数・1日の上限  |
//|   ・接続ツールが生きているか（AI_BRIDGE_AT。30 秒ごとに書かれる合図）|
//|   ・状態ファイル（trelab_state.ini。接続ツールが EA の生存を知る）   |
//| AI による新規注文の見張り（AIリスク監督）は 2026-10-14 に廃止した。   |
//+------------------------------------------------------------------+
#property strict

// EA はこのファイルを「ロットなどの入力の後ろ」で include する（設定画面でロットを一番上に出すため）。
input group "===== サイト連携（変えない） ====="
input string InpGateVariable = "AI_TRADING_ALLOWED";   // 稼働/停止を受け取る変数名
input bool   InpAllowWhenMissing = false;              // 指令が無いとき稼働するか

#define TG_BG     "TrelabGate_bg"
#define TG_TITLE  "TrelabGate_title"
#define TG_STATE  "TrelabGate_state"
#define TG_LINE3  "TrelabGate_line3"
#define TG_LINE4  "TrelabGate_line4"
#define TG_LINE5  "TrelabGate_line5"

// 接続ツールの合図（AI_BRIDGE_AT）がこれより古ければ「未接続」と出す。
// 接続ツールは 30 秒ごとに書くので、数回落としても持つ長さにしてある
#define GATE_ALIVE_SEC 180

// EA の設定「ユメックAIの制御を受ける」。false のとき、サイトの稼働/停止は見ない（EA が OnInit で入れる）
bool     GateSiteControl = true;
// 指令・控えのファイル名。同じ PC に口座が 2 つ以上あるとき（ロイヤルファーストクラス）、
// 接続ツールは口座番号付きの名前（trelab_gate_<口座番号>.ini）も書く。あればそちらを読み、
// 控えもその名前で書く。無ければこれまでの名前（1 口座の PC・古い接続ツール）
string GateFileName()
  {
   const string named = "trelab_gate_" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ".ini";
   return(FileIsExist(named, FILE_COMMON) ? named : "trelab_gate.ini");
  }
string StateFileName()
  {
   const string named = "trelab_gate_" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ".ini";
   return(FileIsExist(named, FILE_COMMON) ? "trelab_state_" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ".ini" : "trelab_state.ini");
  }

bool     g_gate_file_ok = false;
datetime g_gate_mtime   = 0;
// 指令ファイルが「前に読んだときから変わった」のを最後に見た時刻（この PC の時計）。
// 更新時刻や合図の値を PC の時計と直接比べない（MT5 がどの時間基準で返すかに依らない）。
datetime g_gate_prev_mtime = 0;
double   g_gate_prev_beat  = -1.0;
datetime g_gate_changed_at = 0;

void SyncGateFileToGlobals()
  {
   int handle = FileOpen(GateFileName(), FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(handle == INVALID_HANDLE)
     {
      g_gate_file_ok = false;
      DrawGateStatus();
      return;
     }
   g_gate_file_ok = true;
   g_gate_mtime   = (datetime)FileGetInteger(handle, FILE_MODIFY_DATE);
   if(g_gate_mtime != g_gate_prev_mtime)
     {
      g_gate_prev_mtime = g_gate_mtime;
      g_gate_changed_at = TimeLocal();
     }

   // 合図は毎回 0 に戻してから読み直す。MT5 のグローバル変数は消えずに残るので、
   // 指令ファイルから行が消えても古い合図が居座り、「連携済み」のままになるため
   GlobalVariableSet("AI_BRIDGE_AT", 0.0);

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
   const double beat = GateNumber("AI_BRIDGE_AT", 0.0);
   if(beat != g_gate_prev_beat)
     {
      g_gate_prev_beat  = beat;
      if(beat > 0) g_gate_changed_at = TimeLocal();
     }
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
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED) || !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return false;
   if(!GateSiteControl)
      return true;                       // 制御を受けない：自動売買ボタンだけで決まる
   if(!GlobalVariableCheck(InpGateVariable))
      return InpAllowWhenMissing;
   return(GlobalVariableGet(InpGateVariable) >= 0.5);
  }

//+------------------------------------------------------------------+
//| 接続ツール（パスポート）が生きているか。                            |
//|   接続ツールは 30 秒ごとに指令ファイルへ AI_BRIDGE_AT（合図）を書く。 |
//|   この EA は 1 秒ごとにファイルを読み、「合図の値」か「更新時刻」が    |
//|   前回と変わっていれば、そのとき（PC の時計）を覚える。              |
//|   最後に変わってから GATE_ALIVE_SEC 以内なら「連携済み」。            |
//|   古い接続ツールは合図を書かないが、指令ファイルを書き直すので         |
//|   更新時刻の変化で拾える。                                           |
//+------------------------------------------------------------------+
bool GateBridgeAlive()
  {
   if(!g_gate_file_ok || g_gate_changed_at <= 0)
      return(false);
   return((TimeLocal() - g_gate_changed_at) <= GATE_ALIVE_SEC);
  }

//--- パネルに出す1行（サイトと連携しているか）
string SiteLinkLine()
  {
   return(GateBridgeAlive() ? "ユメックAIと連携済み" : "ユメックAIと未接続");
  }

void WriteStateFile(const string state, const bool allowed)
  {
   int h = FileOpen(StateFileName(),
                    FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return;
   FileWriteString(h, "state=" + state + "\n");
   FileWriteString(h, "allowed=" + (allowed ? "1" : "0") + "\n");
   FileWriteString(h, "at=" + TimeToString(TimeLocal(), TIME_DATE|TIME_SECONDS) + "\n");
   FileWriteString(h, "account=" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "\n");
   FileWriteString(h, "ea=" + MQLInfoString(MQL_PROGRAM_NAME) + "\n");
   FileWriteString(h, "common=" + TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\n");
   FileWriteString(h, "symbol=" + _Symbol + "\n");
   FileWriteString(h, "bridge_alive=" + (GateBridgeAlive() ? "1" : "0") + "\n");
   FileClose(h);
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

//+------------------------------------------------------------------+
//| いまチャートに出している状態を、サイト側から読めるように書き出す。 |
//| これでサイトの表示と MT5 の表示がズレていないか確認できる。        |
//+------------------------------------------------------------------+
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
      state  = GateSiteControl ? "稼働中" : "稼働中（ユメックAIの制御なし）";
     }
   else
     {
      fill   = C'52,12,12';
      border = clrOrangeRed;
      statec = clrOrangeRed;
      state  = "ユメックAIが停止中";
     }

   static string   last_state = "";
   static datetime last_write = 0;
   if(state != last_state)
     {
      Print("システム表示: ", state);
      last_state = state;
      WriteStateFile(state, allowed);
      last_write = TimeLocal();
     }
   else if(TimeLocal() - last_write >= 10)
     {
      // 生きていることが分かるよう、変化が無くても10秒ごとに書く
      WriteStateFile(state, allowed);
      last_write = TimeLocal();
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
   PutLabel(TG_LINE5, 24, 144, 13, clrSilver, beat + "  " + entry_info + "   " + SiteLinkLine());

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
