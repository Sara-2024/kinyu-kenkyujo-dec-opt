"""金の銘柄を選んで、MT5 の「気配値表示」に出しておく。

EA をチャートに載せるとき、気配値にゴールドが無いと、お客様は
「銘柄一覧を開いて → 探して → 右クリックで表示」までやることになる。
置いたついでに出しておけば、そのままチャートにドラッグできる。

銘柄の選び方は bridge.py と同じ考え方。業者によって名前が違う
（XAUUSD / GOLD / GOLD# など）ので、名前だけで選ばず、
ドル建ての金だけを採る（XAUEUR や XAUJPY を拾わない）。

MT5 が起動していない／ログインしていないときは、何もしないで終わる。
Phase 1（EA を置くだけ）でも呼べるよう、失敗しても先へ進める作りにする。
"""
from __future__ import annotations

from typing import Any, Callable

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - MT5 が無い環境
    mt5 = None  # type: ignore[assignment]


def is_gold_usd(name: str) -> bool:
    """ドル建ての金かどうか。XAUEUR / XAUJPY を除くために通貨で確かめる。"""
    if mt5 is None:
        return False
    try:
        info = mt5.symbol_info(name)
    except Exception:  # noqa: BLE001
        return False
    if info is None:
        return False
    profit = str(getattr(info, "currency_profit", "") or "").upper()
    base = str(getattr(info, "currency_base", "") or "").upper()
    if profit and profit != "USD":
        return False
    # 基準通貨は業者によって書き方が違う（XM の GOLD は base も USD）
    if not profit and base and base not in ("XAU", "GOLD", "USD"):
        return False
    return True


def find_gold(log: Callable[[str], None] = lambda _m: None) -> str:
    """いまの MT5 で使われている金の銘柄名。見つからなければ空。"""
    if mt5 is None:
        return ""
    # すでに建玉があれば、それが正解
    try:
        for pos in mt5.positions_get() or ():
            name = str(getattr(pos, "symbol", ""))
            if "XAU" in name.upper() or "GOLD" in name.upper():
                return name
    except Exception:  # noqa: BLE001
        pass

    for pattern, wanted in (("*XAU*", "XAUUSD"), ("*GOLD*", "GOLD")):
        try:
            names = [str(getattr(c, "name", "")) for c in (mt5.symbols_get(pattern) or ())]
        except Exception:  # noqa: BLE001
            continue
        exact = [n for n in names if n.upper().startswith(wanted)]
        for name in (*exact, *[n for n in names if n not in exact]):
            if is_gold_usd(name):
                return name
    log("金の銘柄が見つかりませんでした")
    return ""


def show_in_market_watch(
    terminal_exe: Any = None,
    log: Callable[[str], None] = lambda _m: None,
) -> str:
    """金の銘柄を気配値表示に出す。出せた銘柄名を返す（できなければ空）。

    MT5 が起動していない／ログインしていないときは何もしない。
    ここで失敗しても、EA の設置には影響しない。
    """
    if mt5 is None:
        return ""
    try:
        kwargs = {"path": str(terminal_exe)} if terminal_exe else {}
        if not mt5.initialize(**kwargs):
            log("MT5 につながらないので、気配値への表示は省きます")
            return ""
    except Exception as exc:  # noqa: BLE001
        log(f"MT5 につながりません: {type(exc).__name__}")
        return ""

    try:
        name = find_gold(log)
        if not name:
            return ""
        info = mt5.symbol_info(name)
        if info is not None and getattr(info, "visible", False):
            log(f"気配値にはすでに出ています: {name}")
            warm_up_m1(name, log=log)
            return name
        if mt5.symbol_select(name, True):
            log(f"気配値に出しました: {name}")
            warm_up_m1(name, log=log)
            return name
        log(f"気配値に出せませんでした: {name}")
        return ""
    except Exception as exc:  # noqa: BLE001
        log(f"気配値への表示で問題: {type(exc).__name__}")
        return ""
    finally:
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass


def warm_up_m1(name: str, bars: int = 6000, log: Callable[[str], None] = lambda _m: None) -> int:
    """1分足の過去データを先に読ませておく。

    EA は起動時に 1分足を 5000本ほど読み直す。データが端末に無いと、
    そこで待たされる（チャートに載せてもすぐ動き出さない）。
    先に取りに行かせておくと、載せた瞬間から動ける。

    チャートそのものを開くことは、MT5 の仕組み上できない。
    お客様に 1分足のチャートへドラッグしてもらう必要がある。
    """
    if mt5 is None:
        return 0
    try:
        rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M1, 0, bars)
    except Exception as exc:  # noqa: BLE001
        log(f"1分足の読み込みで問題: {type(exc).__name__}")
        return 0
    count = len(rates) if rates is not None else 0
    if count:
        log(f"1分足を {count} 本、先に読み込みました（{name}）")
    else:
        log(f"1分足を読み込めませんでした（{name}）")
    return count


def mt5_is_running() -> bool:
    """MT5 がいま起動しているか（ナビゲーターの更新が要るかの判断に使う）。"""
    if mt5 is None:
        return False
    try:
        ok = mt5.initialize()
    except Exception:  # noqa: BLE001
        return False
    if ok:
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass
    return bool(ok)
