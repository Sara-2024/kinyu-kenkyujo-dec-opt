"""口座の履歴が、取りこぼしなくサイトへ出るかを確かめる。

MT5 は要らない。約定（deal）の身代わりを並べて、集計と組み直しだけを見る。

ここで捕まえたい抜け:
  1. ドテン（DEAL_ENTRY_INOUT）の損益が数えられず、成績に出ない
  2. 窓より前に建てて窓の中で決済した取引が、まるごと消える
  3. サーバー時計との差が粗いせいで、たったいまの決済が窓から外れる

実行: python3 bridge/tests/history_test.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time
import types

BRIDGE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE))

# 覚え書き（clock.json）をリポジトリに書かせない
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="aitrader-test-")

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  NG   {name} {extra}")


# ── 約定の身代わり ────────────────────────────────────────────
DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1
DEAL_TYPE_BALANCE = 2
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_ENTRY_OUT_BY = 3


class Deal:
    def __init__(
        self,
        *,
        time: int,
        type: int,  # noqa: A002
        entry: int,
        position_id: int,
        volume: float = 0.1,
        price: float = 3000.0,
        profit: float = 0.0,
        swap: float = 0.0,
        commission: float = 0.0,
        symbol: str = "XAUUSD",
        magic: int = 0,
    ) -> None:
        self.time = time
        self.type = type
        self.entry = entry
        self.position_id = position_id
        self.volume = volume
        self.price = price
        self.profit = profit
        self.swap = swap
        self.commission = commission
        self.symbol = symbol
        self.magic = magic


DEALS: list[Deal] = []
# 建玉番号で名指しに取れるぶん（窓の外の約定はこちらにだけ入れる）
BY_POSITION: dict[int, list[Deal]] = {}


def _history_deals_get(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
    if "position" in kwargs:
        return tuple(BY_POSITION.get(int(kwargs["position"]), ()))
    if not args:
        return tuple(DEALS)
    start, end = args[0], args[1]
    out = []
    for d in DEALS:
        when = _dt(d.time)
        if start <= when <= end:
            out.append(d)
    return tuple(out)


def _stub(name: str, **attrs: object) -> None:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod


def _connect(*_a, **_k):  # noqa: ANN202
    raise RuntimeError("接続しない")


_stub("websockets", exceptions=types.SimpleNamespace(WebSocketException=Exception))
_stub("websockets.exceptions", WebSocketException=Exception)
_stub("websockets.asyncio", client=types.SimpleNamespace(connect=_connect))
_stub("websockets.asyncio.client", connect=_connect)
_stub(
    "MetaTrader5",
    initialize=lambda *a, **k: False,
    shutdown=lambda: None,
    terminal_info=lambda: None,
    account_info=lambda: None,
    history_deals_get=_history_deals_get,
    positions_get=lambda *a, **k: (),
    symbol_info=lambda *a, **k: types.SimpleNamespace(digits=2, visible=True),
    symbol_info_tick=lambda *a, **k: None,
    symbol_select=lambda *a, **k: True,
    DEAL_TYPE_BUY=DEAL_TYPE_BUY,
    DEAL_TYPE_SELL=DEAL_TYPE_SELL,
    DEAL_TYPE_BALANCE=DEAL_TYPE_BALANCE,
    DEAL_ENTRY_IN=DEAL_ENTRY_IN,
    DEAL_ENTRY_OUT=DEAL_ENTRY_OUT,
    DEAL_ENTRY_INOUT=DEAL_ENTRY_INOUT,
    DEAL_ENTRY_OUT_BY=DEAL_ENTRY_OUT_BY,
    TIMEFRAME_M1=1,
    TIMEFRAME_H1=16385,
    TIMEFRAME_H4=16388,
    TIMEFRAME_D1=16408,
    TIMEFRAME_W1=32769,
    ACCOUNT_TRADE_MODE_DEMO=0,
    ACCOUNT_TRADE_MODE_CONTEST=1,
    ACCOUNT_TRADE_MODE_REAL=2,
)

import bridge as bridge_mod  # noqa: E402

_dt = bridge_mod.MT5Controller._server_dt

mt = bridge_mod.MT5Controller(bridge_mod.Config())
mt.ready = True
# サーバー時計＝UTC として固定する（時差の割り出しには行かせない）
mt._server_offset = 0
mt._server_offset_at = time.time()

NOW = int(time.time())
HOUR = 3600
DAY = 86400
# サーバー時計＝UTC に固定してあるので、今日の始まりは UTC の 0時
TODAY_START = NOW - NOW % DAY
# 「今日のうち」に置く時刻。日付が変わった直後でも前日に落ちないようにする
T_IN = max(TODAY_START + 1, NOW - 120)
T_OUT = max(TODAY_START + 2, NOW - 60)


def reset() -> None:
    DEALS.clear()
    BY_POSITION.clear()


# ── 1) ふつうの1往復が、そのまま出る ──────────────────────────
reset()
DEALS += [
    Deal(time=T_IN, type=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, position_id=1, price=3000.0),
    Deal(time=T_OUT, type=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, position_id=1, price=3010.0, profit=1000.0),
]
today = mt._today_stats_blocking()
check("ふつうの決済が今日の成績に出る", today["today_closed"] == 1 and today["today_profit"] == 1000.0, str(today))
trades = mt._trades_blocking(days=30)
check("ふつうの決済が取引一覧に出る", trades["total"] == 1, str(trades["total"]))
check("向きと建値が入る", trades["trades"][0]["side"] == "buy" and trades["trades"][0]["open_price"] == 3000.0)

# ── 2) ドテン（INOUT）の損益が消えない ───────────────────────
reset()
DEALS += [
    Deal(time=T_IN, type=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, position_id=2, price=3000.0),
    # 決済して、その場で売りに入る1件。確定損益はここに載る
    Deal(time=T_OUT, type=DEAL_TYPE_SELL, entry=DEAL_ENTRY_INOUT, position_id=2, price=2990.0, profit=-500.0),
]
today = mt._today_stats_blocking()
check("ドテンの損益が今日の成績に入る", today["today_closed"] == 1 and today["today_profit"] == -500.0, str(today))
hist = mt._history_stats_blocking(days=30)
check("ドテンの損益が過去の成績に入る", hist["closed"] == 1 and hist["profit"] == -500.0, str(hist))
trades = mt._trades_blocking(days=30)
check("ドテンが取引一覧に出る", trades["total"] == 1 and trades["trades"][0]["profit"] == -500.0, str(trades))

# ── 3) 窓より前に建てて、窓の中で決済した取引 ─────────────────
reset()
old_in = Deal(time=NOW - 200 * DAY, type=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, position_id=3, price=2500.0)
BY_POSITION[3] = [old_in]
DEALS += [
    old_in,  # 200日前。30日窓には入らない
    Deal(time=T_OUT, type=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, position_id=3, price=3000.0, profit=50000.0),
]
trades = mt._trades_blocking(days=30)
check("長く持った取引が消えない", trades["total"] == 1, str(trades["total"]))
if trades["total"] == 1:
    t = trades["trades"][0]
    check("その損益が載る", t["profit"] == 50000.0, str(t["profit"]))
    check("建値も拾える", t["open_price"] == 2500.0, str(t["open_price"]))
    check("向きは買い", t["side"] == "buy", t["side"])
hist = mt._history_stats_blocking(days=30)
check("過去の成績にも入る", hist["closed"] == 1 and hist["profit"] == 50000.0, str(hist))

# ── 4) 建てた側がどうしても取れなくても、損益は消さない ────────
reset()
DEALS += [
    Deal(time=T_OUT, type=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, position_id=4, price=3000.0, profit=1234.0),
]
trades = mt._trades_blocking(days=30)
check("建玉の記録が無くても取引は残る", trades["total"] == 1, str(trades["total"]))
if trades["total"] == 1:
    t = trades["trades"][0]
    check("損益は載る", t["profit"] == 1234.0, str(t["profit"]))
    check("建値は空（作らない）", t["open_price"] == 0.0 and t["opened_at"] == "", str(t))
    check("向きは決済から起こす", t["side"] == "buy", t["side"])

# ── 5) サーバー時計が少し遅れていても、直前の決済が落ちない ────
reset()
# 時計の差を割り出せず 0 のまま＝サーバーが UTC+2 なら、いまは 2時間先まで進んでいる
DEALS += [
    Deal(time=T_IN, type=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, position_id=5, price=3000.0),
    Deal(time=NOW + 2 * HOUR, type=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, position_id=5, price=3010.0, profit=700.0),
]
today = mt._today_stats_blocking()
check("時計がずれていても直前の決済が出る", today["today_closed"] == 1 and today["today_profit"] == 700.0, str(today))
trades = mt._trades_blocking(days=30)
check("取引一覧にも出る", trades["total"] == 1, str(trades["total"]))

# ── 6) 入出金は取引として数えない ────────────────────────────
reset()
DEALS += [
    Deal(time=T_OUT, type=DEAL_TYPE_BALANCE, entry=DEAL_ENTRY_IN, position_id=0, profit=100000.0),
]
today = mt._today_stats_blocking()
check("入金は成績に入らない", today["today_closed"] == 0 and today["today_profit"] == 0.0, str(today))

# ── 7) まだ決済していない建玉は取引一覧に出さない ───────────────
reset()
DEALS += [
    Deal(time=T_IN, type=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, position_id=7, price=3000.0),
]
trades = mt._trades_blocking(days=30)
check("持ったままの建玉は出さない", trades["total"] == 0, str(trades["total"]))

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
