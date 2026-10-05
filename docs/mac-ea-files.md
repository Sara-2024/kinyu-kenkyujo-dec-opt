# Mac ルート：EA とツールのあいだのファイル（EA を作る人向けの仕様）

Windows では MT5 Automatic が MetaQuotes の Python 部品で MT5 を直接読みますが、
Mac 版 MT5（Wine 上で動く公式アプリ）にはその部品がありません。
そこで Mac では **EA が自分でファイルに書き出し、ツールがそれを読む** 形にします。
サイト・中継・一斉制御は Windows と同じです。

- 置き場は MT5 の **共通フォルダ**（`FILE_COMMON`）。`TradingGate.mqh` がいま `trelab_state.ini` を
  書いているのと同じ場所です。
- 文字コードは `FILE_ANSI`（UTF-8 でも可）。1行 1レコード、`key=value` を `;` でつなぐ。
- **追記はしない。毎回まるごと上書き**する（ファイルは大きくならない）。
- 数値は小数点 `.`、時刻は UNIX 秒（`(long)TimeTradeServer()` など）。
- ファイルを書くときは `FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE`。

## 1. EA が書く（ツールが読む）

### `trelab_state.ini` — すでにある（変更なし）

`TradingGate.mqh` の `WriteStateFile()` が 10 秒ごとに書いているもの。そのまま。

### `trelab_account.ini` — 口座と端末（5〜10 秒ごと）

```
login=75613879
server=XMTrading-MT5 3
company=Trading Point of Financial Instruments Ltd
currency=JPY
balance=1000000.00
equity=1001234.56
margin_free=990000.00
trade_mode=0
terminal_connected=1
terminal_trade_allowed=1
build=4620
terminal_name=MetaTrader 5
server_time=1759700000
symbol=GOLD
bid=2650.12
ask=2650.42
digits=2
point=0.01
filling=1
at=1759700000
```

| 項目 | 取り方（MQL5） |
| --- | --- |
| `login` / `server` / `company` / `currency` | `AccountInfoInteger(ACCOUNT_LOGIN)`, `AccountInfoString(ACCOUNT_SERVER / ACCOUNT_COMPANY / ACCOUNT_CURRENCY)` |
| `balance` / `equity` / `margin_free` | `AccountInfoDouble(ACCOUNT_BALANCE / ACCOUNT_EQUITY / ACCOUNT_MARGIN_FREE)` |
| `trade_mode` | `AccountInfoInteger(ACCOUNT_TRADE_MODE)`（0=デモ 1=コンテスト 2=本番） |
| `terminal_connected` / `terminal_trade_allowed` | `TerminalInfoInteger(TERMINAL_CONNECTED / TERMINAL_TRADE_ALLOWED)` |
| `build` / `terminal_name` | `TerminalInfoInteger(TERMINAL_BUILD)`, `TerminalInfoString(TERMINAL_NAME)` |
| `server_time` | `(long)TimeTradeServer()` |
| `symbol` / `bid` / `ask` / `digits` / `point` | `_Symbol`, `SymbolInfoDouble(_Symbol, SYMBOL_BID / SYMBOL_ASK)`, `_Digits`, `_Point` |
| `filling` | `SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE)` |
| `at` | `(long)TimeLocal()`（鮮度の判定に使う。60 秒以上古いと「止まっている」扱い） |

### `trelab_positions.ini` — 建玉（変わったとき＋10 秒ごと）

1 行目が見出し、2 行目から 1 建玉 1 行。建玉が無ければ見出しだけ。

```
count=2;at=1759700000
ticket=123456;symbol=GOLD;type=0;volume=0.10;price_open=2640.00;price_current=2650.12;sl=2630.00;tp=2670.00;profit=1012.00;swap=-12.00;magic=20240101;time=1759690000;comment=Yumekku M1
ticket=123457;symbol=GOLD;type=1;volume=0.10;price_open=2660.00;price_current=2650.42;sl=0;tp=0;profit=958.00;swap=0;magic=20240102;time=1759695000;comment=
```

`type` は `POSITION_TYPE_BUY=0` / `POSITION_TYPE_SELL=1`。`PositionGetTicket(i)` で回して
`PositionGetInteger / PositionGetDouble / PositionGetString` から取る。**手動の建玉も含める**（magic で絞らない）。

### `trelab_orders.ini` — 待機注文（変わったとき＋10 秒ごと）

```
count=1;at=1759700000
ticket=223344;symbol=GOLD;type=2;volume=0.10;price=2600.00;sl=0;tp=0;magic=20240101;time=1759690000;comment=
```

`type` は `ORDER_TYPE_*`（2=BUY_LIMIT 3=SELL_LIMIT 4=BUY_STOP 5=SELL_STOP …）。

### `trelab_deals.ini` — 取引履歴（**頼まれたときだけ**）

ツールが `trelab_request.ini` に書いた依頼に応えて書く（下記 2.2）。見出しに依頼の `id` を入れる。

