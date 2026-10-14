"""ブリッジの配線が通っているかを、MT5 も websockets も無い所で確かめる。

ここが無かったせいで、`_config_dir()` 未定義や、存在しない `last_value` を
見ていた不具合を、Windows で実際に動かすまで誰も気づけなかった。
実行: python3 bridge/tests/wiring_test.py
"""
from __future__ import annotations

import ast
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


# ── MT5 と websockets が無い環境でも import できるよう、最小限の身代わりを置く ──
def _stub(name: str, **attrs: object) -> None:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod


class _FakeWS:
    async def send(self, *_a, **_k) -> None: ...


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

# ── 1) Bridge が組み立てられる（ここで未定義の名前があれば落ちる） ──
cfg = bridge_mod.Config()
b = bridge_mod.Bridge(cfg)
check("Bridge を組み立てられる", b is not None)
try:
    check("設定フォルダを決められる", bridge_mod._config_dir().name == "AITrader")
except AttributeError as exc:
    check("設定フォルダを決められる", False, str(exc))
check("AIリスク監督は動かさない（2026-10-14 に廃止）", b.risk is None)
check("指令を配る係も監督を持たない", getattr(b.router, "risk", None) is None)

# ── 2) 「稼働中か」を見る式が、実在する属性を見ている ──
watch = lambda: b.mt.desired_value != 0.0  # noqa: E731  bridge.run と同じ式
try:
    watch()
    ok = True
except AttributeError as exc:
    ok = False
    print("     ", exc)
check("稼働判定が実在する属性を見ている", ok)

# ── 3) 画面へ送る内容に AIゲートの状態は混ぜない（廃止）──
status = b._with_risk({"account": 1})
check("状態に ai_gate が入らない", "ai_gate" not in status and status.get("account") == 1, str(status.keys()))
check("接続ツールの合図を書く入口がある", hasattr(b.mt, "touch_gate"))

# ── 4) MT5 コントローラに、監督が呼ぶ入口がそろっている ──
for name in ("risk_snapshot", "account_mode", "last_closed_m1", "symbol_tick", "set_variables"):
    check(f"MT5コントローラに {name} がある", hasattr(b.mt, name))

# ── 5) 監督が呼ぶ名前が、実際に定義されているか（静的にも見る） ──
source = (BRIDGE / "risk_gate.py").read_text(encoding="utf-8")
tree = ast.parse(source)
used = {
    node.attr
    for node in ast.walk(tree)
    if isinstance(node, ast.Attribute)
    and isinstance(node.value, ast.Attribute)
    and isinstance(node.value.value, ast.Name)
    and node.value.value.id == "self"
    and node.value.attr == "mt"
}
missing = [name for name in used if not hasattr(b.mt, name)]
check("監督が呼ぶ MT5 の入口が全部ある", not missing, f"足りない: {missing}")

# ── 5-2) ブリッジは「初回に選んだ MT5」に繋ぐ（MT5 が何台もある PC 向け） ──
#    ここを飛ばすと別のターミナルに繋がり、EA を載せた側の「アルゴ取引」が ON でも
#    サイトには OFF と見えたままになる。
import pathlib as _pl
import tempfile as _tf

fake = sys.modules["MetaTrader5"]
_fake_exe = _pl.Path(_tf.mkdtemp(prefix="mt5-")) / "terminal64.exe"
_fake_exe.write_text("")
init_calls = []


def _fake_initialize(*a, **k):
    init_calls.append(k)
    return k.get("path") == str(_fake_exe)  # 名指ししたときだけ繋がる


