"""金の銘柄をどう選ぶかを、業者ごとの並びを作って確かめる。

XAUEUR / XAUJPY を掴むと、EA が売買している商品と別の値を AI に見せてしまう。
逆に絞りすぎると（XM の GOLD は基準通貨も USD）、金そのものを弾いてしまう。
どちらの失敗も一度ずつ起きているので、ここで両方を止める。
実行: python3 bridge/tests/symbol_test.py
"""
from __future__ import annotations

import pathlib
import sys
import types

BRIDGE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE))

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


def _stub(name: str, **attrs: object) -> None:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod


def _noconnect(*_a, **_k):  # noqa: ANN202
    raise RuntimeError("接続しない")


_stub("websockets", exceptions=types.SimpleNamespace(WebSocketException=Exception))
_stub("websockets.exceptions", WebSocketException=Exception)
_stub("websockets.asyncio", client=types.SimpleNamespace(connect=_noconnect))
_stub("websockets.asyncio.client", connect=_noconnect)
_stub("MetaTrader5", initialize=lambda *a, **k: False, shutdown=lambda: None)

import bridge as bridge_mod  # noqa: E402


class Sym:
    def __init__(self, name: str, base: str, profit: str) -> None:
        self.name = name
        self.currency_base = base
        self.currency_profit = profit


def install(symbols: list[Sym], *, no_tick: tuple[str, ...] = ()) -> None:
    """MT5 の銘柄一覧を差し替える。"""
    table = {s.name: s for s in symbols}

    def symbols_get(pattern: str = ""):
        core = pattern.strip("*").upper()
        return [s for s in symbols if core in s.name.upper()]

    bridge_mod.mt5.symbols_get = symbols_get  # type: ignore[attr-defined]
    bridge_mod.mt5.symbol_info = lambda name: table.get(name)  # type: ignore[attr-defined]
    bridge_mod.mt5.symbol_info_tick = lambda name: None if name in no_tick else object()  # type: ignore[attr-defined]
    bridge_mod.mt5.positions_get = lambda: ()  # type: ignore[attr-defined]


mt = bridge_mod.MT5Controller(bridge_mod.Config())
mt._ea_state_blocking = lambda: {}  # type: ignore[method-assign]  EA からの手がかりは無いことにする

# ① XM のような口座（金は GOLD で、基準通貨も USD）
install([
    Sym("GOLD", "USD", "USD"),
    Sym("XAUEUR", "EUR", "EUR"),
    Sym("XAUJPY", "JPY", "JPY"),
    Sym("XAUCNH", "CNH", "CNH"),
])
check("GOLD の口座で GOLD を選ぶ", mt._pick_symbol_blocking("") == "GOLD", mt._pick_symbol_blocking(""))

# ② XAUUSD がある口座
install([Sym("XAUUSD", "XAU", "USD"), Sym("XAUEUR", "XAU", "EUR"), Sym("GOLD.spot", "XAU", "USD")])
check("XAUUSD がある口座では XAUUSD", mt._pick_symbol_blocking("") == "XAUUSD", mt._pick_symbol_blocking(""))

# ③ 接尾辞つき（XAUUSDm など）
install([Sym("XAUUSDm", "XAU", "USD"), Sym("XAUJPY", "XAU", "JPY")])
check("接尾辞つきでも選べる", mt._pick_symbol_blocking("") == "XAUUSDm", mt._pick_symbol_blocking(""))

# ④ ドル建て以外しか無い口座では、金でないものを掴まない
install([Sym("XAUEUR", "XAU", "EUR"), Sym("XAUJPY", "XAU", "JPY")])
picked = mt._pick_symbol_blocking("")
check("ドル建てが無ければ XAUEUR を掴まない", picked not in ("XAUEUR", "XAUJPY"), picked)

# ⑤ 値が取れない銘柄は避ける
install([Sym("XAUUSD", "XAU", "USD"), Sym("GOLD", "USD", "USD")], no_tick=("XAUUSD",))
check("値が取れない銘柄は避ける", mt._pick_symbol_blocking("") == "GOLD", mt._pick_symbol_blocking(""))

# ⑥ 指定があればそれを最優先（RISK_SYMBOL）
check("指定した銘柄をそのまま使う", mt._pick_symbol_blocking("GOLD#") == "GOLD#")

# ⑦ EA が書き出した銘柄があれば、それを最優先
mt._ea_state_blocking = lambda: {"ea_symbol": "GOLD.raw"}  # type: ignore[method-assign]
check("EA が使っている銘柄を最優先", mt._pick_symbol_blocking("") == "GOLD.raw")

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
