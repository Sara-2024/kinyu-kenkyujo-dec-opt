"""初回の設定（Phase 1）が、本当にオフラインで完結するかを通しで確かめる。

にせの MT5 を置いたうえで、

  ・通信しようとしたらその場で落ちる（socket を塞ぐ）
  ・別のプログラムを起こそうとしたらその場で落ちる（ブリッジが起きないこと）

という縛りをかけて setup_phase1() を最後まで走らせる。
ここが通るかぎり、配布直後のアプリはサイトに触らない。

実行: python3 bridge/tests/phase1_offline_test.py
"""
import os, pathlib, shutil, socket, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
WORK = tempfile.mkdtemp(prefix="aitrader-e2e-")
os.environ["LOCALAPPDATA"] = str(pathlib.Path(WORK) / "Local")
os.environ["APPDATA"] = str(pathlib.Path(WORK) / "Roaming")

# にせの MT5 を2台
def make(fid, name):
    base = pathlib.Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / fid
    (base / "MQL5" / "Experts").mkdir(parents=True, exist_ok=True)
    (base / "MQL5" / "Include").mkdir(parents=True, exist_ok=True)
    inst = pathlib.Path(WORK) / "PF" / name
    inst.mkdir(parents=True, exist_ok=True)
    (inst / "terminal64.exe").write_text("")
    (base / "origin.txt").write_text(str(inst), encoding="utf-16")
    return base
hfm = make("A"*32, "HFM MetaTrader 5")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bridge"))

# 通信を一切させない。開こうとしたらその場で落ちる
class NoNet(socket.socket):
    def __init__(self, *a, **k):
        raise AssertionError("Phase 1 で通信しようとした")
socket.socket = NoNet  # type: ignore
# 外のプログラムも起こさせない
def no_spawn(*a, **k):
    raise AssertionError(f"Phase 1 で別のプログラムを起動しようとした: {a}")

import connect
connect.spawn_hidden = no_spawn
connect.run_hidden = no_spawn            # 外のプログラムは一切起こさない
connect.installer_ui.open_window = lambda: None  # 画面は出さない

# 配る EA（コンパイル済み）をでっち上げて、同梱物の置き場として渡す。
# 本物の .ex5 は Windows でコンパイルしないと作れないため。
import hashlib, json  # noqa: E402
ASSETS = pathlib.Path(WORK) / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)
BODY = b"EX5-BODY-for-test"
(ASSETS / "3YumekkuEA_win.ex5").write_bytes(BODY)
(ASSETS / "TradingGate.mqh").write_text("// 共通部品", encoding="utf-8")
(ASSETS / "ea_manifest.json").write_text(json.dumps({
    "ea": "3YumekkuEA_win", "file": "3YumekkuEA_win.ex5", "version": "6.10",
    "sha256": hashlib.sha256(BODY).hexdigest()}), encoding="utf-8")
REAL_ASSETS = connect.BRIDGE_DIR
connect.BRIDGE_DIR = ASSETS

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  ok   {name}")
    else: fail += 1; print(f"  NG   {name} {extra}")

# 古い版が登録した自動起動が残っている状態にしておく
#（Windows のレジストリは触れないので、読み書きの入口を身代わりにする）
removed: list[str] = []
connect.startup_command = lambda: r'"C:\Users\x\Downloads\AITrader.exe" "--silent" "--startup"'
connect.unregister_startup = lambda why="": (removed.append(why), True)[1]

code = connect.setup_phase1()
check("初回の設定が成功で終わる", code == 0, f"code={code}")
check("古い自動起動の登録を片づける", removed == ["まだ連携していない"], str(removed))
connect.startup_command = lambda: ""

ea = hfm / "MQL5" / "Experts" / "3YumekkuEA_win.ex5"
inc = hfm / "MQL5" / "Include" / "TradingGate.mqh"
check("コンパイル済みの EA が置かれた", ea.is_file())
check("Include が置かれた", inc.is_file())
check("EA の中身が配布物と同じ", ea.read_bytes() == BODY)
check("ソース(.mq5)は置かない", not (hfm / "MQL5" / "Experts" / "3YumekkuEA_win.mq5").is_file())

