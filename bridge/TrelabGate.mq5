//+------------------------------------------------------------------+
//| TrelabGate.mq5                                                   |
//| ブリッジが Common/Files に書いた指令を、F3 のグローバル変数へ転写。 |
//| 任意のチャートに1本付けるだけでよい。                             |
//+------------------------------------------------------------------+
#property strict
#property version   "1.0"

input string InpGateFile = "trelab_gate.ini";
input int    InpTimerMs  = 250;

int OnInit()
  {
   EventSetMillisecondTimer(MathMax(100, InpTimerMs));
   SyncFromFile();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTimer()
  {
   SyncFromFile();
  }

void OnTick()
  {
  }

void SyncFromFile()
  {
   int handle = FileOpen(InpGateFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE);
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
      string name = StringSubstr(line, 0, eq);
      string raw  = StringSubstr(line, eq + 1);
      double value = StringToDouble(raw);
      GlobalVariableSet(name, value);
     }
   FileClose(handle);
  }
