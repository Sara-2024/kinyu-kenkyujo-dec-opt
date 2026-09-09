"""指令ファイルが消えても、サイトの設定が戻るかを確かめる。"""
import json, pathlib, sys, tempfile, types
BRIDGE = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(BRIDGE))
def _stub(name, **a):
    m = types.ModuleType(name); [setattr(m, k, v) for k, v in a.items()]; sys.modules[name] = m
def _nc(*a, **k): raise RuntimeError()
_stub("websockets", exceptions=types.SimpleNamespace(WebSocketException=Exception))
_stub("websockets.exceptions", WebSocketException=Exception)
_stub("websockets.asyncio", client=types.SimpleNamespace(connect=_nc))
_stub("websockets.asyncio.client", connect=_nc)
_stub("MetaTrader5", initialize=lambda *a, **k: False, shutdown=lambda: None)
import bridge as b
P=F=0
def check(n,c,e=""):
    global P,F
    (globals().__setitem__('P',P+1), print(f"  ok   {n}")) if c else (globals().__setitem__('F',F+1), print(f"  NG   {n} {e}"))
tmp = pathlib.Path(tempfile.mkdtemp())
b._config_dir = lambda: tmp
mt = b.MT5Controller(b.Config())
gate = tmp / "trelab_gate.ini"
mt._gate_path = lambda: gate

# サイトから設定が来た
mt._set_gvs_blocking({"AI_LOT": 0.01, "AI_MAX_POSITIONS": 7.0, "AI_DAY_LOSS_LIMIT": 45000.0, "AI_TRADING_ALLOWED": 1.0})
check("指令ファイルに書かれる", "AI_LOT=0.01" in gate.read_text())
check("控えが作られる", json.loads((tmp/"gate_settings.json").read_text())["AI_MAX_POSITIONS"] == 7.0)

# AIゲートの値は控えない（毎回変わるので）
mt._set_gvs_blocking({"AI_GATE_MODE": 2.0, "AI_BUY_ALLOWED": 0.0})
check("AIゲートの値は控えない", "AI_GATE_MODE" not in json.loads((tmp/"gate_settings.json").read_text()))

# 指令ファイルが消えた（MT5 の入れ直しや掃除、検証中の削除）
gate.unlink()
restored = mt._restore_settings_blocking()
check("消えた設定を書き戻す", sorted(restored) == ["AI_DAY_LOSS_LIMIT", "AI_LOT", "AI_MAX_POSITIONS", "AI_TRADING_ALLOWED"], str(restored))
text = gate.read_text()
check("ロットが戻る", "AI_LOT=0.01" in text, text)
check("1日の損失上限が戻る", "AI_DAY_LOSS_LIMIT=45000.0" in text, text)

# 一部だけ消えた場合
vals = {l.split("=")[0]: l.split("=")[1] for l in gate.read_text().splitlines() if "=" in l}
del vals["AI_MAX_POSITIONS"]
gate.write_text("".join(f"{k}={v}\n" for k, v in vals.items()))
check("欠けた分だけ戻す", mt._restore_settings_blocking() == ["AI_MAX_POSITIONS"])

# そろっていれば何もしない
check("そろっていれば触らない", mt._restore_settings_blocking() == [])
print(f"\n{P} ok / {F} NG"); sys.exit(1 if F else 0)
