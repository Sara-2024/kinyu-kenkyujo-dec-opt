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
check("AIリスク監督が用意される", b.risk is not None, "risk_gate を読めていない")
check("指令を配る係が監督を持っている", getattr(b.router, "risk", None) is b.risk)

# ── 2) 「稼働中か」を見る式が、実在する属性を見ている ──
watch = lambda: b.mt.desired_value != 0.0  # noqa: E731  bridge.run と同じ式
try:
    watch()
    ok = True
except AttributeError as exc:
    ok = False
    print("     ", exc)
check("稼働判定が実在する属性を見ている", ok)

# ── 3) 画面へ送る内容に AIゲートの状態が混ざる ──
status = b._with_risk({"account": 1, "ea_skipped": {"ai_skip_buy": 1}}) if b.risk else {}
check("状態に ai_gate が入る", "ai_gate" in status, str(status.keys()))
check("ai_gate に買い売りが入る", {"buy", "sell", "mode"} <= set(status["ai_gate"]))

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

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
