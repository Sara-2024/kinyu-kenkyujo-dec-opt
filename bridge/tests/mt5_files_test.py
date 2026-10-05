"""Mac ルートの「ファイル読み書き版 MetaTrader5」が、EA の書くファイルを正しく読み、
ブリッジの全決済がそのまま通るかを確かめる。

    python3 bridge/tests/mt5_files_test.py

MT5 も Mac も要らない。一時フォルダに「EA のふり」をするスレッドを置き、
依頼（trelab_request.ini）と指令（trelab_cmd.ini）に答えさせる。
docs/mac-ea-files.md とファイル名がずれていないかも見る。
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import threading
import time

BRIDGE = pathlib.Path(__file__).resolve().parent.parent
ROOT = BRIDGE.parent
sys.path.insert(0, str(BRIDGE))

TMP = pathlib.Path(tempfile.mkdtemp(prefix="trelab-mac-"))
os.environ["TRELAB_FILES_DIR"] = str(TMP)
os.environ["TRELAB_DATA_PATH"] = str(TMP / "data")
os.environ["LOCALAPPDATA"] = str(TMP / "local")
(TMP / "data" / "MQL5" / "Experts").mkdir(parents=True)

import mt5_files  # noqa: E402

sys.modules["MetaTrader5"] = mt5_files  # ブリッジにはこれが MetaTrader5 に見える

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


def write(name: str, text: str) -> None:
    (TMP / name).write_text(text, encoding="utf-8")


NOW = int(time.time())

# ── 1) EA が居なければ「つながらない」 ──
check("控えが無ければ initialize は False", mt5_files.initialize() is False)
check("理由が last_error に入る", "trelab_account.ini" in mt5_files.last_error()[1])
check("account_info も None", mt5_files.account_info() is None)

# ── 2) EA が口座の控えを書けば「つながる」 ──
ACCOUNT = (
    "login=75613879\nserver=XMTrading-MT5 3\ncompany=XM\ncurrency=JPY\nbalance=1000000.5\nequity=1001234.25\n"
    "margin_free=990000\ntrade_mode=0\nterminal_connected=1\nterminal_trade_allowed=1\nbuild=4620\n"
    f"terminal_name=MetaTrader 5\nserver_time={NOW}\nsymbol=GOLD\nbid=2650.12\nask=2650.42\ndigits=2\npoint=0.01\nfilling=2\nat={NOW}\n"
)
write("trelab_account.ini", ACCOUNT)
check("控えがあれば initialize は True", mt5_files.initialize(path="/dummy/terminal64.exe") is True)
acc = mt5_files.account_info()
check("口座番号・サーバー・残高が読める", acc.login == 75613879 and acc.server == "XMTrading-MT5 3" and acc.balance == 1000000.5, str(acc))
check("デモ口座と分かる", acc.trade_mode == mt5_files.ACCOUNT_TRADE_MODE_DEMO)
term = mt5_files.terminal_info()
check("アルゴ取引 ON が読める", term.trade_allowed is True and term.connected is True, str(term))
check("共通フォルダの場所をブリッジに教える", term.commondata_path == str(TMP.parent), term.commondata_path)
tick = mt5_files.symbol_info_tick("GOLD")
check("載っている銘柄の値段が読める", tick.bid == 2650.12 and tick.ask == 2650.42, str(tick))
check("載っていない銘柄は None", mt5_files.symbol_info_tick("USDJPY") is None)
check("金の銘柄を探せる", [s.name for s in mt5_files.symbols_get("*GOLD*")] == ["GOLD"])
info = mt5_files.symbol_info("GOLD")
check("ドル建ての金として見える", info.currency_profit == "USD" and info.filling_mode == 2, str(info))

# 古くなれば「止まっている」
old = NOW - 600
os.utime(TMP / "trelab_account.ini", (old, old))
check("控えが古ければ account_info は None（EA が止まった）", mt5_files.account_info() is None)
write("trelab_account.ini", ACCOUNT)

# ── 3) 建玉・待機注文 ──
write(
    "trelab_positions.ini",
    f"count=2;at={NOW}\n"
    "ticket=111;symbol=GOLD;type=0;volume=0.10;price_open=2640;price_current=2650.12;sl=2630;tp=2670;profit=1012;swap=-12;magic=7;time=1759690000;comment=Yumekku M1\n"
    "ticket=222;symbol=GOLD;type=1;volume=0.20;price_open=2660;price_current=2650.42;sl=0;tp=0;profit=958;swap=0;magic=0;time=1759695000;comment=\n",
)
write("trelab_orders.ini", f"count=1;at={NOW}\nticket=333;symbol=GOLD;type=2;volume=0.10;price=2600;sl=0;tp=0;magic=7;time=1759690000;comment=\n")
pos = mt5_files.positions_get()
check("建玉が 2 件読める", len(pos) == 2 and pos[0].ticket == 111 and pos[1].type == mt5_files.POSITION_TYPE_SELL, str(pos))
check("手動の建玉（magic=0）も落とさない", any(p.magic == 0 for p in pos))
check("待機注文が読める", [o.ticket for o in mt5_files.orders_get()] == [333])


# ── 4) EA のふり：依頼と指令に答える ──
stop = threading.Event()


def fake_ea() -> None:
    while not stop.is_set():
        req = mt5_files.read_record("trelab_request.ini")
        if req and req.get("kind") == "deals":
            body = f"request={req['id']};count=2;from={req.get('from', '')};to={req.get('to', '')}\n"
            body += "ticket=1;order=1;position=111;entry=0;type=0;volume=0.1;price=2640;profit=0;commission=-0.5;swap=0;fee=0;time=1759690000;symbol=GOLD;magic=7;comment=\n"
            body += "ticket=2;order=2;position=111;entry=2;type=1;volume=0.2;price=2650;profit=1000;commission=-0.5;swap=-3;fee=0;time=1759695000;symbol=GOLD;magic=7;comment=\n"
            write("trelab_deals.ini", body)
            (TMP / "trelab_request.ini").unlink(missing_ok=True)
        cmd = mt5_files.read_record("trelab_cmd.ini")
        if cmd:
            if cmd.get("cmd") == "close" and cmd.get("position") == "222":
                ack = {"id": cmd["id"], "ok": 0, "retcode": 10013, "comment": "invalid request"}
            else:
                ack = {"id": cmd["id"], "ok": 1, "retcode": 10009, "deal": 9000, "comment": "done"}
            mt5_files.write_record("trelab_cmd_ack.ini", ack)
            (TMP / "trelab_cmd.ini").unlink(missing_ok=True)
        time.sleep(0.05)


th = threading.Thread(target=fake_ea, daemon=True)
th.start()

deals = mt5_files.history_deals_get(NOW - 86400 * 30, NOW)
check("履歴は EA に書いてもらって読む", deals is not None and len(deals) == 2, str(deals))
check("ドテン（INOUT）の損益も落とさない", deals is not None and any(d.entry == mt5_files.DEAL_ENTRY_INOUT and d.profit == 1000 for d in deals))
check("依頼ファイルは EA が消す", not (TMP / "trelab_request.ini").exists())

res = mt5_files.order_send({"action": mt5_files.TRADE_ACTION_DEAL, "position": 111, "symbol": "GOLD", "volume": 0.1})
check("閉じる指令に返事が返る", res.retcode == mt5_files.TRADE_RETCODE_DONE and res.deal == 9000, str(res))
res = mt5_files.order_send({"action": mt5_files.TRADE_ACTION_REMOVE, "order": 333})
check("取り消す指令にも返事が返る", res.retcode == mt5_files.TRADE_RETCODE_DONE, str(res))

# ── 5) ブリッジの全決済が、この部品のままで通る ──
import types  # noqa: E402

# websockets が無い環境でもブリッジを読み込めるよう、最小限の身代わり（wiring_test と同じ）
try:
    import websockets.exceptions  # noqa: F401
except ImportError:

    def _stub(name: str, **attrs: object) -> None:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod

    async def _connect(*_a: object, **_k: object) -> None:
        raise RuntimeError("stub")

    _stub("websockets", exceptions=types.SimpleNamespace(WebSocketException=Exception))
    _stub("websockets.exceptions", WebSocketException=Exception)
    _stub("websockets.asyncio", client=types.SimpleNamespace(connect=_connect))
    _stub("websockets.asyncio.client", connect=_connect)

import bridge as bridge_mod  # noqa: E402

check("ブリッジは MetaTrader5 としてこの部品を見ている", bridge_mod.mt5 is mt5_files)
cfg = bridge_mod.Config()
ctl = bridge_mod.MT5Controller(cfg)
ctl.ready = True
result = ctl._close_all_blocking()
failed_tickets = [f.get("ticket") if isinstance(f, dict) else f for f in result["failed"]]
check("全決済が EA 経由で回る（1 件はわざと失敗）", result["closed"] == 1 and result["removed"] == 1 and failed_tickets == [222], str(result))

# ── 6) 仕様書とファイル名がずれていない ──
spec = (ROOT / "docs" / "mac-ea-files.md").read_text(encoding="utf-8")
for name in ("trelab_account.ini", "trelab_positions.ini", "trelab_orders.ini", "trelab_deals.ini", "trelab_cmd.ini", "trelab_cmd_ack.ini", "trelab_request.ini"):
    check(f"仕様書に {name} がある", name in spec)
src = (BRIDGE / "mt5_files.py").read_text(encoding="utf-8")
# at（EA が書いた時刻）は仕様にはあるが、鮮度はファイルの更新時刻で見るので読まない
for key in ("login", "server", "balance", "equity", "trade_mode", "terminal_trade_allowed", "server_time", "symbol", "bid", "ask", "filling"):
    check(f"仕様書の口座の項目 {key} を読んでいる", f'"{key}"' in src and f"{key}=" in spec)

stop.set()
print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
