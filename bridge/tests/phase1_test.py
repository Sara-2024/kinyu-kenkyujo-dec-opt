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
from mt5_terminal import EA_NAMES  # noqa: E402  いま配る名前（変わりうる）
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

# ── 1-2) 選択画面に口座番号が出るか ────────────────
#  「HFM」「4」では、お客様はどれを選べばいいか分からない。
#  MT5 のログから口座番号とサーバー名を読む。ログの文字コードは環境で変わる。
_LOGIN_LINE = (
    "CP\t0\t13:39:29.995\tNetwork\t'75602463': authorized on "
    "HFMarketsGlobal-Demo4 through Access Server (ping: 151 ms)\n"
)
for enc in ("utf-8", "utf-16-le", "utf-16", "cp932"):
    probe = pathlib.Path(tempfile.mkdtemp(prefix="log-", dir=WORK))
    (probe / "logs").mkdir()
    (probe / "logs" / "20260914.log").write_bytes(_LOGIN_LINE.encode(enc))
    label = mt5_detect.broker_label(pathlib.Path("MetaTrader 5"), probe)
    check(f"{enc} のログから口座番号を出せる", "75602463" in label, label)
    check(f"{enc} のログからサーバー名も出せる", "HFMarketsGlobal-Demo4" in label, label)

# ログイン行がファイルの先頭にあり、後ろが長くても拾えること
probe = pathlib.Path(tempfile.mkdtemp(prefix="log-big-", dir=WORK))
(probe / "logs").mkdir()
(probe / "logs" / "20260914.log").write_text(
    _LOGIN_LINE + "Network\tnoise\n" * 40000, encoding="utf-8"
)
check("ログが長くても先頭の行を拾う", "75602463" in mt5_detect.broker_label(pathlib.Path("MetaTrader 5"), probe))

# ログが無ければ、これまでどおりフォルダ名
probe = pathlib.Path(tempfile.mkdtemp(prefix="log-none-", dir=WORK))
check("ログが無ければフォルダ名", mt5_detect.broker_label(pathlib.Path("HFM MetaTrader 5"), probe) == "HFM")

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

# 前の名前の .ex5 が残っていても、いま配る名前のものを選ぶ
mixed = pathlib.Path(tempfile.mkdtemp(prefix="mixed-", dir=WORK))
(mixed / "TradingGate.mqh").write_text("// 共通部品", encoding="utf-8")
# 名前は変わりうるので、決め打ちにせず「いま配る名前」で組み立てる
CURRENT_EA = f"{EA_NAMES[0]}.ex5"
OLD_EA = "YumekkuEA_mukashi.ex5"
old_body = b"EX5-OLD-NAME-NEWER"
(mixed / OLD_EA).write_bytes(old_body)
import time as _t

_t.sleep(0.01)
(mixed / CURRENT_EA).write_bytes(b"EX5-CURRENT")
# 古いほうを、あとから触って「新しい」ことにする
import os as _os

_os.utime(mixed / OLD_EA, None)
picked = ea_manager.find_source_file(mixed)
check("前の名前が新しくても、いま配る名前を選ぶ", picked is not None and picked.name == CURRENT_EA,
      str(picked.name if picked else None))

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

# ── 7-2) MT5 のサンプルだけを片づける（お客様の EA は消さない）──
experts2 = hfm / "MQL5" / "Experts"
(experts2 / "Advisors").mkdir(parents=True, exist_ok=True)
(experts2 / "Free Robots").mkdir(parents=True, exist_ok=True)
(experts2 / "Advisors" / "ExpertMACD.ex5").write_text("sample", encoding="utf-8")
(experts2 / "Free Robots" / "SomeFreeRobot.ex5").write_text("sample", encoding="utf-8")
(experts2 / "お客様が買ったEA.ex5").write_text("mine", encoding="utf-8")
(experts2 / "MyFolder").mkdir(exist_ok=True)
(experts2 / "MyFolder" / "BoughtEA.ex5").write_text("mine", encoding="utf-8")

gone = ea_manager.tidy_samples(hfm)
check("サンプルを片づける", len(gone) == 2, str(gone))
check("Advisors フォルダごと消える", not (experts2 / "Advisors").exists())
check("Free Robots も消える", not (experts2 / "Free Robots").exists())
check("直下のお客様の EA は残る", (experts2 / "お客様が買ったEA.ex5").is_file())
check("よそのフォルダは触らない", (experts2 / "MyFolder" / "BoughtEA.ex5").is_file())
check("うちの EA は残る", (experts2 / source.file_name).is_file())

