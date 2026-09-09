//+------------------------------------------------------------------+
//|                                               OrbitGoldEA_v5.mq5 |
//|                  Orbit GOLD 2軸エンジン（M1絞り込み + H1独立軸）  |
//|                                                                  |
//|  20ヶ月の実XAUUSD M1データ(587,900本)でのバックテストに基づく設計。|
//|                                                                  |
//|  v3 の致命的欠陥を修正:                                          |
//|   旧: 3回ナンピン後の全体SLが最終追加からわずか1step下だった      |
//|       → 満玉後は「+6step勝ち / -1step負け」の勝てない構造         |
//|       → MT5実測で4レッグ363件の勝率10.5% / -1,105,524円          |
//|   新: InpM1NanpinSLRoom で最終追加からの余裕stepを指定（既定3）   |
//|                                                                  |
//|  ATR は Pine の ta.atr と同じ Wilder RMA で自前計算（iATRは別物）  |
//|                                                                  |
//|  トレード研究所（サイト）との連携: TradingGate.mqh                 |
//|   ・稼働/停止・ロット・同時保有数・1日の損失上限は、サイトの管理画面 |
//|     から指令ファイル → 端末グローバル変数で届く                    |
//|   ・入力パラメータは「サイトから値が来ていないとき」の既定値        |
//|   ・10秒ごとに状態ファイルを書き、サイトが生存を確認する            |
//+------------------------------------------------------------------+
#property copyright "Orbit GOLD EA v5"
#property version   "5.00"
#property description "Orbit GOLD 2軸EA v5: 深いトレール利確 + ナンピン最適化"

#include <Trade\Trade.mqh>
#include <TradingGate.mqh>   // サイト連携（稼働/停止・ロット・上限・状態ファイル）

enum ENUM_LOT_MODE { LOT_FIXED = 0, LOT_RISK = 1 };

//==================================================================
// 入力
//==================================================================
input group "===== 共通 ====="
input ENUM_LOT_MODE InpLotMode        = LOT_FIXED;  // ロット決定方式
input double  InpFixedLot             = 0.01;       // 固定ロット（サイトの AI_LOT が届いていればそちら）
input double  InpRiskPercent          = 0.5;        // 残高リスク％(LOT_RISK時)
input double  InpMaxLot               = 5.00;       // ロット上限（サイトの管理画面の上限に合わせる）
input double  InpMaxSpreadUSD         = 0.60;       // 最大許容スプレッド(USD, 0=無制限)
input int     InpSlippagePoints       = 40;         // 許容スリッページ(ポイント)
input bool    InpRestrictToGold       = true;       // XAU/GOLD 以外では発注しない
input int     InpWarmupBars           = 5000;       // 起動時に再生する過去足本数
input bool    InpVerboseLog           = true;       // 詳細ログ

input group "===== M1軸 ====="
input bool    InpM1Enabled            = true;       // M1軸を有効にする
input long    InpM1Magic              = 20260901;   // M1軸 マジックナンバー
input double  InpM1MinAtrUSD          = 2.00;       // ATRがこの値(USD)未満なら見送り
input bool    InpM1RequireH1Align     = true;       // H1トレンドと方向一致を必須化
input int     InpM1Cooldown           = 30;         // クールダウン本数
input int     InpM1MaxSignals         = 2;          // 1トレンドあたり最大サイン数
input double  InpM1SLatrMult          = 5.0;        // 損切り幅(ATR倍) ※ナンピンOFF時のみ使用
input double  InpM1TPatrMult          = 4.5;        // 利確幅(ATR倍) ※ナンピン時は平均取得から

input group "===== M1軸 ナンピン（等倍・全体SL付き） ====="
input bool    InpM1NanpinEnabled      = true;       // ナンピンを使う(false=単発・広SL運用)
input double  InpM1NanpinStepATR      = 1.0;        // 追加する値幅（ATR倍）
input int     InpM1NanpinMaxAdds      = 3;          // 最大追加回数
input int     InpM1NanpinSLRoom       = 4;          // ★最終ナンピン地点から更に何step下にSLを置くか
input double  InpM1NanpinLotMult      = 1.0;        // ロット倍率(1.0=等倍。絶対に上げないこと)

input group "===== M1軸 トレール利確 ====="
input double  InpM1TrailStartATR      = 4.0;        // 平均取得からこのstep倍の含み益で開始(0=無効)
input double  InpM1TrailDistATR       = 2.0;        // 最高値からこのstep倍下にSLを置く

input group "===== H1軸（独立） ====="
input bool    InpH1Enabled            = true;       // H1軸を有効にする
input long    InpH1Magic              = 20260902;   // H1軸 マジックナンバー
input int     InpH1MaxPositions       = 1;          // H1軸 同時保有数
input int     InpH1Cooldown           = 10;         // クールダウン本数
input int     InpH1MaxSignals         = 2;          // 1トレンドあたり最大サイン数
input double  InpH1AtrSLmult          = 1.5;        // ATR SL倍率
input double  InpH1RR                 = 2.0;        // リスクリワード比

input group "===== シグナル共通（インジケーター準拠・通常は変更不要） ====="
input int     InpEmaPeriod            = 200;        // トレンド判定EMA期間
input int     InpAtrPeriod            = 14;         // ATR期間
input int     InpInternalLeft         = 1;          // 内部スイング 左本数
input int     InpInternalRight        = 1;          // 内部スイング 右本数
input int     InpExternalLeft         = 5;          // 外部スイング 左本数
input int     InpExternalRight        = 5;          // 外部スイング 右本数
input double  InpAtrMultiplier        = 0.12;       // リテスト許容ATR倍率
input int     InpRetestBars           = 6;          // リテスト待機本数