fake.initialize = _fake_initialize
fake.account_info = lambda: types.SimpleNamespace(login=75602463, server="XMTrading-MT5 3")
fake.terminal_info = lambda: types.SimpleNamespace(name="MetaTrader 5", build=5000, trade_allowed=True)
cfg2 = bridge_mod.Config()
cfg2.mt5_path = str(_fake_exe)
b2 = bridge_mod.Bridge(cfg2)
ok2 = b2.mt._initialize_blocking()
check("初回に選んだ MT5 に繋ぐ", ok2 is True, str(init_calls))
check("最初の接続が名指し（path つき）", bool(init_calls) and init_calls[0].get("path") == str(_fake_exe), str(init_calls[:1]))
init_calls.clear()
cfg3 = bridge_mod.Config()
cfg3.mt5_path = str(_fake_exe.with_name("gone.exe"))  # 無いもの
b3 = bridge_mod.Bridge(cfg3)
fake.initialize = lambda *a, **k: (init_calls.append(k), False)[1]
fake.last_error = lambda: (-1, "test")
b3.mt._initialize_blocking()
check("選んだ MT5 が無ければ、まず名指しせずにほかを探す", bool(init_calls) and init_calls[0].get("path") != cfg3.mt5_path, str(init_calls))

# ── 5-3) 古いブリッジを exe の名前で見分けられる（名前を変えても止められる） ──
real_image = bridge_mod._process_image
for image, expect in (("DreamlandPassport.exe", True), ("MT5Automatic.exe", True), ("AITrader.exe", True), ("pythonw.exe", True), ("notepad.exe", False)):
    bridge_mod._process_image = lambda pid, _i=image: _i
    check(f"{image} はブリッジ{'として扱う' if expect else 'ではない'}", bridge_mod._is_bridge_process(4242) is expect)
bridge_mod._process_image = real_image

# ── 5-4) EA の控えは PC 内で1つ。口座・EA 名・銘柄を突き合わせて「進める」を決める ──
#    別の MT5 の EA が書いた控えで「生きている」と出たり、ゴールド以外のチャートで
#    手順が「済み」になったりしないこと。
_common = _pl.Path(_tf.mkdtemp(prefix="mt5common-"))
(_common / "Files").mkdir()
fake.terminal_info = lambda: types.SimpleNamespace(name="MetaTrader 5", build=5000, trade_allowed=True, commondata_path=str(_common))
fake.account_info = lambda: types.SimpleNamespace(login=75613879, server="XMTrading-MT5 3")
_state = _common / "Files" / b.mt.STATE_FILE


def _ea_state(text):
    _state.write_text(text, encoding="utf-8")
    return b.mt._ea_state_blocking()


s = _ea_state("state=稼働\nallowed=1\naccount=75613879\nea=YumekkuEA_win\nsymbol=GOLD\n")
check("自分の口座・Yumekku・GOLD なら進める", s["ea_alive"] is True and s["ea_ready"] is True and s["ea_problem"] is None, str(s))
s = _ea_state("state=稼働\nallowed=1\naccount=75613879\nea=YumekkuEA_win\nsymbol=XAUUSD.r\n")
check("XAUUSD 系も進める", s["ea_ready"] is True, str(s))
s = _ea_state("state=稼働\nallowed=1\naccount=198588095\nea=YumekkuEA_win\nsymbol=XAUUSD\n")
check("別の口座の控えでは進めない", s["ea_alive"] is False and s["ea_ready"] is False and "198588095" in str(s["ea_problem"]), str(s))
s = _ea_state("state=稼働\nallowed=1\naccount=75613879\nea=OrbitGoldEA_v6\nsymbol=GOLD\n")
check("Yumekku 以外の EA では進めない", s["ea_alive"] is False and "OrbitGoldEA_v6" in str(s["ea_problem"]), str(s))
s = _ea_state("state=稼働\nallowed=1\naccount=75613879\nea=YumekkuEA_win\nsymbol=USDJPY\n")
check("ゴールド以外のチャートでは進めない（EA は生きている）", s["ea_alive"] is True and s["ea_ready"] is False and "USDJPY" in str(s["ea_problem"]), str(s))
s = _ea_state("state=稼働\nallowed=1\naccount=75613879\nea=YumekkuEA_win\nsymbol=XAUEUR\n")
check("XAUEUR はゴールド扱いしない", s["ea_ready"] is False, str(s))
s = _ea_state("state=稼働\nallowed=1\nea=YumekkuEA_win\nsymbol=GOLD\n")
check("口座を書かない古い EA でも進める", s["ea_alive"] is True and s["ea_ready"] is True, str(s))
_state.unlink()
s = b.mt._ea_state_blocking()
check("控えが無ければ進めない", s.get("ea_alive") is False and s.get("ea_ready") is False, str(s))

