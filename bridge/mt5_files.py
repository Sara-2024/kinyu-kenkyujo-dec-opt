"""Mac ルート：MetaTrader5 の Python 部品の代わりに、EA が書くファイルを読む。

Windows では ``import MetaTrader5 as mt5`` が MT5 を直接読むが、Mac 版 MT5（Wine 上）には
その部品が無い。そこで、ブリッジが使う関数と同じ名前・同じ返り値の形をここで用意し、
``sys.modules["MetaTrader5"] = mt5_files`` と差し込んで ``bridge.py`` をそのまま動かす。

読み書きするファイルは docs/mac-ea-files.md のとおり。置き場は MT5 の共通フォルダ
（``<Common>/Files``）。環境変数 ``TRELAB_FILES_DIR`` があればそこ、無ければ
``$APPDATA/MetaQuotes/Terminal/Common/Files``（connect_mac が APPDATA を Wine の
Roaming に向けておく）。

    EA → ここ : trelab_account.ini / trelab_positions.ini / trelab_orders.ini /
                trelab_deals.ini（依頼に応えて） / trelab_rates_*.ini（任意） / trelab_cmd_ack.ini
    ここ → EA : trelab_request.ini（書いてほしい） / trelab_cmd.ini（閉じて・取り消して）

ブリッジが使うのは次の関数だけ（bridge.py を grep して確かめている）:
    initialize / shutdown / last_error / account_info / terminal_info / positions_get /
    orders_get / history_deals_get / order_send / symbol_info / symbol_info_tick /
    symbol_select / symbols_get / copy_rates_from_pos
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# ── MetaTrader5 と同じ定数（値も本物と同じにしておく） ──
TIMEFRAME_M1 = 1
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_H1 = 16385
TIMEFRAME_H4 = 16388
TIMEFRAME_D1 = 16408
TIMEFRAME_W1 = 32769
_TF_NAMES = {
    TIMEFRAME_M1: "M1", TIMEFRAME_M5: "M5", TIMEFRAME_M15: "M15", TIMEFRAME_M30: "M30",
    TIMEFRAME_H1: "H1", TIMEFRAME_H4: "H4", TIMEFRAME_D1: "D1", TIMEFRAME_W1: "W1",
}

TRADE_ACTION_DEAL = 1
TRADE_ACTION_REMOVE = 8
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
ORDER_TIME_GTC = 0
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1
DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_ENTRY_OUT_BY = 3
TRADE_RETCODE_PLACED = 10008
TRADE_RETCODE_DONE = 10009
ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2

# ── 鮮度と待ち時間 ──
ACCOUNT_FRESH_SEC = 60      # trelab_account.ini がこれより古ければ「EA が止まっている」
REQUEST_TIMEOUT_SEC = 20    # 履歴・足の依頼を待つ上限
COMMAND_TIMEOUT_SEC = 15    # 閉じる・取り消すの返事を待つ上限
_POLL_SEC = 0.2

_last_error: tuple[int, str] = (0, "")
_initialized = False


# ────────────────────────────────
# 置き場
# ────────────────────────────────
def files_dir() -> Path:
    """EA と共有するフォルダ。無ければ作る（EA が先でもツールが先でもよいように）。"""
    env = os.environ.get("TRELAB_FILES_DIR")
    if env:
        p = Path(env)
    else:
        base = os.environ.get("APPDATA") or os.environ.get("TMPDIR") or "/tmp"
        p = Path(base) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path(name: str) -> Path:
    return files_dir() / name


# ────────────────────────────────
# 読み書きの型（key=value を ; でつないだ 1 行）
# ────────────────────────────────
def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp932"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


def parse_record(line: str) -> dict[str, str]:
    """``a=1;b=x`` → {"a": "1", "b": "x"}。値に ; は入らない前提（comment は EA 側で ; を取る）。"""
    out: dict[str, str] = {}
    for part in line.strip().split(";"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        out[key.strip()] = value.strip()
    return out


def read_record(name: str) -> dict[str, str] | None:
    """1 レコードのファイル（account / ack）。無ければ None。"""
    path = _path(name)
    try:
        text = _decode(path.read_bytes())
    except OSError:
        return None
    rec: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        rec.update(parse_record(line) if ";" in line else parse_record(line.replace("\n", "")))
    return rec or None


def read_table(name: str) -> tuple[dict[str, str], list[dict[str, str]]] | None:
    """見出し 1 行＋レコード N 行のファイル（positions / orders / deals / rates）。"""
    path = _path(name)
    try:
        text = _decode(path.read_bytes())
    except OSError:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {}, []
    return parse_record(lines[0]), [parse_record(ln) for ln in lines[1:]]


def write_record(name: str, rec: dict[str, Any]) -> None:
    body = ";".join(f"{k}={v}" for k, v in rec.items()) + "\n"
    tmp = _path(name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, _path(name))  # 途中の状態を EA に読ませない


def _f(rec: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(rec.get(key, default))
    except (TypeError, ValueError):
        return default


def _i(rec: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(rec.get(key, default)))
    except (TypeError, ValueError):
        return default


def _age(name: str) -> float | None:
    try:
        return time.time() - _path(name).stat().st_mtime
    except OSError:
        return None


# ────────────────────────────────
# 口座・端末
# ────────────────────────────────
def _account_record() -> dict[str, str] | None:
    """新しい trelab_account.ini。古ければ None（EA がチャートに無い／MT5 が止まっている）。"""
    age = _age("trelab_account.ini")
    if age is None or age > ACCOUNT_FRESH_SEC:
        return None
    return read_record("trelab_account.ini")


def initialize(path: str | None = None, login: int | None = None, password: str | None = None,
               server: str | None = None, timeout: int | None = None, portable: bool = False) -> bool:
    """EA が書いた口座の控えが新しければ「つながった」。引数は MetaTrader5 と同じ形で受けて無視する。"""
    global _initialized, _last_error
    rec = _account_record()
    if rec is None or not rec.get("login"):
        _initialized = False
        _last_error = (-10005, "EA がまだチャートで動いていません（trelab_account.ini が無いか古い）")
        return False
    _initialized = True
    _last_error = (1, "Success")
    return True


def shutdown() -> None:
    global _initialized
    _initialized = False


def last_error() -> tuple[int, str]:
    return _last_error


def account_info() -> SimpleNamespace | None:
    rec = _account_record()
    if rec is None:
        return None
    return SimpleNamespace(
        login=_i(rec, "login"),
        server=rec.get("server", ""),
        company=rec.get("company", ""),
        currency=rec.get("currency", ""),
        balance=_f(rec, "balance"),
        equity=_f(rec, "equity"),
        margin_free=_f(rec, "margin_free"),
        trade_mode=_i(rec, "trade_mode"),
        name=rec.get("name", ""),
    )


def terminal_info() -> SimpleNamespace | None:
    rec = _account_record()
    if rec is None:
        return None
    common = files_dir().parent  # <Common>
    data_path = os.environ.get("TRELAB_DATA_PATH") or str(common.parent)
    return SimpleNamespace(
        connected=bool(_i(rec, "terminal_connected", 1)),
        trade_allowed=bool(_i(rec, "terminal_trade_allowed", 0)),
        build=_i(rec, "build"),
        name=rec.get("terminal_name", "MetaTrader 5"),
        data_path=data_path,
        commondata_path=str(common),
    )


# ────────────────────────────────
# 銘柄
# ────────────────────────────────
def _own_symbol(rec: dict[str, str] | None) -> str:
    return (rec or {}).get("symbol", "")


def symbol_info(name: str) -> SimpleNamespace | None:
    rec = _account_record()
    if rec is None or not name:
        return None
    own = _own_symbol(rec)
    if name.upper() != own.upper():
        # EA が載っている銘柄しか分からない。ドル建ての金かどうかの判定には足りる
        return SimpleNamespace(name=name, visible=False, currency_profit="", currency_base="",
                               digits=2, point=0.01, filling_mode=_i(rec, "filling", 1))
    return SimpleNamespace(
        name=own,
        visible=True,
        currency_profit="USD",
        currency_base="XAU",
        digits=_i(rec, "digits", 2),
        point=_f(rec, "point", 0.01),
        filling_mode=_i(rec, "filling", 1),
    )


def symbol_info_tick(name: str) -> SimpleNamespace | None:
    rec = _account_record()
    if rec is None or name.upper() != _own_symbol(rec).upper():
        return None
    bid = _f(rec, "bid")
    ask = _f(rec, "ask")
    return SimpleNamespace(bid=bid, ask=ask, last=bid, time=_i(rec, "server_time"))


def symbol_select(name: str, enable: bool = True) -> bool:
    return bool(name)


def symbols_get(group: str = "*") -> list[SimpleNamespace]:
    rec = _account_record()
    own = _own_symbol(rec)
    if not own:
        return []
    pattern = group.strip("*").upper()
    if pattern and pattern not in own.upper():
        return []
    return [SimpleNamespace(name=own)]


# ────────────────────────────────
# 建玉・待機注文
# ────────────────────────────────
def positions_get(**_kw: Any) -> list[SimpleNamespace]:
    table = read_table("trelab_positions.ini")
    if table is None:
        return []
    _, rows = table
    out = []
    for r in rows:
        if not r.get("ticket"):
            continue
        out.append(SimpleNamespace(
            ticket=_i(r, "ticket"),
            identifier=_i(r, "ticket"),
            symbol=r.get("symbol", ""),
            type=_i(r, "type"),
            volume=_f(r, "volume"),
            price_open=_f(r, "price_open"),
            price_current=_f(r, "price_current"),
            sl=_f(r, "sl"),
            tp=_f(r, "tp"),
            profit=_f(r, "profit"),
            swap=_f(r, "swap"),
            magic=_i(r, "magic"),
            time=_i(r, "time"),
            comment=r.get("comment", ""),
        ))
    return out


def orders_get(**_kw: Any) -> list[SimpleNamespace]:
    table = read_table("trelab_orders.ini")
    if table is None:
        return []
    _, rows = table
    return [
        SimpleNamespace(
            ticket=_i(r, "ticket"),
            symbol=r.get("symbol", ""),
            type=_i(r, "type"),
            volume_current=_f(r, "volume"),
            price_open=_f(r, "price"),
            magic=_i(r, "magic"),
            time_setup=_i(r, "time"),
            comment=r.get("comment", ""),
        )
        for r in rows
        if r.get("ticket")
    ]


# ────────────────────────────────
# 依頼（履歴・足）
# ────────────────────────────────
def _new_id() -> str:
    return str(int(time.time() * 1000))


def _wait_for_table(name: str, request_id: str, timeout: float) -> list[dict[str, str]] | None:
    """依頼の id が見出しに入った結果が来るまで待つ。来なければ None。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        table = read_table(name)
        if table is not None:
            head, rows = table
            if head.get("request") == request_id:
                return rows
        time.sleep(_POLL_SEC)
    return None