//==================================================================
// 状態
//==================================================================
struct SState
  {
   double lastInternalHigh, lastInternalLow;
   double lastExternalHigh, lastExternalLow;
   bool   externalTrendUp, externalTrendDown;
   int    currentTrendDir, trendSignalCount;
   bool   waitingRetestBuy, waitingRetestSell;
   double breakLevelBuy, breakLevelSell;
   long   breakBarBuy, breakBarSell;
   long   lastSignalBar;
  };

struct SEngine
  {
   ENUM_TIMEFRAMES tf;
   string   name;
   bool     enabled;
   long     magic;
   int      maxPositions;
   int      cooldown, maxSignals;
   double   slAtrMult;       // 損切り幅(ATR倍)
   double   tpAtrMult;       // 利確幅(ATR倍)
   double   minAtr;          // ATR下限(USD) 0=無効
   bool     requireH1Align;
   int      emaHandle;
   double   atr;             // Wilder RMA（直近確定足）
   SState   st;
   long     barIndex;
   datetime lastBarTime;
   bool     warmed;
  };

CTrade   g_trade;
SEngine  g_m1, g_h1;
bool     g_symbolAllowed = true;
string   GVN_FIRST, GVN_STEP, GVN_TPD, GVN_BEST;   // バスケット状態（再起動しても復元できるよう端末GVに保存）

#define EMPTY_PIVOT (-1.0)
bool IsEmptyV(const double v) { return(v <= EMPTY_PIVOT + 0.5); }

//==================================================================
// 基礎ユーティリティ
//==================================================================
double TrueRange(const ENUM_TIMEFRAMES tf, const int shift)
  {
   double hi = iHigh(_Symbol, tf, shift);
   double lo = iLow(_Symbol, tf, shift);
   double pc = iClose(_Symbol, tf, shift+1);
   if(hi <= 0.0 || lo <= 0.0 || pc <= 0.0) return(0.0);
   return(MathMax(hi-lo, MathMax(MathAbs(hi-pc), MathAbs(lo-pc))));
  }

double PivotHighTF(const ENUM_TIMEFRAMES tf, const int shift, const int left, const int right)
  {
   int cand = shift + right;
   if(cand + left >= Bars(_Symbol, tf)) return(EMPTY_PIVOT);
   double cv = iHigh(_Symbol, tf, cand);
   if(cv <= 0.0) return(EMPTY_PIVOT);
   for(int i=1; i<=left; i++)  if(iHigh(_Symbol,tf,cand+i) >= cv) return(EMPTY_PIVOT);
   for(int i=1; i<=right; i++) if(iHigh(_Symbol,tf,cand-i) >= cv) return(EMPTY_PIVOT);
   return(cv);
  }

double PivotLowTF(const ENUM_TIMEFRAMES tf, const int shift, const int left, const int right)
  {
   int cand = shift + right;
   if(cand + left >= Bars(_Symbol, tf)) return(EMPTY_PIVOT);
   double cv = iLow(_Symbol, tf, cand);
   if(cv <= 0.0) return(EMPTY_PIVOT);
   for(int i=1; i<=left; i++)  if(iLow(_Symbol,tf,cand+i) <= cv) return(EMPTY_PIVOT);
   for(int i=1; i<=right; i++) if(iLow(_Symbol,tf,cand-i) <= cv) return(EMPTY_PIVOT);
   return(cv);
  }

void ResetState(SState &st)
  {
   st.lastInternalHigh = st.lastInternalLow = EMPTY_PIVOT;
   st.lastExternalHigh = st.lastExternalLow = EMPTY_PIVOT;
   st.externalTrendUp  = st.externalTrendDown = false;
   st.currentTrendDir  = 0;  st.trendSignalCount = 0;
   st.waitingRetestBuy = st.waitingRetestSell = false;
   st.breakLevelBuy    = st.breakLevelSell = EMPTY_PIVOT;
   st.breakBarBuy      = st.breakBarSell = -1;
   st.lastSignalBar    = -1;
  }

