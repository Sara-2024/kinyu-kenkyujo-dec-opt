"""初回の設定（Phase 1）を、MT5 も Windows も無いところで確かめる。

にせの MT5 データフォルダを作って、

  ・PC の中の MT5 を全部見つけられるか
  ・EA の状態（未設置／最新／要更新）を正しく言えるか
  ・置き直しが必要なときだけ置くか
  ・すでに使っているお客様を CONNECTED として引き継げるか
  ・連携が済むまで通信を始めない歯止めが効いているか

を見る。実行: python3 bridge/tests/phase1_test.py
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile

BRIDGE = pathlib.Path(__file__).resolve().parent.parent
ROOT = BRIDGE.parent
sys.path.insert(0, str(BRIDGE))

WORK = tempfile.mkdtemp(prefix="aitrader-phase1-")
os.environ["LOCALAPPDATA"] = str(pathlib.Path(WORK) / "AppDataLocal")
os.environ["APPDATA"] = str(pathlib.Path(WORK) / "AppDataRoaming")

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


# ── にせの MT5 を用意する ────────────────────────────
def make_terminal(folder_id: str, install_name: str, encoding: str = "utf-16") -> pathlib.Path:
    """AppData 配下の MT5 データフォルダを1つ作る。"""
    base = pathlib.Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / folder_id
    (base / "MQL5" / "Experts").mkdir(parents=True, exist_ok=True)
    (base / "MQL5" / "Include").mkdir(parents=True, exist_ok=True)
    install = pathlib.Path(WORK) / "Program Files" / install_name
    install.mkdir(parents=True, exist_ok=True)
    (install / "terminal64.exe").write_text("", encoding="utf-8")
    # MT5 は origin.txt を UTF-16 で書く。片方はわざと UTF-8 にして、
    # どちらでも検出が止まらないことを見る
    (base / "origin.txt").write_text(str(install), encoding=encoding)
    return base


hfm = make_terminal("A" * 32, "HFM MetaTrader 5")
xm = make_terminal("B" * 32, "XM MT5", encoding="utf-8")

import connect_state  # noqa: E402
import ea_manager  # noqa: E402
import mt5_detect  # noqa: E402

# ── 1) MT5 を全部見つけられる（起動もログインも不要） ──
terminals = mt5_detect.list_terminals()
check("MT5 を2台とも見つける", len(terminals) == 2, str(mt5_detect.describe(terminals)))
labels = sorted(t.label for t in terminals)
check("ブローカー名を出せる", labels == ["HFM", "XM"], str(labels))
check("データフォルダを持っている", all(t.data_path.is_dir() for t in terminals))

# ── 2) 配布物（同梱の EA）を読める ──
source = ea_manager.load_source(BRIDGE)
check("同梱の EA を読める", source is not None)
if source is None:
    print("\n配布物が読めないので以降は省略")
    sys.exit(1)
check("EA の版を読める", bool(source.version), source.version)
check("EA の名前は変えていない", source.file_name == "OrbitGoldEA_v6.mq5", source.file_name)
check("Include も同梱している", len(source.includes) == 1, str(source.includes))

# ── 3) 置く前は「未設置」 ──
st = ea_manager.status(hfm, source)
check("置く前は未設置", st.state == ea_manager.NOT_INSTALLED, st.state)
check("未設置なら置く必要あり", st.needs_install)

# ── 4) 置くと「最新」になる ──
after = ea_manager.install(hfm, source, old_names=("TrelabEA", "OrbitGoldEA_v5"))
check("置いたあとは最新", after.state == ea_manager.LATEST, after.as_dict())
check("EA が置かれている", (hfm / "MQL5" / "Experts" / source.file_name).is_file())
check("Include も置かれている", (hfm / "MQL5" / "Include" / "TradingGate.mqh").is_file())
check("もう置く必要は無い", not after.needs_install)

# ── 5) 中身が古いと「要更新」。無条件に上書きしない ──
target = hfm / "MQL5" / "Experts" / source.file_name
target.write_text("古い中身", encoding="utf-8")
st = ea_manager.status(hfm, source)
check("中身が違えば要更新", st.state == ea_manager.UPDATE_AVAILABLE, st.state)
again = ea_manager.install(hfm, source)
check("更新すると最新に戻る", again.state == ea_manager.LATEST, again.state)

# ── 6) Include だけ消えても気づく（EA だけ新しくても動かないため） ──
(hfm / "MQL5" / "Include" / "TradingGate.mqh").unlink()
check("Include が欠けたら要更新", ea_manager.status(hfm, source).state == ea_manager.UPDATE_AVAILABLE)
ea_manager.install(hfm, source)
check("入れ直すと最新", ea_manager.status(hfm, source).state == ea_manager.LATEST)

# ── 7) 古い版の EA は片づける。今の EA は消さない ──
experts = hfm / "MQL5" / "Experts"
(experts / "OrbitGoldEA_v5.mq5").write_text("古い版", encoding="utf-8")
removed = ea_manager.cleanup_old(experts, ("OrbitGoldEA_v5",))
check("古い版を片づける", removed == ["OrbitGoldEA_v5.mq5"], str(removed))
check("いまの EA は残る", (experts / source.file_name).is_file())

# ── 8) 触っていない MT5 は未設置のまま（勝手に全部へ置かない） ──
check("選ばなかった MT5 は未設置のまま", ea_manager.status(xm, source).state == ea_manager.NOT_INSTALLED)

# ── 9) 状態は既定で INSTALL_ONLY ──
check("最初は INSTALL_ONLY", connect_state.current() == connect_state.INSTALL_ONLY, connect_state.current())
check("最初はつながらない", not connect_state.is_connected())

# ── 10) サイトから連携されたときだけ CONNECTED ──
connect_state.mark_connected("11111111-2222-4333-8444-555555555555")
check("連携すると CONNECTED", connect_state.is_connected())
connect_state.mark_install_only("試験")
check("解除すると INSTALL_ONLY に戻る", not connect_state.is_connected())

# ── 11) すでに使っているお客様を引き継ぐ ──
connect_state.state_path().unlink()
check("記録が無ければ INSTALL_ONLY 扱い", connect_state.current() == connect_state.INSTALL_ONLY)
check("既定の部屋では引き継がない", not connect_state.adopt_legacy("vps-01"))
connect_state.state_path().unlink(missing_ok=True)
check("会員IDがあれば引き継ぐ", connect_state.adopt_legacy("11111111-2222-4333-8444-555555555555"))
check("引き継いだら CONNECTED", connect_state.is_connected())
check("二度目は引き継がない", not connect_state.adopt_legacy("11111111-2222-4333-8444-555555555555"))

# ── 12) 連携前はブリッジを起動しない（最後の歯止め） ──
sys.path.insert(0, str(ROOT))
import ast  # noqa: E402

tree = ast.parse((ROOT / "connect.py").read_text(encoding="utf-8"))
start_bridge = next(
    (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "start_bridge"), None
)
check("start_bridge がある", start_bridge is not None)
if start_bridge is not None:
    body = ast.dump(start_bridge)
    check("先頭で連携を確かめている", "is_connected" in body)
    first = start_bridge.body[0]
    check("確かめてから他のことをする", isinstance(first, ast.If) and "is_connected" in ast.dump(first))

# 引数なしで開いたら、初回の設定だけをするようになっているか
main = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
check("main がある", main is not None)
if main is not None:
    dumped = ast.dump(main)
    check("初回は setup_phase1 を通る", "setup_phase1" in dumped)
    check("引き継ぎも見ている", "adopt_legacy" in dumped)

shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