```
request=17597001234;count=3;from=1744100000;to=1759700000
ticket=5551;order=7771;position=123450;entry=0;type=0;volume=0.10;price=2600.00;profit=0;commission=-0.5;swap=0;fee=0;time=1759600000;symbol=GOLD;magic=20240101;comment=
ticket=5552;order=7772;position=123450;entry=1;type=1;volume=0.10;price=2610.00;profit=1000.00;commission=-0.5;swap=-3.00;fee=0;time=1759650000;symbol=GOLD;magic=20240101;comment=
ticket=5553;order=7773;position=123451;entry=2;type=1;volume=0.20;price=2615.00;profit=500.00;commission=-1.0;swap=0;fee=0;time=1759660000;symbol=GOLD;magic=20240101;comment=
```

- `entry` は `DEAL_ENTRY_IN=0` / `OUT=1` / `INOUT=2` / `OUT_BY=3`。**INOUT（ドテン）も必ず入れる**（損益がここに載る）。
- `HistorySelect(from, to)` → `HistoryDealsTotal()` / `HistoryDealGetTicket(i)` で回す。
- 依頼が `position=` のときは `HistorySelectByPosition(position)` で、その建玉のぶんだけ。
- 残高入出金（`DEAL_TYPE_BALANCE` など）は入れなくてよい。

### `trelab_rates_<SYMBOL>_<TF>.ini` — ローソク足（任意。頼まれたときだけ）

AI の見張り（新規注文の監督）に使う。**無くても連携・停止・決済はすべて動く**ので、あとからでよい。

```
request=17597001235;symbol=GOLD;tf=M1;count=300
time=1759699940;open=2650.0;high=2650.5;low=2649.8;close=2650.1;tick_volume=120
...
```

新しい足が最後の行。`CopyRates(symbol, tf, 0, count, rates)` で取れる。

### `trelab_cmd_ack.ini` — 指令の返事

ツールが `trelab_cmd.ini` に書いた指令（下記 2.3）を実行したら書く。

```
id=17597001236;ok=1;retcode=10009;deal=5560;comment=done
```

`retcode` は `MqlTradeResult.retcode`（成功は 10009 `TRADE_RETCODE_DONE`、取消は 10008 でも可）。
失敗したときは `ok=0` と `retcode`・`comment` を入れる。

## 2. ツールが書く（EA が読む）

### 2.1 `trelab_gate.ini` — すでにある（変更なし）

`SyncGateFileToGlobals()` がいま読んでいるもの。稼働／停止・ロット・AI の判定はここ。

### 2.2 `trelab_request.ini` — 「書いてほしい」の依頼

```
id=17597001234;kind=deals;from=1744100000;to=1759700000
```
```
id=17597001237;kind=deals;position=123450
```
```
id=17597001235;kind=rates;symbol=GOLD;tf=M1;count=300
```

- `OnTimer`（1 秒ごと）で読む。書き出しが終わったら **このファイルを消す**（`FileDelete(..., FILE_COMMON)`）。
- 同じ `id` の依頼は一度だけ処理すればよい。ツールは 20 秒待って、結果が無ければあきらめる。

### 2.3 `trelab_cmd.ini` — 指令

```
id=17597001236;cmd=close;position=123456
```
```
id=17597001238;cmd=remove;order=223344
```

- `close` … その建玉を**全量**成行で閉じる（`PositionClose` 相当。`ORDER_FILLING` は `trelab_account.ini` の `filling` から
  ツールが選ばず、EA 側で口座に合うものを使ってよい）。
- `remove` … その待機注文を取り消す（`OrderDelete` 相当）。
- 実行したら `trelab_cmd_ack.ini` を書いて、**このファイルを消す**。
- 一斉制御の「全決済」は、ツールが建玉と待機注文の分だけ `close` / `remove` を**順に**送る。
  1 件ずつ返事を待つので、EA は 1 つ処理したら次を読むだけでよい。
- `close` は **magic を見ずに**実行する（手動の建玉も「全決済」の対象）。

## 3. 書く頻度と鮮度

| ファイル | 書くタイミング |
| --- | --- |
| `trelab_state.ini` | 10 秒ごと（今のまま） |
| `trelab_account.ini` | 5〜10 秒ごと |
| `trelab_positions.ini` / `trelab_orders.ini` | 変わったとき（`OnTradeTransaction`）＋ 10 秒ごと |
| `trelab_deals.ini` / `trelab_rates_*.ini` | 依頼があったときだけ |
| `trelab_cmd_ack.ini` | 指令を実行したとき |

ツールは `trelab_account.ini` の `at` が **60 秒以上古ければ「EA が止まっている」**とみなし、
サイトには「チャートに載せてください」と出します。

## 4. 確認のしかた（EA の人が手元で）

1. Mac 版 MT5 で EA をゴールドのチャートに載せる
2. `Finder` → `移動` → `フォルダへ移動` に `~/Library/Application Support` を入れ、
   `net.metaquotes.wine.metatrader5`（業者版は別名）→ `drive_c/users/<ユーザー>/AppData/Roaming/MetaQuotes/Terminal/Common/Files`
3. `trelab_account.ini` と `trelab_positions.ini` が 10 秒ごとに更新されていれば OK
4. そこに `trelab_cmd.ini` を手で置く（`id=1;cmd=close;position=<建玉番号>`）→ 建玉が閉じ、
   `trelab_cmd_ack.ini` ができて `trelab_cmd.ini` が消えれば OK

ツール側の読み手は `bridge/mt5_files.py`。この仕様とずれていないかは
`python3 bridge/tests/mt5_files_test.py` が見ています。