//==================================================================
// 1本分のバー処理（Pine のバー単位実行に相当）
//   戻り値: 0=シグナル無し, 1=BUY, -1=SELL / sl,tp を出力
//==================================================================
int ProcessBar(SEngine &eng, const int shift, double &outEntry, double &outSL, double &outTP)
  {
   outEntry = outSL = outTP = 0.0;
   ENUM_TIMEFRAMES tf = eng.tf;

   double hi = iHigh(_Symbol,tf,shift), lo = iLow(_Symbol,tf,shift), cl = iClose(_Symbol,tf,shift);
   if(hi<=0.0 || lo<=0.0 || cl<=0.0) return(0);

   double emaBuf[];
   if(CopyBuffer(eng.emaHandle,0,shift,1,emaBuf)!=1) return(0);
   double ema = emaBuf[0];
   if(ema<=0.0 || eng.atr<=0.0) return(0);

   //--- ピボット更新
   double iph = PivotHighTF(tf,shift,InpInternalLeft,InpInternalRight);
   double ipl = PivotLowTF (tf,shift,InpInternalLeft,InpInternalRight);
   double eph = PivotHighTF(tf,shift,InpExternalLeft,InpExternalRight);
   double epl = PivotLowTF (tf,shift,InpExternalLeft,InpExternalRight);
   if(!IsEmptyV(iph)) eng.st.lastInternalHigh = iph;
   if(!IsEmptyV(ipl)) eng.st.lastInternalLow  = ipl;
   if(!IsEmptyV(eph)) eng.st.lastExternalHigh = eph;
   if(!IsEmptyV(epl)) eng.st.lastExternalLow  = epl;

   //--- 外部トレンド
   if(!IsEmptyV(eng.st.lastExternalHigh) && hi > eng.st.lastExternalHigh)
     { eng.st.externalTrendUp = true;  eng.st.externalTrendDown = false; }
   if(!IsEmptyV(eng.st.lastExternalLow)  && lo < eng.st.lastExternalLow)
     { eng.st.externalTrendDown = true; eng.st.externalTrendUp   = false; }

   bool trendUp   = (cl > ema) && eng.st.externalTrendUp;
   bool trendDown = (cl < ema) && eng.st.externalTrendDown;

   int nd = trendUp ? 1 : (trendDown ? -1 : 0);
   if(nd != eng.st.currentTrendDir) eng.st.trendSignalCount = 0;
   eng.st.currentTrendDir = nd;

   double retestRange = eng.atr * InpAtrMultiplier;

   //--- ブレイク
   if(trendUp && !IsEmptyV(eng.st.lastInternalHigh) && cl > eng.st.lastInternalHigh)
     { eng.st.waitingRetestBuy = true;  eng.st.breakLevelBuy  = eng.st.lastInternalHigh; eng.st.breakBarBuy  = eng.barIndex; }
   if(trendDown && !IsEmptyV(eng.st.lastInternalLow) && cl < eng.st.lastInternalLow)
     { eng.st.waitingRetestSell = true; eng.st.breakLevelSell = eng.st.lastInternalLow;  eng.st.breakBarSell = eng.barIndex; }

   //--- リテスト
   bool retestBuy  = eng.st.waitingRetestBuy  && eng.st.breakBarBuy>=0 &&
                     (eng.barIndex-eng.st.breakBarBuy  <= InpRetestBars) && (lo <= eng.st.breakLevelBuy  + retestRange);
   bool retestSell = eng.st.waitingRetestSell && eng.st.breakBarSell>=0 &&
                     (eng.barIndex-eng.st.breakBarSell <= InpRetestBars) && (hi >= eng.st.breakLevelSell - retestRange);

   if(eng.st.waitingRetestBuy  && eng.st.breakBarBuy>=0  && (eng.barIndex-eng.st.breakBarBuy)  > InpRetestBars) eng.st.waitingRetestBuy  = false;
   if(eng.st.waitingRetestSell && eng.st.breakBarSell>=0 && (eng.barIndex-eng.st.breakBarSell) > InpRetestBars) eng.st.waitingRetestSell = false;

   bool cdOK = (eng.st.lastSignalBar < 0) || (eng.barIndex - eng.st.lastSignalBar > eng.cooldown);
   bool cnOK = (eng.st.trendSignalCount < eng.maxSignals);

   bool buy  = retestBuy  && cdOK && cnOK;
   bool sell = retestSell && cdOK && cnOK;
   if(!buy && !sell) return(0);

   //--- ★絞り込みフィルター（M1軸）------------------------------
   //  1) H1 トレンド一致（H1エンジンの確定トレンドを参照）
   if(eng.requireH1Align)
     {
      int hd = g_h1.st.currentTrendDir;
      if(hd == 0) return(0);
      if(buy  && hd < 0) return(0);
      if(sell && hd > 0) return(0);
     }
   //  2) ATR の下限（低ボラ時のスプレッド負けを排除）
   if(eng.minAtr > 0.0 && eng.atr < eng.minAtr) return(0);
   //---------------------------------------------------------------

   double entry  = cl;
   double slDist = eng.atr * eng.slAtrMult;
   double tpDist = eng.atr * eng.tpAtrMult;
   if(slDist <= 0.0 || tpDist <= 0.0) return(0);
   double sl = buy ? entry - slDist : entry + slDist;
   double tp = buy ? entry + tpDist : entry - tpDist;

   //--- 発火に伴う状態更新
   eng.st.trendSignalCount++;
   eng.st.lastSignalBar = eng.barIndex;
   if(buy) eng.st.waitingRetestBuy = false; else eng.st.waitingRetestSell = false;

   outEntry = entry; outSL = sl; outTP = tp;
   return(buy ? 1 : -1);
  }

