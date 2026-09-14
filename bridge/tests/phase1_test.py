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


def make_mt4(folder_id: str, install_name: str) -> pathlib.Path:
    """MT4 のデータフォルダ。MetaQuotes\\Terminal には MT5 と一緒に並んでいる。"""
    base = pathlib.Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / folder_id
    (base / "MQL4" / "Experts").mkdir(parents=True, exist_ok=True)
    install = pathlib.Path(WORK) / "Program Files" / install_name
    install.mkdir(parents=True, exist_ok=True)
    (install / "terminal.exe").write_text("", encoding="utf-8")
    (base / "origin.txt").write_text(str(install), encoding="utf-16")
    return base


make_mt4("C" * 32, "XM Global MT4")
make_mt4("D" * 32, "Myfx Markets 4")

import connect_state  # noqa: E402
import ea_manager  # noqa: E402
import mt5_detect  # noqa: E402


def make_assets(version: str = "6.10", *, sha_ok: bool = True, ea_body: bytes = b"EX5-BODY-v6.10") -> pathlib.Path:
    """にせの配布物（コンパイル済み EA ＋ 控え）を作る。

    本物の .ex5 は Windows でコンパイルしないと作れないので、試験では中身を
    でっち上げる。ea_manager は中身を解釈せず、SHA-256 だけを見ている。
    """
    import hashlib
    import json

    assets = pathlib.Path(tempfile.mkdtemp(prefix="assets-", dir=WORK))
    ea = assets / "3YumekkuEA_win.ex5"
    ea.write_bytes(ea_body)
    (assets / "TradingGate.mqh").write_text("// 共通部品", encoding="utf-8")
    digest = hashlib.sha256(ea_body).hexdigest()
    (assets / "ea_manifest.json").write_text(
        json.dumps({"ea": "3YumekkuEA_win", "file": ea.name, "version": version,
                    "sha256": digest if sha_ok else "0" * 64}),
        encoding="utf-8",
    )
    return assets

# ── 1) MT5 を全部見つけられる（起動もログインも不要） ──
terminals = mt5_detect.list_terminals()
check("MT5 を2台とも見つける", len(terminals) == 2, str(mt5_detect.describe(terminals)))
check("MT4 は混ぜない", all("MT4" not in t.label and "Myfx" not in t.label for t in terminals),
      str([t.label for t in terminals]))
check("MQL5 があるものだけ", all((t.data_path / "MQL5").is_dir() for t in terminals))
labels = sorted(t.label for t in terminals)
check("ブローカー名を出せる", labels == ["HFM", "XM"], str(labels))
check("データフォルダを持っている", all(t.data_path.is_dir() for t in terminals))

# ── 2) 配布物（同梱の EA）を読める ──
assets = make_assets()
source = ea_manager.load_source(assets)
check("配布物を読める", source is not None)
if source is None:
    print("\n配布物が読めないので以降は省略")
    sys.exit(1)
check("配るのはコンパイル済み", source.file_name == "3YumekkuEA_win.ex5", source.file_name)
check("版は控えから読む", source.version == "6.10", source.version)
check("SHA-256 が合っている", source.ok, source.broken)
check("Include も同梱している", len(source.includes) == 1, str(source.includes))
check("お客様のPCでコンパイルしない", not ea_manager.needs_compile())

# 中身が控えと違う配布物は使わない
bad = ea_manager.load_source(make_assets(sha_ok=False))
check("中身が控えと違えば使わない", bad is not None and not bad.ok, str(bad.broken if bad else None))
st_bad = ea_manager.install(xm, bad) if bad else None
check("壊れた配布物は置かない", st_bad is not None and st_bad.state == ea_manager.ERROR)
check("壊れていたら何も置かれない", not (xm / "MQL5" / "Experts" / "3YumekkuEA_win.ex5").is_file())

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
target.write_bytes(b"EX5-BODY-v6.00")
st = ea_manager.status(hfm, source)
check("中身が違えば要更新", st.state == ea_manager.UPDATE_AVAILABLE, st.state)
again = ea_manager.install(hfm, source)
check("更新すると最新に戻る", again.state == ea_manager.LATEST, again.state)
check("置いた版が分かる", again.installed_version == "6.10", again.installed_version)

# 新しい版の配布物に差し替えたら、更新が要ると分かる
newer = ea_manager.load_source(make_assets(version="6.20", ea_body=b"EX5-BODY-v6.20"))
st = ea_manager.status(hfm, newer)
check("新しい版が来たら要更新", st.state == ea_manager.UPDATE_AVAILABLE, st.state)
check("入っている版も言える", st.installed_version == "6.10", st.installed_version)
check("配布物の版も言える", st.source_version == "6.20", st.source_version)
after_new = ea_manager.install(hfm, newer)
check("新しい版に入れ替わる", after_new.state == ea_manager.LATEST and after_new.installed_version == "6.20",
      after_new.as_dict())
ea_manager.install(hfm, source)  # 元に戻しておく

# 控えは「最新」でも、実ファイルが別物なら最新と言わない
#（お客様が手で .ex5 を差し替えた場合。控えを信じると嘘をつく）
check("この時点では最新", ea_manager.status(hfm, source).state == ea_manager.LATEST)
record = ea_manager.read_record(hfm)
check("控えは最新版のまま", record.get("version") == "6.10" and record.get("sha256") == source.sha256)
(hfm / "MQL5" / "Experts" / source.file_name).write_bytes(b"HAND-REPLACED")
swapped = ea_manager.status(hfm, source)
check("実ファイルが別物なら最新と言わない", swapped.state == ea_manager.UPDATE_AVAILABLE, swapped.as_dict())
check("控えの版は使わない", swapped.installed_version == "", swapped.installed_version)
check("入れ替えられたことが分かる", "入れ替え" in swapped.detail, swapped.detail)
check("控え自体は残っている", ea_manager.read_record(hfm).get("sha256") == source.sha256)
ea_manager.install(hfm, source)
check("置き直せば最新に戻る", ea_manager.status(hfm, source).state == ea_manager.LATEST)

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
ea_manager.cleanup_old(experts, ("3YumekkuEA_win",))
check("取り違えても今の EA は消さない", (experts / source.file_name).is_file())

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

# ── 13) リポジトリに置いてある本物の配布物（あれば）を確かめる ──
real_ea = BRIDGE / "3YumekkuEA_win.ex5"
real_manifest = BRIDGE / "ea_manifest.json"
if real_ea.is_file() and real_manifest.is_file():
    real = ea_manager.load_source(BRIDGE)
    check("同梱の EA が控えと一致している", real is not None and real.ok, str(real.broken if real else None))
    check("同梱の EA に版が入っている", bool(real and real.version), str(real.version if real else ""))
elif real_ea.is_file() or real_manifest.is_file():
    check("EA と控えは両方そろえる", False, "片方しかない")
else:
    print("  --   コンパイル済みの EA はまだ置かれていません")
    print("       Windows で MetaEditor コンパイル → py -3 tools/make-ea-manifest.py")

shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