def _to_unix(value: Any) -> int:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    return int(value)


def history_deals_get(*args: Any, **kwargs: Any) -> list[SimpleNamespace] | None:
    """``history_deals_get(from, to)`` か ``history_deals_get(position=…)``。EA に書いてもらって読む。"""
    request_id = _new_id()
    req: dict[str, Any] = {"id": request_id, "kind": "deals"}
    if "position" in kwargs:
        req["position"] = int(kwargs["position"])
    elif len(args) >= 2:
        req["from"] = _to_unix(args[0])
        req["to"] = _to_unix(args[1])
    else:
        return None
    write_record("trelab_request.ini", req)
    rows = _wait_for_table("trelab_deals.ini", request_id, REQUEST_TIMEOUT_SEC)
    if rows is None:
        return None
    return [
        SimpleNamespace(
            ticket=_i(r, "ticket"),
            order=_i(r, "order"),
            position_id=_i(r, "position"),
            entry=_i(r, "entry"),
            type=_i(r, "type"),
            volume=_f(r, "volume"),
            price=_f(r, "price"),
            profit=_f(r, "profit"),
            commission=_f(r, "commission"),
            swap=_f(r, "swap"),
            fee=_f(r, "fee"),
            time=_i(r, "time"),
            symbol=r.get("symbol", ""),
            magic=_i(r, "magic"),
            comment=r.get("comment", ""),
            reason=0,
        )
        for r in rows
        if r.get("ticket")
    ]