//==================================================================
// エンジン初期化 / ウォームアップ
//==================================================================
bool InitEngine(SEngine &eng, const ENUM_TIMEFRAMES tf, const string nm, const bool en,
                const long magic, const int maxPos, const int cd, const int maxSig,
                const double slm, const double tpm, const double minAtr, const bool alignH1)
  {
   eng.tf=tf; eng.name=nm; eng.enabled=en; eng.magic=magic; eng.maxPositions=maxPos;
   eng.cooldown=cd; eng.maxSignals=maxSig; eng.slAtrMult=slm; eng.tpAtrMult=tpm;
   eng.minAtr=minAtr; eng.requireH1Align=alignH1;
   eng.atr=0.0; eng.barIndex=0; eng.lastBarTime=0; eng.warmed=false;
   ResetState(eng.st);
   eng.emaHandle = iMA(_Symbol, tf, InpEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
   if(eng.emaHandle == INVALID_HANDLE)
     { PrintFormat("[%s] EMAハンドル作成失敗", nm); return(false); }
   return(true);
  }

void WarmUpEngine(SEngine &eng)
  {
   int total = Bars(_Symbol, eng.tf);
   int need  = InpEmaPeriod + InpAtrPeriod +
               MathMax(InpExternalLeft+InpExternalRight, InpInternalLeft+InpInternalRight) + 10;
   if(total < need + 60) return;
   if(BarsCalculated(eng.emaHandle) < need) return;

   int start = MathMin(InpWarmupBars, total - need - 5);
   if(start < 50) return;

   ResetState(eng.st); eng.barIndex = 0;

   //--- ATR(Wilder) のシード: start+1 から遡って atrPeriod 本の TR 平均
   double s = 0.0;
   for(int k=0; k<InpAtrPeriod; k++) s += TrueRange(eng.tf, start+1+k);
   eng.atr = s / InpAtrPeriod;

   double e,sl,tp;
   for(int sh=start; sh>=1; sh--)
     {
      eng.atr = (eng.atr*(InpAtrPeriod-1) + TrueRange(eng.tf,sh)) / InpAtrPeriod;
      eng.barIndex++;
      ProcessBar(eng, sh, e, sl, tp);   // ウォームアップ中は発注しない
     }
   eng.lastBarTime = iTime(_Symbol, eng.tf, 0);
   eng.warmed = true;
   PrintFormat("[%s] ウォームアップ完了 %d本 / トレンド=%d ATR=$%.2f",
               eng.name, start, eng.st.currentTrendDir, eng.atr);
  }

//==================================================================
// 取引
//==================================================================
int CountPositions(const long magic, int &buys, int &sells)
  {
   buys=0; sells=0;
   for(int i=PositionsTotal()-1; i>=0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != magic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY) buys++; else sells++;
     }
   return(buys+sells);
  }

//==================================================================
// サイト連携（トレード研究所）
//   AI_TRADING_ALLOWED … 稼働/停止（無ければ停止）
//   AI_LOT             … 1回の注文ロット（無ければ InpFixedLot）
//   AI_MAX_POSITIONS   … この EA が同時に持つ建玉の上限（新規のみ。ナンピン追加は別）
//   AI_DAY_LOSS_LIMIT  … 本日の確定損益＋含み損益がこれを下回ったら、その日は新規を止める
//==================================================================
bool IsOrbitMagic(const long magic) { return(magic==InpM1Magic || magic==InpH1Magic); }

double SiteLot()
  {
   double lot = GateNumber("AI_LOT", 0.0);
   return((lot > 0.0) ? lot : InpFixedLot);
  }

int CountOrbitPositions()
  {
   int b,s,n=0;
   n += CountPositions(InpM1Magic,b,s);
   n += CountPositions(InpH1Magic,b,s);
   return(n);
  }

// 本日（サーバー時計）の確定損益。この EA の建玉ぶんだけ、口座通貨。30秒キャッシュ
double TodayClosedProfit()
  {
   static datetime at=0; static double sum=0.0;
   datetime now=TimeCurrent();
   if(at!=0 && now-at<30) return(sum);
   at=now; sum=0.0;
   datetime day = now - (now % 86400);
   if(!HistorySelect(day, now+60)) return(sum);
   int n=HistoryDealsTotal();
   for(int i=0;i<n;i++)
     {
      ulong tk=HistoryDealGetTicket(i); if(tk==0) continue;
      if(!IsOrbitMagic(HistoryDealGetInteger(tk,DEAL_MAGIC))) continue;
      long entry=HistoryDealGetInteger(tk,DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_OUT && entry!=DEAL_ENTRY_INOUT && entry!=DEAL_ENTRY_OUT_BY) continue;
      sum += HistoryDealGetDouble(tk,DEAL_PROFIT)+HistoryDealGetDouble(tk,DEAL_SWAP)+HistoryDealGetDouble(tk,DEAL_COMMISSION);
     }
   return(sum);
  }

double FloatingProfit()
  {
   double sum=0.0;
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong tk=PositionGetTicket(i); if(tk==0) continue;
      if(!IsOrbitMagic(PositionGetInteger(POSITION_MAGIC))) continue;
      sum += PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
     }
   return(sum);
  }

// 新しく建ててよいか。isAdd=true はナンピン追加（同時保有数の上限は見ない）
bool SiteAllowsEntry(const bool isAdd, string &reason)
  {
   if(!IsTradingAllowedRaw()) { reason="サイトから停止中"; return(false); }
   double dayLimit = GateNumber("AI_DAY_LOSS_LIMIT", 0.0);
   if(dayLimit > 0.0 && TodayClosedProfit()+FloatingProfit() <= -dayLimit)
     { reason=StringFormat("本日の損失が上限(%.0f)に達した", dayLimit); return(false); }
   if(!isAdd)
     {
      double maxPos = GateNumber("AI_MAX_POSITIONS", 0.0);
      if(maxPos > 0.0 && CountOrbitPositions() >= (int)maxPos)
        { reason="同時保有数の上限"; return(false); }
     }
   reason=""; return(true);
  }

// 見送りの理由は変わったときだけログに出す（毎ティック出すと読めない）
void SiteSkipLog(const string who, const string reason)
  {
   static string last="";
   string line = who + ": " + reason;
   if(line == last) return;
   last = line;
   PrintFormat("[Orbit v5] 見送り %s", line);
  }

