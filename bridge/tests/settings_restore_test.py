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

# 接続ツールの合図（EA のパネルが「連携済み／未接続」を出す材料）
import calendar, time
check("合図を書ける", mt._touch_gate_blocking())
beat = [l for l in gate.read_text().splitlines() if l.startswith("AI_BRIDGE_AT=")]
check("合図は PC の時計（ローカル時刻の UNIX 秒）", bool(beat) and abs(float(beat[0].split("=")[1]) - calendar.timegm(time.localtime())) < 5, str(beat))
check("合図を書いても設定は消えない", "AI_LOT=0.01" in gate.read_text())
check("合図は控えに入れない", "AI_BRIDGE_AT" not in json.loads((tmp/"gate_settings.json").read_text()))

# ── 追加口座の枠（BRIDGE_SLOT）：ロック名・設定の置き場・指令ファイル名が口座番号で分かれる ──
import importlib, os as _os
_os.environ["BRIDGE_SLOT"] = "135209731"
try:
    b2 = importlib.reload(b)
    check("追加口座のロック名は口座番号付き", b2._lock_name() == "aitrader-bridge-135209731.lock")
    check("追加口座は --slot 付きのプロセスだけを自分の枠と見る", b2._slot_ok("x.exe --run-bridge --slot 135209731") and not b2._slot_ok("x.exe --run-bridge"))
    b2._config_dir = lambda: tmp / "accounts" / "135209731"
    mt2 = b2.MT5Controller(b2.Config())
    check("追加口座の指令ファイルは口座番号付き", mt2._gate_name() == "trelab_gate_135209731.ini")
finally:
    _os.environ.pop("BRIDGE_SLOT", None)
    b = importlib.reload(b)
check("1 本目のロック名はこれまでどおり", b._lock_name() == "aitrader-bridge.lock")
check("1 本目は --slot 付きのプロセスを触らない", b._slot_ok("x.exe --run-bridge") and not b._slot_ok("x.exe --run-bridge --slot 1"))

print(f"\n{P} ok / {F} NG"); sys.exit(1 if F else 0)