def copy_rates_from_pos(symbol: str, timeframe: int, start_pos: int, count: int) -> list[dict[str, Any]] | None:
    """ローソク足。EA が対応していなければ None（AI の見張りだけが使う。無くても連携は動く）。"""
    tf = _TF_NAMES.get(int(timeframe), "M1")
    request_id = _new_id()
    write_record("trelab_request.ini", {"id": request_id, "kind": "rates", "symbol": symbol, "tf": tf, "count": int(count)})
    rows = _wait_for_table(f"trelab_rates_{symbol}_{tf}.ini", request_id, REQUEST_TIMEOUT_SEC)
    if rows is None:
        return None
    return [
        {
            "time": _i(r, "time"),
            "open": _f(r, "open"),
            "high": _f(r, "high"),
            "low": _f(r, "low"),
            "close": _f(r, "close"),
            "tick_volume": _i(r, "tick_volume"),
        }
        for r in rows
    ]


# ────────────────────────────────
# 指令（閉じる・取り消す）
# ────────────────────────────────
def order_send(request: dict[str, Any]) -> SimpleNamespace:
    """ブリッジの全決済が使う形だけ受ける：
    ``{"action": TRADE_ACTION_DEAL, "position": ticket, ...}`` → close、
    ``{"action": TRADE_ACTION_REMOVE, "order": ticket}`` → remove。
    EA が実行して ``trelab_cmd_ack.ini`` に返事を書くのを待つ。
    """
    action = int(request.get("action", 0))
    request_id = _new_id()
    if action == TRADE_ACTION_REMOVE:
        cmd = {"id": request_id, "cmd": "remove", "order": int(request.get("order", 0))}
    else:
        cmd = {"id": request_id, "cmd": "close", "position": int(request.get("position", 0))}
    try:
        _path("trelab_cmd_ack.ini").unlink()
    except OSError:
        pass
    write_record("trelab_cmd.ini", cmd)
    deadline = time.time() + COMMAND_TIMEOUT_SEC
    while time.time() < deadline:
        ack = read_record("trelab_cmd_ack.ini")
        if ack and ack.get("id") == request_id:
            ok = ack.get("ok", "0") == "1"
            retcode = _i(ack, "retcode", TRADE_RETCODE_DONE if ok else 10013)
            return SimpleNamespace(retcode=retcode, comment=ack.get("comment", ""), deal=_i(ack, "deal"), order=_i(ack, "order"))
        time.sleep(_POLL_SEC)
    return SimpleNamespace(retcode=10031, comment="EA から返事がありません", deal=0, order=0)


def ea_running() -> bool:
    """EA がいまチャートで動いているか（connect_mac の案内に使う）。"""
    return _account_record() is not None