// サイトのチャートパネルに出す「エントリー回数・直近時刻」
void MarkSiteEntry()
  {
   GlobalVariableSet("AI_ENTRY_COUNT", GateNumber("AI_ENTRY_COUNT", 0.0) + 1.0);
   GlobalVariableSet("AI_LAST_ENTRY", (double)TimeCurrent());
  }

double CalcLot(const double slDistance)
  {
   double lot = SiteLot();
   if(InpLotMode==LOT_RISK && slDistance>0.0)
     {
      double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
      double tsz= SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tv>0.0 && tsz>0.0)
        {
         double lossPerLot = (slDistance/tsz)*tv;
         if(lossPerLot>0.0)
            lot = AccountInfoDouble(ACCOUNT_BALANCE)*InpRiskPercent/100.0/lossPerLot;
        }
     }
   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double mx=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double stp=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(stp>0.0) lot = MathFloor(lot/stp)*stp;
   lot = MathMin(lot, MathMin(mx, InpMaxLot));
   lot = MathMax(lot, mn);
   int dg = 2; if(stp>0.0) dg = (stp>=1.0) ? 0 : (int)MathRound(-MathLog10(stp));
   return(NormalizeDouble(lot, dg));
  }

double NormalizeLotValue(double lot)
  {
   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double mx=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double stp=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(stp>0.0) lot=MathFloor(lot/stp)*stp;
   lot=MathMin(lot,MathMin(mx,InpMaxLot)); lot=MathMax(lot,mn);
   int dg=2; if(stp>0.0) dg=(stp>=1.0)?0:(int)MathRound(-MathLog10(stp));
   return(NormalizeDouble(lot,dg));
  }

bool SpreadOK()
  {
   if(InpMaxSpreadUSD <= 0.0) return(true);
   double sp = SymbolInfoDouble(_Symbol,SYMBOL_ASK) - SymbolInfoDouble(_Symbol,SYMBOL_BID);
   return(sp <= InpMaxSpreadUSD);
  }