# サンプルのフォルダに、うちのシステムが紛れていたら触らない
(experts2 / "Advisors").mkdir(exist_ok=True)
(experts2 / "Advisors" / "ExpertMACD.ex5").write_text("sample", encoding="utf-8")
(experts2 / "Advisors" / "YumekkuEA_old.ex5").write_text("ours", encoding="utf-8")
gone2 = ea_manager.tidy_samples(hfm)
check("うちのが混ざっていたら、そのフォルダは触らない", gone2 == [] and (experts2 / "Advisors" / "ExpertMACD.ex5").is_file(), str(gone2))
import shutil as _sh
_sh.rmtree(experts2 / "Advisors", ignore_errors=True)
_sh.rmtree(experts2 / "MyFolder", ignore_errors=True)
(experts2 / "お客様が買ったEA.ex5").unlink()

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

# ── 12-2) 名前の後半が変わっても拾えるか ──────────────
import mt5_terminal  # noqa: E402

for name in ("YumekkuEA_v11", "YumekkuEA_v12_final", "3YumekkuEA_win", "yumekkuea_test"):
    check(f"{name} はうちのシステムと分かる", mt5_terminal.is_our_ea(name))
for name in ("OrbitGoldEA_v11", "TrelabEA", "SomeoneElseEA"):
    check(f"{name} はうちのではない", not mt5_terminal.is_our_ea(name))

# 同梱の .ex5 の名前が変わっても、そのまま配れる
fresh = pathlib.Path(tempfile.mkdtemp(prefix="newname-", dir=WORK))
import hashlib as _h
import json as _j

body = b"EX5-NEW-NAME"
(fresh / "YumekkuEA_v12.ex5").write_bytes(body)
(fresh / "TradingGate.mqh").write_text("// 共通部品", encoding="utf-8")
(fresh / "ea_manifest.json").write_text(
    _j.dumps({"version": "12.00", "sha256": _h.sha256(body).hexdigest()}), encoding="utf-8"
)
newer_src = ea_manager.load_source(fresh)
check("名前が変わった配布物も読める", newer_src is not None and newer_src.file_name == "YumekkuEA_v12.ex5",
      str(newer_src.file_name if newer_src else None))

# 古い版が入っている MT5 に、新しい版を置くと、古い方が片づく
old_ea = xm / "MQL5" / "Experts" / "YumekkuEA_v11.ex5"
old_ea.parent.mkdir(parents=True, exist_ok=True)
old_ea.write_bytes(b"EX5-OLD-NAME")
after_new_name = ea_manager.install(xm, newer_src)
check("新しい名前で置ける", (xm / "MQL5" / "Experts" / "YumekkuEA_v12.ex5").is_file())
check("前の版は片づく", not old_ea.is_file(), "YumekkuEA_v11.ex5 が残っている")
check("置いたあとは最新", after_new_name.state == ea_manager.LATEST, after_new_name.state)

# 他社の EA は消さない
other = xm / "MQL5" / "Experts" / "SomeoneElseEA.ex5"
other.write_bytes(b"OTHER")
ea_manager.install(xm, newer_src)
check("よその EA は消さない", other.is_file())

# 後片づけ（このあとの検査に影響させない）
for p_ in (xm / "MQL5" / "Experts").glob("*"):
    p_.unlink()

# ── 13) リポジトリに置いてある本物の配布物（あれば）を確かめる ──
# 名前は変わりうるので、決め打ちにせず Yumekku で探す
real_ea = ea_manager.find_source_file(BRIDGE)
real_manifest = BRIDGE / "ea_manifest.json"
if real_ea is not None and real_manifest.is_file():
    real = ea_manager.load_source(BRIDGE)
    check("同梱の EA が控えと一致している", real is not None and real.ok, str(real.broken if real else None))
    check("同梱の EA に版が入っている", bool(real and real.version), str(real.version if real else ""))
    # 名前が食い違うと、配る側と受け取る側で別のファイルを見てしまう
    check("控えの名前と実ファイルが一致", real_ea.stem == _j.loads(real_manifest.read_text(encoding="utf-8"))["ea"],
          f"{real_ea.stem} / {real_manifest.name}")
    check("いま配る名前と一致", real_ea.stem == EA_NAMES[0], f"{real_ea.stem} ≠ {EA_NAMES[0]}")
    # 2つ置いてあると、どちらが配られるのか分からなくなる
    ours = [q.name for q in BRIDGE.glob("*.ex5") if ea_manager.is_our_ea(q.stem)]
    check("同梱の EA は1つだけ", len(ours) == 1, str(ours))
    # 版は .ex5 そのものから読めること（ソースは配らない）
    check("版は .ex5 から読める", bool(ea_manager.version_from_ex5(real_ea)), ea_manager.version_from_ex5(real_ea))
