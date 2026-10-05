"""Mac 版の入口（connect_mac.py）が、Windows 版の本体を正しく差し替えて動くかを確かめる。

    python3 bridge/tests/connect_mac_test.py

Mac も MT5 も要らない。一時フォルダに Wine の中身のふりをしたフォルダを作り、
  ・MT5 を探せる（業者ごとの Wine を区別し、口座番号をログから拾う）
  ・EA の控えがある MT5 を「ログイン済み」とみなす。選んだ MT5 以外には繋がない
  ・Windows 向けの部品（ea_manager / mt5_terminal）が、向けた MT5 を見る
  ・自動起動（LaunchAgent）を書ける・消せる
  ・連携前はブリッジを起こさない（歯止めは共通）
  ・配布の定義（build-mac.sh / launcher / workflow / connector.ts）がずれていない
を見る。
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BRIDGE = ROOT / "bridge"

# 本物の ~/Library を触らないよう、HOME を一時フォルダにしてから読み込む
HOME = pathlib.Path(tempfile.mkdtemp(prefix="trelab-machome-"))
os.environ["HOME"] = str(HOME)
os.environ["LOCALAPPDATA"] = str(HOME / "Library" / "Application Support" / "MT5Automatic")
os.environ.pop("APPDATA", None)
os.environ.pop("TRELAB_FILES_DIR", None)
os.environ.pop("TRELAB_DATA_PATH", None)

APP_SUPPORT = HOME / "Library" / "Application Support"


def make_wine(app_id: str, terminal_id: str, *, account: str = "", server: str = "", program: bool = True) -> pathlib.Path:
    prefix = APP_SUPPORT / app_id
    roaming = prefix / "drive_c" / "users" / "mao" / "AppData" / "Roaming"
    data = roaming / "MetaQuotes" / "Terminal" / terminal_id
    (data / "MQL5" / "Experts").mkdir(parents=True)
    (data / "MQL5" / "Include").mkdir(parents=True)
    (roaming / "MetaQuotes" / "Terminal" / "Common" / "Files").mkdir(parents=True)
    if program:
        exe = prefix / "drive_c" / "Program Files" / "MetaTrader 5" / "terminal64.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")
    if account:
        (data / "logs").mkdir()
        line = f"0\t12:00:00.000\tNetwork\t'{account}': authorized on {server}\n"
        (data / "logs" / "20261005.log").write_bytes(line.encode("utf-16-le"))
    return data


XM = make_wine("com.xm.metatrader5", "ABCDEF0123456789ABCDEF0123456789", account="75613879", server="XMTrading-MT5 3")
MQ = make_wine("net.metaquotes.wine.metatrader5", "0123456789ABCDEF0123456789ABCDEF")
make_wine("net.metaquotes.wine.metatrader4", "FFFF", program=True)  # MT4（MQL5 無し）
(APP_SUPPORT / "net.metaquotes.wine.metatrader4" / "drive_c" / "users" / "mao" / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "FFFF" / "MQL5").rename(
    APP_SUPPORT / "net.metaquotes.wine.metatrader4" / "drive_c" / "users" / "mao" / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "FFFF" / "MQL4"
)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BRIDGE))
import connect_mac  # noqa: E402

connect = connect_mac.connect
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


# ── 1) 差し替えが効いている ──
check("MT5 を探す部品が Mac 版になっている", connect.mt5_detect.list_terminals is connect_mac.list_terminals)
check("ログイン済みの判定が Mac 版になっている", connect.find_logged_in_terminal is connect_mac.find_logged_in_terminal)
check("ブリッジの起動が Mac 版になっている", connect.start_bridge is connect_mac.start_bridge)
check("MetaTrader5 として mt5_files が入っている", sys.modules["MetaTrader5"] is connect_mac.mt5_files)
check("設定の置き場が ~/Library/Application Support の下", str(connect.CONFIG_DIR).startswith(str(HOME / "Library")), str(connect.CONFIG_DIR))

# ── 2) MT5 を探す ──
terminals = connect_mac.list_terminals()
labels = [t.label for t in terminals]
check("MT5 が 2 台見つかる（MT4 は除く）", len(terminals) == 2, str(labels))
xm = next((t for t in terminals if t.app_id == "com.xm.metatrader5"), None)
check("業者の Wine を区別できる（XM）", xm is not None and xm.app_label == "XM", str(labels))
check("口座番号とサーバーをログから拾う", xm is not None and xm.account == "75613879" and "XMTrading-MT5 3" in xm.label, str(labels))
check("記録用の 1 行が作れる", "口座 75613879" in connect.mt5_detect.describe(terminals))

# ── 3) EA の控えがある MT5 だけ「ログイン済み」 ──
check("控えが無ければログイン済みは無い", connect.find_logged_in_terminal() is None)
NOW = int(time.time())
account_ini = (
    "login=75613879\nserver=XMTrading-MT5 3\ncurrency=JPY\nbalance=100\nequity=100\ntrade_mode=0\n"
    f"terminal_connected=1\nterminal_trade_allowed=1\nbuild=4620\nserver_time={NOW}\nsymbol=GOLD\nbid=1\nask=1\nfilling=1\nat={NOW}\n"
)
xm_common = xm.common_files
(xm_common / "trelab_account.ini").write_text(account_ini, encoding="utf-8")
session = connect.find_logged_in_terminal()
check("控えがある MT5 を見つける", session is not None and session["account"] == 75613879 and session["data_path"] == str(XM), str(session))
check("部品はその MT5 の Wine を見る（APPDATA）", os.environ.get("APPDATA") == str(xm.roaming), os.environ.get("APPDATA", ""))
check("ファイルの置き場もその MT5", os.environ.get("TRELAB_FILES_DIR") == str(xm_common))
check("選んだ MT5 以外には繋がない", connect.find_logged_in_terminal(prefer_data_path=str(MQ)) is None)
check("選んだ MT5 なら繋ぐ", (connect.find_logged_in_terminal(prefer_data_path=str(XM)) or {}).get("account") == 75613879)

# Windows 向けの部品が、向けた MT5 を見ている
import ea_manager  # noqa: E402

(xm_common / "trelab_state.ini").write_text("state=稼働\nallowed=1\naccount=75613879\nea=YumekkuEA_win\nsymbol=GOLD\n", encoding="utf-8")
beat = ea_manager.heartbeat(account="75613879")
check("EA の動きの控えも、向けた MT5 から読む", beat["fresh"] is True and beat["gold"] is True, str(beat))

# ── 4) EA を置ける（Windows と同じ copy_ea_files） ──
try:
    connect.copy_ea_files(session)
    placed = (XM / "MQL5" / "Experts" / f"{connect.EA_NAME}.ex5").is_file() and (XM / "MQL5" / "Include" / "TradingGate.mqh").is_file()
    check("EA と TradingGate.mqh を Wine の中の MQL5 に置ける", placed)
except SystemExit as exc:
    check("EA と TradingGate.mqh を Wine の中の MQL5 に置ける", False, str(exc))

# ── 5) ブリッジに渡す環境 ──
env = connect.bridge_env(session)
check("ブリッジにファイルの置き場を渡す", env.get("TRELAB_FILES_DIR") == str(xm_common))
check("ブリッジに設定の置き場を渡す", env.get("LOG_FILE", "").startswith(str(connect.CONFIG_DIR)))

# ── 6) 連携前はブリッジを起こさない（歯止めは Windows と同じ） ──
spawned: list[list[str]] = []
connect.spawn_hidden = lambda cmd, cwd=None, env=None: spawned.append(cmd)  # type: ignore[assignment]
connect_mac.start_bridge(session)
check("INSTALL_ONLY のあいだは何も起こさない", spawned == [], str(spawned))

# ── 7) 自動起動（LaunchAgent） ──
ok = connect_mac.register_startup()
plist = connect_mac.agent_path()
check("自動起動の plist を書く", plist.is_file(), str(plist))
check("plist は --startup で起こす", "--startup" in connect_mac.startup_command())
check("plist は本物の ~/Library ではなく試験用の HOME", str(plist).startswith(str(HOME)))
connect_mac.unregister_startup("試験")
check("自動起動の plist を消せる", not plist.exists())
check("URL の登録は .app 任せ（何もしないで True）", connect_mac.register_protocol() is True)

# ── 8) 配布の定義がずれていない ──
build = (ROOT / "tools" / "mac" / "build-mac.sh").read_text(encoding="utf-8")
launcher = (ROOT / "tools" / "mac" / "launcher.applescript").read_text(encoding="utf-8")

# ── Gatekeeper の通し方（macOS 15 で実際に踏んだ 2 つの落とし穴）──
# 1) 書き換えた .app を署名し直さないと「壊れている」扱いになり、許可の道が出ない
check("build-mac.sh は .app をアドホック署名して整合を取る", "codesign --force --deep --sign -" in build)
check("build-mac.sh は署名の整合を確かめてから ZIP にする", "codesign --verify --deep --strict" in build)
# 2) 外側を許可しても、隔離の印が付いた中の本体はその場で強制終了される
check("launcher は本体を Application Support に印なしで写す（cp -X）", "cp -X" in launcher and "application support folder" in launcher)
check("launcher は写しの隔離の印も外す", "xattr -d com.apple.quarantine" in launcher)
check("launcher は動いている写しを直接上書きしない（別名→差し替え）", ".new" in launcher and "mv -f" in launcher)
workflow = (ROOT / ".github" / "workflows" / "build-mac.yml").read_text(encoding="utf-8")
connector = (ROOT / "src" / "data" / "connector.ts").read_text(encoding="utf-8")
check("build-mac.sh は websockets を同梱する", "--hidden-import websockets" in build)
check("build-mac.sh は tkinter を同梱する", "--hidden-import tkinter" in build)
check("build-mac.sh は aitrader:// を Info.plist に書く", '"CFBundleURLSchemes": ["aitrader"]' in build)
check("build-mac.sh は connect.py と bridge/ を同梱する", "connect.py:." in build and ':bridge"' in build)
check("起動ラッパーは URL を本体に渡す", "open location" in launcher and "--from-site" in launcher)
check("起動ラッパーは機種（uname -m）で本体を使い分ける", "uname -m" in launcher and "MT5Automatic-" in launcher)
check("build-mac.sh は本体を機種ごとに作って（--binary）まとめる（--assemble）", "--binary)" in build and "--assemble)" in build)
check("自動ビルドは macOS で回る", "runs-on: macos" in workflow)
check("自動ビルドは Apple シリコンと Intel の両方で本体を作る", "macos-15-intel" in workflow and "arch: arm64" in workflow and "arch: x86_64" in workflow)
check("自動ビルドは 2 機種ぶんそろってから .app にする", "MT5Automatic-x86_64" in workflow and "--assemble" in workflow)
check("自動ビルドの置き場とサイトのダウンロード先が同じ", "public/download/MT5Automatic-mac.zip" in workflow and "/download/MT5Automatic-mac.zip" in connector)
check("Mac 版の部品に MetaTrader5 を入れない", "MetaTrader5" not in [ln.split(">=")[0] for ln in (BRIDGE / "requirements-mac.txt").read_text().splitlines() if ln and not ln.startswith("#")])

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