bool OpenTrade(SEngine &eng, const int dir, const double refEntry, const double refSL, const double refTP)
  {
   if(!g_symbolAllowed) return(false);
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
     { if(InpVerboseLog) PrintFormat("[%s] 見送り: 自動売買不許可", eng.name); return(false); }
   if(!SpreadOK())
     { if(InpVerboseLog) PrintFormat("[%s] 見送り: スプレッド超過 ($%.2f)", eng.name,
        SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID)); return(false); }

   int b,s;
   if(CountPositions(eng.magic,b,s) >= eng.maxPositions)
     { if(InpVerboseLog) PrintFormat("[%s] 見送り: 保有上限", eng.name); return(false); }

   string why;
   if(!SiteAllowsEntry(false, why)) { SiteSkipLog(eng.name, why); return(false); }

   //--- AIリスク監督（方向別）。損失上限・手動停止・スプレッドの次に見る
   string aiWhy=""; bool aiShadow=false;
   if(!AiAllowsEntry(dir, aiWhy, aiShadow))
     { AiCountSkip(dir, false); SiteSkipLog(eng.name, aiWhy); return(false); }
   if(aiWhy != "" && aiShadow)
     { AiCountSkip(dir, true); if(InpVerboseLog) PrintFormat("[%s] AI記録のみ: %s（発注は続行）", eng.name, aiWhy); }

   bool isBuy = (dir>0);
   int    dgt = (int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   double pt  = SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   double ask = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double price = isBuy ? ask : bid;
   if(price<=0.0) return(false);

   double useSL = refSL, useTP = refTP;
   if(eng.magic==InpM1Magic && InpM1NanpinEnabled)
     {
      // 全体SL = 初回 ± 値幅×(最大追加回数+1)、TP は当初のRR幅（後で平均取得基準に補正）
      double stepUsd = g_m1.atr*InpM1NanpinStepATR;
      useSL = refEntry - stepUsd*(InpM1NanpinMaxAdds+InpM1NanpinSLRoom)*dir;
      useTP = refEntry + MathAbs(refTP-refEntry)*dir;
     }
   double sl = NormalizeDouble(useSL,dgt), tp = NormalizeDouble(useTP,dgt);
   double minDist = (double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*pt;
   if(isBuy)
     { if(sl >= bid-minDist || tp <= ask+minDist)
        { if(InpVerboseLog) PrintFormat("[%s] 見送り: SL/TPがストップレベル内",eng.name); return(false); } }
   else
     { if(sl <= ask+minDist || tp >= bid-minDist)
        { if(InpVerboseLog) PrintFormat("[%s] 見送り: SL/TPがストップレベル内",eng.name); return(false); } }

   double lot = CalcLot(MathAbs(price-sl));
   //--- リスク%指定でナンピンを使う場合、バスケット全体の想定損失は
   //    単発の (最大追加回数+2)/2 倍になるためロットを割り戻す
   if(InpLotMode==LOT_RISK && eng.magic==InpM1Magic && InpM1NanpinEnabled)
      lot = NormalizeLotValue(lot / ((InpM1NanpinMaxAdds+2)/2.0));
   if(lot<=0.0) return(false);

   g_trade.SetExpertMagicNumber(eng.magic);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   string cm = "Orbit " + eng.name;
   bool ok = isBuy ? g_trade.Buy(lot,_Symbol,0.0,sl,tp,cm) : g_trade.Sell(lot,_Symbol,0.0,sl,tp,cm);

   if(ok && eng.magic==InpM1Magic)
     {
      GlobalVariableSet(GVN_FIRST, g_trade.ResultPrice());
      GlobalVariableSet(GVN_STEP,  g_m1.atr*InpM1NanpinStepATR);
      GlobalVariableSet(GVN_TPD,   MathAbs(refTP-refEntry));
     }
   if(ok) MarkSiteEntry();

   if(ok) PrintFormat("[%s] %s lot=%.2f price=%.*f SL=%.*f TP=%.*f (SL幅$%.2f)",
                      eng.name,(isBuy?"BUY":"SELL"),lot,dgt,price,dgt,sl,dgt,tp,MathAbs(refEntry-refSL));
   else   PrintFormat("[%s] 発注失敗 retcode=%d (%s)",eng.name,
                      g_trade.ResultRetcode(),g_trade.ResultRetcodeDescription());
   return(ok);
  }

//==================================================================
// M1軸 ナンピンバスケット管理（毎ティック）
//   ・不利方向へ 値幅 進むごとに等倍で追加（最大 InpM1NanpinMaxAdds 回）
//   ・全建玉の TP を「平均取得 ± 当初RR幅」に揃える
//   ・全建玉の SL を「初回 ∓ 値幅×(最大追加回数+1)」に揃える（バスケット全体の損切り）
//==================================================================
void ManageM1Basket()
  {
   ulong  tickets[];  ArrayResize(tickets,0);
   int    cnt=0, dir=0;
   double totVol=0.0, sumPV=0.0, firstPrice=0.0, firstVol=0.0, posSL=0.0;
   datetime firstTime=0;

   for(int i=PositionsTotal()-1; i>=0; i--)
     {
      ulong tk=PositionGetTicket(i); if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpM1Magic) continue;
      double v=PositionGetDouble(POSITION_VOLUME);
      double pr=PositionGetDouble(POSITION_PRICE_OPEN);
      datetime tm=(datetime)PositionGetInteger(POSITION_TIME);
      if(cnt==0 || tm<firstTime){ firstTime=tm; firstPrice=pr; firstVol=v; posSL=PositionGetDouble(POSITION_SL); }
      dir = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY)?1:-1;
      totVol+=v; sumPV+=pr*v; cnt++;
      int k=ArraySize(tickets); ArrayResize(tickets,k+1); tickets[k]=tk;
     }

   if(cnt==0)
     {
      if(GlobalVariableCheck(GVN_FIRST)) GlobalVariableDel(GVN_FIRST);
      if(GlobalVariableCheck(GVN_STEP))  GlobalVariableDel(GVN_STEP);
      if(GlobalVariableCheck(GVN_TPD))   GlobalVariableDel(GVN_TPD);
      if(GlobalVariableCheck(GVN_BEST))  GlobalVariableDel(GVN_BEST);
      return;
     }
   if(!GlobalVariableCheck(GVN_STEP) || !GlobalVariableCheck(GVN_TPD)) return;

   double step  = GlobalVariableGet(GVN_STEP);
   double tpd   = GlobalVariableGet(GVN_TPD);
   double first = GlobalVariableCheck(GVN_FIRST) ? GlobalVariableGet(GVN_FIRST) : firstPrice;
   if(step<=0.0 || tpd<=0.0 || totVol<=0.0) return;

   int    adds = cnt-1;
   double avg  = sumPV/totVol;
   double bid  = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask  = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   int    dgt  = (int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   double pt   = SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   double cur  = (dir>0) ? bid : ask;

   //--- ナンピン追加
   if(InpM1NanpinEnabled && adds < InpM1NanpinMaxAdds)
     {
      double nextAdd = first - step*(adds+1)*dir;
      bool hit = (dir>0) ? (bid<=nextAdd) : (ask>=nextAdd);
      string why="", aiWhy=""; bool aiShadow=false;
      bool aiOK = AiAllowsEntry(dir, aiWhy, aiShadow);
      if(hit && SpreadOK() && !aiOK)
        { AiCountSkip(dir, false); SiteSkipLog("M1軸 ナンピン", aiWhy); }   // 追加はしないが、SL/TP の管理は続ける
      else if(hit && SpreadOK() && !SiteAllowsEntry(true, why))
         SiteSkipLog("M1軸 ナンピン", why);        // 追加はしないが、SL/TP の管理は続ける
      else if(hit && SpreadOK())
        {
         if(aiWhy != "" && aiShadow)
           { AiCountSkip(dir, true); if(InpVerboseLog) PrintFormat("[M1軸 ナンピン] AI記録のみ: %s（追加は続行）", aiWhy); }
         // 等倍＝初回建玉と同じロット（途中でサイトのロットが変わっても崩さない）
         double baseLot = (firstVol>0.0) ? firstVol : SiteLot();
         double lot = NormalizeLotValue(baseLot*MathPow(InpM1NanpinLotMult,adds+1));
         g_trade.SetExpertMagicNumber(InpM1Magic);
         g_trade.SetDeviationInPoints(InpSlippagePoints);
         bool ok = (dir>0) ? g_trade.Buy(lot,_Symbol,0.0,0.0,0.0,StringFormat("Orbit M1軸 nanpin%d",adds+1))
                           : g_trade.Sell(lot,_Symbol,0.0,0.0,0.0,StringFormat("Orbit M1軸 nanpin%d",adds+1));
         if(ok)
           {
            if(GlobalVariableCheck(GVN_BEST)) GlobalVariableDel(GVN_BEST);  // 追加したらトレールをリセット
            MarkSiteEntry();
            if(InpVerboseLog) PrintFormat("[M1軸] ナンピン%d回目 lot=%.2f (平均%.*f)",adds+1,lot,dgt,avg);
           }
         return;
        }
     }

   //--- ベースSL / TP
   double gsl, tp;
   if(InpM1NanpinEnabled)
     {
      gsl = first - step*(InpM1NanpinMaxAdds+InpM1NanpinSLRoom)*dir;
      tp  = avg   + tpd*dir;
     }
   else
     {
      if(posSL<=0.0) return;     // 単発運用時は初回に張ったSLを基準にする
      gsl = posSL;
      tp  = avg + tpd*dir;
     }

   //--- トレール（含み益が TrailStart×step を超えたら最高値から TrailDist×step 下へ）
   if(InpM1TrailStartATR > 0.0)
     {
      double prof = (cur-avg)*dir;
      if(prof >= InpM1TrailStartATR*step)
        {
         double best = GlobalVariableCheck(GVN_BEST) ? GlobalVariableGet(GVN_BEST) : cur;
         if((dir>0 && cur>best) || (dir<0 && cur<best)) best=cur;
         GlobalVariableSet(GVN_BEST,best);
         double tsl = best - InpM1TrailDistATR*step*dir;
         if((dir>0 && tsl>gsl) || (dir<0 && tsl<gsl)) gsl=tsl;   // 有利方向にのみ移動
        }
     }

   //--- ストップレベル補正して全建玉に適用
   double minDist=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*pt;
   if(dir>0){ if(gsl>=bid-minDist) gsl=bid-minDist; if(tp<=ask+minDist) tp=ask+minDist; }
   else     { if(gsl<=ask+minDist) gsl=ask+minDist; if(tp>=bid-minDist) tp=bid-minDist; }
   gsl=NormalizeDouble(gsl,dgt); tp=NormalizeDouble(tp,dgt);

   double tol = pt*2.0;
   for(int i=0;i<ArraySize(tickets);i++)
     {
      if(!PositionSelectByTicket(tickets[i])) continue;
      double csl=PositionGetDouble(POSITION_SL), ctp=PositionGetDouble(POSITION_TP);
      if(MathAbs(csl-gsl)>tol || MathAbs(ctp-tp)>tol)
         g_trade.PositionModify(tickets[i],gsl,tp);
     }
  }