import connect_state
check("状態は INSTALL_ONLY", connect_state.current() == "INSTALL_ONLY", connect_state.current())
check("つながっていない", not connect_state.is_connected())

cfg = pathlib.Path(os.environ["LOCALAPPDATA"]) / "AITrader"
check("bridge.env を作っていない", not (cfg / "bridge.env").is_file(),
      str(sorted(p.name for p in cfg.iterdir())))
log = (cfg / "connect.log").read_text(encoding="utf-8") if (cfg/"connect.log").is_file() else ""
check("記録は残る", "初回の設定が終わりました" in log)
check("サイトのURLを記録にも出していない", "kinyu" not in log and "onrender" not in log)

# もう一度動かしても、置き直さない（最新なので触らない）
before = ea.stat().st_mtime_ns
code2 = connect.setup_phase1()
check("2回目も成功", code2 == 0)
check("最新なら置き直さない", ea.stat().st_mtime_ns == before)

# 連携していない状態でブリッジを起こそうとしても、起きない
connect.start_bridge(None)   # no_spawn が呼ばれたら AssertionError で落ちる
check("連携前はブリッジを起動しない", True)

# ── MT5 が動いていないときに、MT5 を起こしてしまわない ──
#   mt5.initialize() は、MT5 が止まっていると自分で起動してしまう。
#   「動いているか」はプロセス一覧で見て、止まっていれば MT5 に触らない
import gold_symbol  # noqa: E402
touched = []
real_show = gold_symbol.show_in_market_watch
gold_symbol.show_in_market_watch = lambda exe=None, log=None: (touched.append(str(exe)), "")[1]
connect.mt5_pids = lambda exe: []          # 止まっている
code4 = connect.setup_phase1()
check("MT5 が止まっていても設定は成功", code4 == 0, f"code={code4}")
check("止まっている MT5 に触らない（起こさない）", touched == [], str(touched))
connect.mt5_pids = lambda exe: [4242]      # 動いている
code5 = connect.setup_phase1()
check("動いていれば気配値に出しに行く", len(touched) == 1, str(touched))
gold_symbol.show_in_market_watch = real_show
connect.mt5_pids = lambda exe: []

# ── 開き直しは、隠しウィンドウで起こさない ──
#   spawn_hidden は「窓を出さない」指定つき。MT5 に使うと画面に出てこない
class T:
    exe = pathlib.Path(WORK) / "PF" / "HFM MetaTrader 5" / "terminal64.exe"
launched = []
connect.launch_mt5 = lambda exe: launched.append(str(exe))
connect.mt5_pids = lambda exe: [4242]
connect.wait_gone = lambda pid, seconds=10.0, tick=None: True
connect.run_hidden = lambda *a, **k: 0    # taskkill の身代わり
ticks = []
restarted = connect.restart_mt5(T(), tick=lambda: ticks.append(1))
check("開き直しは launch_mt5 で起こす（spawn_hidden ではない）", restarted and launched == [str(T.exe)], str(launched))
check("待っているあいだ画面を動かす", len(ticks) > 0, str(len(ticks)))
connect.run_hidden = no_spawn
connect.mt5_pids = lambda exe: []

# 同梱の EA が無いときは、何もせずに案内して終わる（壊れたまま置かない）
empty = pathlib.Path(WORK) / "empty"
empty.mkdir(exist_ok=True)
connect.BRIDGE_DIR = empty
shutil.rmtree(hfm / "MQL5", ignore_errors=True)
code3 = connect.setup_phase1()
check("配布物が無ければ失敗で終わる", code3 == 1, f"code={code3}")
check("配布物が無ければ何も置かない", not (hfm / "MQL5" / "Experts").exists())
connect.BRIDGE_DIR = ASSETS

shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{ok} ok / {fail} NG")
sys.exit(1 if fail else 0)