# ── 6) 一斉制御の「全決済」が配線されている ──
import asyncio  # noqa: E402

check("MT5コントローラに close_all がある", hasattr(b.mt, "close_all"))
check("全決済の本体がある", hasattr(b.mt, "_close_all_blocking"))


class _Pos:
    def __init__(self, ticket, symbol, volume, kind, magic=7):
        self.ticket, self.symbol, self.volume, self.type, self.magic = ticket, symbol, volume, kind, magic


class _Order:
    def __init__(self, ticket):
        self.ticket = ticket


class _Result:
    def __init__(self, retcode, comment=""):
        self.retcode, self.comment = retcode, comment


sent = []


def _order_send(req):
    sent.append(req)
    # 1件だけわざと失敗させる（最後まで回って失敗を返すこと）
    if req.get("position") == 2:
        return _Result(10013, "invalid request")
    return _Result(10009)


fake = sys.modules["MetaTrader5"]
fake.positions_get = lambda *a, **k: [_Pos(1, "XAUUSD", 0.1, 0), _Pos(2, "XAUUSD", 0.2, 1)]
fake.orders_get = lambda *a, **k: [_Order(9)]
fake.symbol_info = lambda s: types.SimpleNamespace(filling_mode=2)
fake.symbol_info_tick = lambda s: types.SimpleNamespace(bid=2400.0, ask=2400.5)
fake.order_send = _order_send
fake.TRADE_RETCODE_DONE = 10009
fake.TRADE_RETCODE_PLACED = 10008
fake.TRADE_ACTION_DEAL = 1
fake.TRADE_ACTION_REMOVE = 8
fake.ORDER_TYPE_BUY = 0
fake.ORDER_TYPE_SELL = 1
fake.POSITION_TYPE_BUY = 0
fake.ORDER_FILLING_IOC = 1
fake.SYMBOL_FILLING_IOC = 2
fake.SYMBOL_FILLING_FOK = 1
b.mt.ready = True
out = b.mt._close_all_blocking()
check("建玉は反対売買で閉じる（買いは売り・売りは買い）",
      sent[0]["type"] == 1 and sent[0]["position"] == 1 and sent[1]["type"] == 0 and sent[1]["position"] == 2,
      str(sent[:2]))
check("待機注文は取り消す", any(r.get("action") == 8 and r.get("order") == 9 for r in sent), str(sent))
check("1件失敗しても最後まで回る", out["closed"] == 1 and out["removed"] == 1 and len(out["failed"]) == 1, str(out))
check("失敗した番号が分かる", out["failed"][0]["ticket"] == 2, str(out["failed"]))

# 指令として届いたときは、先に新規を止めてから閉じる
calls = []


async def _set_trading(allowed, by="サイト"):
    calls.append(("set_trading", allowed))
    return True, 0.0


async def _close_all():
    calls.append(("close_all",))
    return {"closed": 1, "removed": 1, "failed": []}


b.mt.set_trading = _set_trading
b.mt.close_all = _close_all
ack = asyncio.run(b.router.handle({"command": "close_all", "id": "t1"}))
check("close_all（一斉全決済）の指令が通る", ack["ok"] is True and ack["closed"] == 1, str(ack))
check("全決済だけのときは新規を止めない", calls == [("close_all",)], str(calls))
check("全決済だけの応答に売買フラグを混ぜない", "value" not in ack, str(ack))
calls.clear()
ack = asyncio.run(b.router.handle({"command": "stop_system", "id": "t2"}))
check("stop_system（システム停止）の指令が通る", ack["ok"] is True and ack["closed"] == 1, str(ack))
check("システム停止は、閉じる前に新規を止める", calls == [("set_trading", False), ("close_all",)], str(calls))
calls.clear()
ack = asyncio.run(b.router.handle({"command": "stop_trading", "id": "t3"}))
check("stop_trading（エントリーのみ停止）は閉じない", calls == [("set_trading", False)], str(calls))

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
