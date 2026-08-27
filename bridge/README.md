# トレラボ ⇔ MT5 ブリッジ

トレラボ（Webアプリ）からの指令を WebSocket で待ち受け、MT5 の
**ターミナル・グローバル変数**を書き換えて EA の売買可否を制御する常駐スクリプト。

```
トレラボ  ──WebSocket(常時接続)──▶  bridge.py  ──▶  MT5 グローバル変数
                                                        │
                                              EA が毎Tick読んで判断
```

HTTPポーリングを一切しないため、待機中の CPU 使用率はほぼ 0%
（実測: 25秒間のアイドルでCPU時間の増加 0.00 秒）。

---

## 1. インストール（Windows VPS）

64bit の Python 3.9 以上が必要（MetaTrader5 パッケージは Windows 64bit 専用）。

```bat
cd C:\trelab\bridge
py -3 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt`

```
MetaTrader5>=5.0.45
websockets>=12.0
python-dotenv>=1.0.1
```

## 2. 設定

`.env.example` を `.env` にコピーして書き換える。最低限必要なのは接続先だけ。

```
TRELAB_WS_URL=wss://api.trelab.example.com/bridge
TRELAB_TOKEN=（ブリッジ用トークン）
BRIDGE_ID=vps-01
GV_NAME=AI_TRADING_ALLOWED
```

| 変数 | 既定値 | 説明 |
| --- | --- | --- |
| `TRELAB_WS_URL` | `ws://127.0.0.1:8080/bridge` | 接続先。本番は必ず `wss://` |
| `TRELAB_TOKEN` | （空） | `Authorization: Bearer …` で送る |
| `BRIDGE_ID` | `vps-01` | 複数VPSを見分ける名前 |
| `MT5_PATH` | （空） | 起動中のターミナルに繋ぐだけなら空でよい |
| `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | （空） | 指定するとログインまで行う |
| `GV_NAME` | `AI_TRADING_ALLOWED` | EA が読むグローバル変数名 |
| `GV_DEFAULT` | `1` | 起動直後の値 |
| `RECONNECT_MIN_SEC` / `RECONNECT_MAX_SEC` | `3` / `60` | 再接続の指数バックオフ |
| `PING_INTERVAL_SEC` / `PING_TIMEOUT_SEC` | `20` / `20` | 死んだ回線の検知 |
| `WATCHDOG_INTERVAL_SEC` | `30` | 見張りの間隔 |
| `REASSERT_STATE` | `true` | 値がズレていたら指示どおりに書き戻す |
| `FAILSAFE_DISCONNECT_SEC` | `0`（無効） | **デッドマンスイッチ**。この秒数だけ切断が続いたら自動で売買停止 |
| `LOG_LEVEL` / `LOG_FILE` | `INFO` / （空） | ログ |

## 3. 動作確認 → 常駐

```bat
python bridge.py --check     :: MT5に繋がるか・現在値の確認だけ
python bridge.py             :: 常駐開始
```

VPSで落ちないように常駐させるなら `run.bat`（異常終了しても5秒後に再起動）を
タスクスケジューラの「コンピューターの起動時」に登録する。
サービス化したい場合は [NSSM](https://nssm.cc/) で `python.exe bridge.py` を登録。

## 4. 通信仕様

サーバー → ブリッジ（指令）

```jsonc
{"command": "stop_trading",  "id": "任意", "reason": "指標発表前"}
{"command": "start_trading", "id": "任意"}
{"command": "set_variable",  "id": "任意", "name": "AI_RISK_PCT", "value": 0.5}
{"command": "get_status",    "id": "任意"}
{"command": "ping"}
```

ブリッジ → サーバー（接続直後の名乗り）

```jsonc
{"type":"hello","bridge_id":"vps-01","account":12345678,"server":"XM-Real",
 "balance":1000000.0,"equity":1002345.0,"variable":"AI_TRADING_ALLOWED","value":1.0,
 "terminal_connected":true,"terminal_trade_allowed":true}
```

ブリッジ → サーバー（指令ごとの応答。`value` は書き込み後の**読み戻し値**）

```jsonc
{"type":"ack","bridge_id":"vps-01","id":"任意","command":"stop_trading","ok":true,"value":0.0}
```

## 5. MT5側（EA）

同梱の `TradingGate.mqh` を EA から読み込み、`OnTick()` の先頭で判定する。

```mql5
#include <TradingGate.mqh>

void OnTick()
  {
   if(!IsTradingAllowed())
      return;              // 新規エントリーを見送る
   // …通常のロジック
  }
```

`IsTradingAllowed()` はグローバル変数に加え、ターミナル側の
自動売買スイッチ（`TERMINAL_TRADE_ALLOWED`）も見る。
変数が存在しない場合の扱いは `InpAllowWhenMissing` で決める（既定は「停止」）。

## 6. 安全に関する設計

* **読み戻し確認** — 書き込み後に必ず読み直し、その値を ack で返す。
* **状態の復元** — 再接続時・MT5再初期化時に、最後に指示された状態を書き戻す。
* **ズレの自動補正** — 30秒ごとに値を点検し、指示と違えば書き戻す（`REASSERT_STATE`）。
* **デッドマンスイッチ** — サーバーと長時間つながらない＝停止指令が届かない状態。
  `FAILSAFE_DISCONNECT_SEC=120` などを設定すると自動で売買を止める。**本番では有効化を推奨**。
* **単一スレッド** — MetaTrader5 のブロッキングAPIは専用スレッド1本に隔離し、
  イベントループを止めない。`time.sleep()` は一切使っていない。

## 7. 注意

* ブリッジが止まっても EA は最後に書かれた値で動き続ける。停止を担保したいなら
  デッドマンスイッチを必ず有効にすること。
* グローバル変数はターミナル単位。複数ターミナルを制御するなら各々にブリッジを常駐させ、
  `BRIDGE_ID` で区別する。
* `TRELAB_TOKEN` は `.env` に置き、リポジトリに含めないこと。