elif real_ea is not None or real_manifest.is_file():
    check("EA と控えは両方そろえる", False, "片方しかない")
else:
    print("  --   コンパイル済みの EA はまだ置かれていません")
    print("       Windows で MetaEditor コンパイル → py -3 tools/make-ea-manifest.py")


# ── 14) EA がチャートで動いているか（設置のあとの案内に使う）──
import os as _os
import time as _time

beat = ea_manager.heartbeat()
check("控えが無ければ「動いていない」", beat["seen"] is False and beat["fresh"] is False, str(beat))

common = pathlib.Path(_os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / "Common" / "Files"
common.mkdir(parents=True, exist_ok=True)
state_ini = common / ea_manager.HEARTBEAT_FILE
state_ini.write_text("ea=YumekkuEA_v11\nstate=1\nsymbol=XAUUSD\n", encoding="utf-8")

beat = ea_manager.heartbeat()
check("いま書かれていれば「動いている」", beat["fresh"] is True, str(beat))
check("載っている銘柄が読める", beat["symbol"] == "XAUUSD", str(beat))
check("EA の名前が読める", beat["ea"] == "YumekkuEA_v11", str(beat))

# 古い控え（チャートから外された・MT5 が止まった）
old_time = _time.time() - 600
_os.utime(state_ini, (old_time, old_time))
beat = ea_manager.heartbeat()
check("古ければ「止まっている」", beat["seen"] is True and beat["fresh"] is False, str(beat))

# MQL5 の書き出しは環境によって文字コードが変わる
state_ini.write_bytes("ea=YumekkuEA_v11\nstate=1\nsymbol=GOLD\n".encode("utf-16"))
beat = ea_manager.heartbeat()
check("別の文字コードでも読める", beat["symbol"] == "GOLD", str(beat))

# ── 15) 設置のあとの案内（「もう入っています」で終わらせない）──
import connect  # noqa: E402


class FakeUI:
    """画面のかわり。押されたボタンと、出た文字を覚えるだけ。"""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []
        self.finished = None

    def alive(self):
        return True

    def ask(self, question, yes, no, lines=()):
        self.asked.append((question, list(lines)))
        return self.answers.pop(0) if self.answers else False

    def finish(self, lines, ok=True):
        self.finished = list(lines)


# 動いていれば、案内を出さずに終わる
ui = FakeUI([])
connect.guide_after_install(ui, placed=ea_manager.LATEST, shown="GOLD", needs_restart=False)
check("動いていれば操作をお願いしない", ui.asked == [], str(ui.asked))
check("動いていれば終わりの画面を出す", ui.finished is not None)
check("どこで動いているか言う", any("GOLD" in l for l in (ui.finished or [])), str(ui.finished))

# 止まっていれば、次の一手を出す
old_time = _time.time() - 600
_os.utime(state_ini, (old_time, old_time))
ui = FakeUI([False])
connect.guide_after_install(ui, placed=ea_manager.LATEST, shown="GOLD", needs_restart=True)
check("止まっていれば操作をお願いする", len(ui.asked) == 1, str(ui.asked))
steps = "\n".join(ui.asked[0][1]) if ui.asked else ""
check("ナビゲーターの案内が出る", "ナビゲーター" in steps, steps)
check("1分足と書いてある", "1分足" in steps, steps)
check("アルゴ取引のボタンを案内する", "アルゴ取引" in steps, steps)
check("開き直しの案内が出る", "開き直" in steps, steps)
for word in ("MQL5", "Experts", "ブリッジ", "API", "Python", "token", "SHA"):
    check(f"専門用語を出さない: {word}", word not in steps, steps)

# 「できたので確かめる」を押したら、その場でもう一度見る
pressed = {"n": 0}
real_heartbeat = ea_manager.heartbeat


def fake_heartbeat(fresh_sec=ea_manager.HEARTBEAT_FRESH_SEC):
    pressed["n"] += 1
    if pressed["n"] == 1:
        return {"seen": True, "fresh": False, "age": 600, "ea": "", "symbol": ""}
    return {"seen": True, "fresh": True, "age": 1, "ea": "YumekkuEA_v11", "symbol": "XAUUSD"}


ea_manager.heartbeat = fake_heartbeat
ui = FakeUI([True])
connect.guide_after_install(ui, placed=ea_manager.LATEST, shown="", needs_restart=False)
ea_manager.heartbeat = real_heartbeat
check("押したらもう一度確かめる", pressed["n"] == 2, str(pressed))
check("できていれば先へ進む", ui.finished is not None and any("XAUUSD" in l for l in ui.finished), str(ui.finished))


# ── 16) すでに入っているときの画面（「いま入っているのはこれです」）──
class Term:
    def __init__(self, label, data_path):
        self.label = label
        self.data_path = data_path
        self.exe = None


class MenuUI(FakeUI):
    def __init__(self, answers, menu_answers=()):
        super().__init__(answers)
        self.menus = []
        self.menu_answers = list(menu_answers)

    def menu(self, title, lines=(), options=()):
        self.menus.append((title, list(lines), list(options)))
        return self.menu_answers.pop(0) if self.menu_answers else None


term = Term("XMTrading-MT5 3（口座 75602463）", xm)
st_latest = ea_manager.Status(ea_manager.LATEST, installed_version="v11", source_version="v11")

# まだチャートに載せていないとき
state_ini.unlink(missing_ok=True)
ui = MenuUI([], ["use"])
connect.ask_what_to_do(ui, term, st_latest, can_switch=False)
title, lines, options = ui.menus[0]
body = "\n".join(lines)
check("すでに入っていることを伝える", "すでに" in title, title)
check("入っている版を出す", "v11" in body, body)
check("どのMT5に入れたか出す", "75602463" in body, body)
check("まだ載せていないことを伝える", "まだチャートに載せていません" in body, body)
keys = [k for k, _ in options]
check("このまま使うを選べる", "use" in keys, str(keys))
check("設置しなおすを選べる", "again" in keys, str(keys))
check("MT5が1台なら選び直しは出さない", "other" not in keys, str(keys))

# 動いているとき／MT5 が複数あるとき
state_ini.write_text("ea=YumekkuEA_v11\nstate=1\nsymbol=XAUUSD\n", encoding="utf-8")
ui = MenuUI([], ["use"])
connect.ask_what_to_do(ui, term, st_latest, can_switch=True)
title, lines, options = ui.menus[0]
body = "\n".join(lines)
check("動いていることを伝える", "XAUUSD" in body and "動いています" in body, body)
check("MT5が複数なら選び直しを出す", "other" in [k for k, _ in options], str(options))

# ボタンの文字に専門用語を出さない
labels = " ".join(l for _, l in options)
for word in ("MQL5", "Experts", "EA", "API", "Python"):
    check(f"ボタンに専門用語を出さない: {word}", word not in labels, labels)

# 「設置しなおす」は、中身が同じでも本当に置き直す
target_ea = xm / "MQL5" / "Experts" / newer_src.file_name
ea_manager.install(xm, newer_src)
before_mtime = target_ea.stat().st_mtime
_os.utime(target_ea, (before_mtime - 500, before_mtime - 500))
ea_manager.install(xm, newer_src)
check("ふつうは触らない", target_ea.stat().st_mtime == before_mtime - 500)
ea_manager.install(xm, newer_src, force=True)
check("設置しなおすと置き直す", target_ea.stat().st_mtime != before_mtime - 500)
check("置き直しても中身は同じ", ea_manager.sha256_of(target_ea) == newer_src.sha256)


# ── 17) 窓を作れなかったときでも、黙って終わらない ──
#    tkinter を積み忘れた exe を作ってしまうと、お客様には
#    「ダブルクリックしても何も起きない」としか見えない。
import installer_ui  # noqa: E402

shown_boxes = []
real_box = installer_ui.message_box
installer_ui.message_box = lambda text, title=installer_ui.APP_NAME: (shown_boxes.append(text), True)[1]

connect.tell(None, "MT5が見つかりませんでした。", "MT5を開いてから、もう一度お試しください。")
check("窓が無くても知らせる", len(shown_boxes) == 1, str(shown_boxes))
check("次にやることも伝える", "もう一度" in shown_boxes[0], str(shown_boxes))

shown_boxes.clear()
state_ini.unlink(missing_ok=True)
connect.guide_after_install(None, placed=ea_manager.LATEST, shown="", needs_restart=False)
check("窓が無くても案内する", len(shown_boxes) == 1, str(shown_boxes))
check("窓が無くても手順を出す", "ナビゲーター" in shown_boxes[0], str(shown_boxes))

installer_ui.message_box = real_box
check("Windows以外では小さな画面を出さない", installer_ui.message_box("x") is False)

shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