//==================================================================
// エンジン更新（新しい足の確定を検出して1本処理）
//==================================================================
void UpdateEngine(SEngine &eng)
  {
   if(!eng.warmed) return;
   datetime t = iTime(_Symbol, eng.tf, 0);
   if(t == eng.lastBarTime) return;
   eng.lastBarTime = t;

   eng.atr = (eng.atr*(InpAtrPeriod-1) + TrueRange(eng.tf,1)) / InpAtrPeriod;
   eng.barIndex++;

   double e,sl,tp;
   int dir = ProcessBar(eng, 1, e, sl, tp);
   if(dir != 0 && eng.enabled)
      OpenTrade(eng, dir, e, sl, tp);
  }

//==================================================================
// 標準イベント
//==================================================================
int OnInit()
  {
   string sym=_Symbol; StringToUpper(sym);
   g_symbolAllowed = (!InpRestrictToGold) || (StringFind(sym,"XAU")>=0) || (StringFind(sym,"GOLD")>=0);
   if(!g_symbolAllowed) Print("[Orbit v5] 警告: 対象外シンボルのため発注しません（XAUUSD のチャートに載せてください）");

   if(!InitEngine(g_m1, PERIOD_M1, "M1軸", InpM1Enabled, InpM1Magic, 1,
                  InpM1Cooldown, InpM1MaxSignals, InpM1SLatrMult, InpM1TPatrMult,
                  InpM1MinAtrUSD, InpM1RequireH1Align)) return(INIT_FAILED);
   // H1軸は「取引を無効」にしていても M1 のトレンドフィルター用に必ず動かす
   if(!InitEngine(g_h1, PERIOD_H1, "H1軸", InpH1Enabled, InpH1Magic, InpH1MaxPositions,
                  InpH1Cooldown, InpH1MaxSignals, InpH1AtrSLmult,
                  InpH1AtrSLmult*InpH1RR, 0.0, false)) return(INIT_FAILED);

   GVN_FIRST="OrbitV5_"+_Symbol+"_"+IntegerToString(InpM1Magic)+"_first";
   GVN_STEP ="OrbitV5_"+_Symbol+"_"+IntegerToString(InpM1Magic)+"_step";
   GVN_TPD  ="OrbitV5_"+_Symbol+"_"+IntegerToString(InpM1Magic)+"_tpd";
   GVN_BEST ="OrbitV5_"+_Symbol+"_"+IntegerToString(InpM1Magic)+"_best";

   g_trade.SetDeviationInPoints(InpSlippagePoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   // AIリスク監督へ渡す戦略プロフィール。ここが唯一の出どころで、
   // ブリッジは状態ファイル越しにこの値を読む（実際の設定と食い違わないようにする）
   GateProfile = StringFormat(
      "name:Orbit GOLD 2軸;entry:上位トレンド方向へ内部高値安値のブレイク後リテスト成立で入る;"
      "ema_period:%d;atr_period:%d;retest_tolerance_atr:%.3f;retest_bars:%d;"
      "m1_enabled:%d;m1_sl_atr_mult:%.2f;m1_tp_atr_mult:%.2f;m1_min_atr_usd:%.2f;m1_require_h1_align:%d;"
      "m1_cooldown_bars:%d;m1_max_signals:%d;"
      "m1_nanpin_enabled:%d;m1_nanpin_step_atr:%.2f;m1_nanpin_max_adds:%d;m1_nanpin_sl_room:%d;m1_nanpin_lot_mult:%.2f;"
      "m1_trail_start_atr:%.2f;m1_trail_dist_atr:%.2f;"
      "h1_enabled:%d;h1_sl_atr_mult:%.2f;h1_rr:%.2f;h1_max_positions:%d;h1_cooldown_bars:%d;h1_max_signals:%d;"
      "max_spread_usd:%.2f;lot_mode:%d",
      InpEmaPeriod, InpAtrPeriod, InpAtrMultiplier, InpRetestBars,
      (InpM1Enabled?1:0), InpM1SLatrMult, InpM1TPatrMult, InpM1MinAtrUSD, (InpM1RequireH1Align?1:0),
      InpM1Cooldown, InpM1MaxSignals,
      (InpM1NanpinEnabled?1:0), InpM1NanpinStepATR, InpM1NanpinMaxAdds, InpM1NanpinSLRoom, InpM1NanpinLotMult,
      InpM1TrailStartATR, InpM1TrailDistATR,
      (InpH1Enabled?1:0), InpH1AtrSLmult, InpH1RR, InpH1MaxPositions, InpH1Cooldown, InpH1MaxSignals,
      InpMaxSpreadUSD, (int)InpLotMode);

   // サイト連携: 1秒ごとに指令ファイルを読み、チャートのパネルと状態ファイルを更新する
   EventSetMillisecondTimer(1000);
   SyncGateFileToGlobals();

   PrintFormat("[Orbit v5] 初期化 %s / M1軸=%s H1軸=%s / サイト指令=%s ロット=%.2f",
               _Symbol, (InpM1Enabled?"ON":"OFF"), (InpH1Enabled?"ON":"OFF"),
               (IsTradingAllowedRaw()?"稼働":"停止"), SiteLot());
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   RemoveGateStatus();
   if(g_m1.emaHandle!=INVALID_HANDLE) IndicatorRelease(g_m1.emaHandle);
   if(g_h1.emaHandle!=INVALID_HANDLE) IndicatorRelease(g_h1.emaHandle);
   Comment("");
  }

void OnTimer()
  {
   // ティックが来ない週末や休場でも、サイトへ「生きている」ことを伝え続ける
   SyncGateFileToGlobals();
  }

void OnTick()
  {
   // ★順序が重要: M1 を先に処理する。
   //   毎正時は M1 と H1 が同時に確定するが、バックテストと同じく
   //   「1本前の確定H1トレンド」を参照させるため M1→H1 の順にする。
   //--- ウォームアップは H1 が先（M1のH1一致フィルタが参照するため）
   if(!g_h1.warmed) { WarmUpEngine(g_h1); return; }
   if(!g_m1.warmed) { WarmUpEngine(g_m1); return; }

   ManageM1Basket();      // 既存バスケットの追加・SL/TP調整が先
   UpdateEngine(g_m1);
   UpdateEngine(g_h1);
   UpdateComment();
  }

string TrendTxt(const int d){ return(d>0?"UP":(d<0?"DOWN":"----")); }

void UpdateComment()
  {
   static datetime last=0;
   if(TimeCurrent()==last) return;
   last=TimeCurrent();
   int mb,ms,hb,hs;
   CountPositions(InpM1Magic,mb,ms); CountPositions(InpH1Magic,hb,hs);
   // 先頭の空行は、サイト連携パネル（左上）と重ならないようにするため
   Comment(StringFormat(
     "\n\n\n\n\n\n\n\n\n\n\n\n"
     "Orbit GOLD EA v5  [%s]\n"
     "スプレッド: $%.2f (上限 $%.2f)\n"
     "── M1軸 %s ──\n"
     "  トレンド:%s  ATR:$%.2f (下限$%.2f)  ナンピン:%s\n"
     "  サイン:%d/%d  待機:B%s/S%s  保有:%d (ナンピン%d/%d回)\n"
     "── H1軸 %s ──\n"
     "  トレンド:%s  ATR:$%.2f  サイン:%d/%d  保有:%d",
     _Symbol,
     SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID), InpMaxSpreadUSD,
     (InpM1Enabled?"ON":"OFF"),
     TrendTxt(g_m1.st.currentTrendDir), g_m1.atr, InpM1MinAtrUSD,
     (InpM1NanpinEnabled?StringFormat("%d回/余裕%d/トレール%.1f-%.1f",InpM1NanpinMaxAdds,InpM1NanpinSLRoom,InpM1TrailStartATR,InpM1TrailDistATR):"OFF"),
     g_m1.st.trendSignalCount, InpM1MaxSignals,
     (g_m1.st.waitingRetestBuy?"○":"×"), (g_m1.st.waitingRetestSell?"○":"×"), mb+ms,
     MathMax(mb+ms-1,0), InpM1NanpinMaxAdds,
     (InpH1Enabled?"ON":"OFF"),
     TrendTxt(g_h1.st.currentTrendDir), g_h1.atr, g_h1.st.trendSignalCount, InpH1MaxSignals, hb+hs));
  }
//+------------------------------------------------------------------+
