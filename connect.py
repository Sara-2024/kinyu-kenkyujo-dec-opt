#!/usr/bin/env python3
"""
お客様向け接続ツール。

普段は画面に何も出さずに動く（黒い画面を出さない）。やることは4つ:

  1. 起動中の MT5 があればそれを使う（無ければ起動／未導入なら公式インストーラ）
  2. ログイン済みターミナルへ システム(EA) をコピーしてコンパイル
  3. ブリッジを裏側で起動して、中継サーバーにつなぐ
  4. サイトのボタンから起動できるよう aitrader:// を登録し、
     次回からPCの起動時にも自動でつながるようにする

サイトに口座パスワードは一切渡さない。

  DreamlandPassport.exe をダブルクリック   … 初回は MT5 を探して EA を置くだけ（画面つき）
                                         連携済みなら、これまでどおり裏でつなぎ直す
  MT5Automatic.vbs をダブルクリック       … 画面を出さずに全部やる
  python connect.py --console          … 経過を画面に出す（調査用）
  python connect.py --setup            … 初回の設定（MT5を探して EA を置く。画面つき）
  python connect.py --install-ea       … システムの配置だけ
  python connect.py --register         … サイト連携の登録だけ
  python connect.py --stop             … 裏で動いているブリッジを止める
  python connect.py --uninstall        … 停止して、登録も消す
  python connect.py --relay <URL>      … 中継の接続先を .env に書く（他の項目は残す）
  python connect.py --status           … いまの状態と記録の末尾をまとめて出す
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
# PyInstaller で1つの exe にまとめた場合、EA などの同梱物はここに展開される
ASSETS = Path(getattr(sys, "_MEIPASS", ROOT))
BRIDGE_DIR = ASSETS / "bridge"
# 同梱の EA（.ex5）の置き場。普段は bridge/ と同じ。Mac 版が手元で動くときは bridge/mac/ に向ける
EA_ASSETS_DIR = BRIDGE_DIR
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(BRIDGE_DIR))

from mt5_terminal import (  # noqa: E402
    EA_NAMES,
    find_logged_in_terminal,
    probe_ea_files,
    resolve_terminal_exe,
)
import connect_state  # noqa: E402  INSTALL_ONLY / CONNECTED
import ea_manager  # noqa: E402  EA の状態判定と配置
import gold_symbol  # noqa: E402  金の銘柄を気配値に出す
import installer_ui  # noqa: E402  初回の設定画面
import mt5_detect  # noqa: E402  PC の中の MT5 を全部探す

MT5_SETUP_URL = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
# お客様に配る exe が向かう中継。開発機（.py のまま動かすとき）はローカルの中継。
# exe は開発機の bridge/.env を持ち込まない（127.0.0.1 が焼き込まれて、お客様のPCで
# どこにも繋がらなくなった前例がある）。
PRODUCTION_RELAY = "wss://kinyu-relay.onrender.com/bridge"
# 合図を確かめる先。攻撃者の用意した URL へ向かわないよう、ここで決め打ちにする
# （aitrader:// の from= は当てにしない）。手元で試すときだけ環境変数で差し替える。
PRODUCTION_SITE = "https://kinyu-kenkyujo-dec-opt.vercel.app"
LOCAL_RELAY = "ws://127.0.0.1:8080/bridge"

# お客様の MT5 に送るシステムは、これ1つだけ（Orbit GOLD 2軸エンジン。XAUUSD 専用）
EA_NAME = EA_NAMES[0]
# 配るのはコンパイル済みだけ。お客様の PC ではコンパイルしない（ソースも配らない）
EA_FILES = (f"{EA_NAME}{ea_manager.EA_SOURCE_SUFFIX}",)
# 以前に配っていたもの。1つに絞ったので、見つけたら片づける。
# 残っていると同じ指令ファイルを二重に読み書きして紛らわしい。
OLD_EA_NAMES = (
    "TrelabEA",
    "TrelabGate",
    "SiteTestEA",
    "OrbitGoldEA_v5",
    "OrbitGoldEA_v6",
    "OrbitGoldEA_v11",
    "YumekkuEA_v11",
    "3YumekkuEA_win",
    "YumekkuEA_win",   # 2026-10-14 まで配っていた Windows 用（v1.00。サイト連携なし・有効期限 2026-10-15）
    "YumekkuEA_mac",   # 同じく Mac 用（Mac では片づけない。connect_mac._patch）
)
INCLUDE_FILES = ("TradingGate.mqh",)

# お客様に見える名前（aitrader:// の登録名・ブラウザの「開きますか？」）。ファイル名は DreamlandPassport.exe
PRODUCT_NAME = "ドリームランド・パスポート"
# Windows の自動起動（Run）に登録する名前。前の名前は LEGACY_APP_NAMES で片づける
APP_NAME = "DreamlandPassport"
PROTOCOL = "aitrader"
LEGACY_PROTOCOL = "trelab"
# 前の版が自動起動に登録していた名前。見つけたら消して、いまの名前で登録し直す
LEGACY_APP_NAMES = ("MT5 Automatic", "AIトレーダー", "TrelabConnect")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# このPCの「部屋」は会員ID（UUID）だけ。ここを緩くしていたので、
# 悪意あるページが `aitrader://connect?room=<自分のID>` を開かせるだけで、
# お客様のブリッジを他人の部屋へ移せた（しかも bridge.env に残るので恒久的に）。
# いまは URL から部屋を受け取ること自体をやめ、サイトが合図（token）と
# 引き換えに返した部屋しか受け取らない。この検査はその最後の関門。
MEMBER_ROOM_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

SEARCH_EXES = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "MetaTrader 5" / "terminal64.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "MetaTrader 5" / "terminal.exe",
]

# 画面に出すかどうか。既定は「出さない」
CONSOLE = False


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TMPDIR") or "/tmp"
    path = Path(base) / "AITrader"
    old = Path(base) / "Trelab"
    if old.is_dir() and not path.exists():
        try:
            old.rename(path)
        except OSError:
            pass
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ROOT
    return path


CONFIG_DIR = log_dir()
LOG_FILE = CONFIG_DIR / "connect.log"


def env_file() -> Path:
    """ブリッジの設定。exe版は展開先が毎回消えるのでユーザーフォルダに置く。"""
    return (CONFIG_DIR / "bridge.env") if FROZEN else (BRIDGE_DIR / ".env")


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    if CONSOLE:
        print(f"  {msg}", flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def banner(title: str) -> None:
    if CONSOLE:
        print()
        print("=" * 60)
        print(f"  {title}")
        print("=" * 60)
    log(f"--- {title} ---")


# ────────────────────────────────────────────────
# 黒い画面を出さずに他のプログラムを動かすための小道具
# ────────────────────────────────────────────────
def _no_window_flags(detached: bool = False) -> int:
    if os.name != "nt":
        return 0
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    if detached:
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    return flags


def _hidden_startupinfo():
    if os.name != "nt":
        return None
    si = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    si.wShowWindow = 0  # SW_HIDE
    return si


# PyInstaller（1 ファイルの exe）が自分の環境に置く目印。子プロセスに持ち越すと、子は「もう展開済み」と
# 思って親の一時展開フォルダ（_MEIxxxx）を使う。すると親が終わるときに
# 「Failed to remove temporary directory」の警告が出て、子はそのあと部品を読めずに黙って落ちる
# （設置のあとの「合図を待つ係」と、そこから起こす連携で実際に起きた）。
# この exe から自分自身を起こすときは、必ずここを通して目印を外す。
_PYI_ENV_KEYS = ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL")


def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """子プロセスに渡す環境。PyInstaller の目印を外したもの。"""
    env = dict(os.environ if base is None else base)
    for key in _PYI_ENV_KEYS:
        env.pop(key, None)
    return env


def run_hidden(cmd: list[str], cwd: str | None = None, timeout: float | None = None) -> int:
    """終わるまで待つ。ウィンドウは出さない。"""
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            env=child_env(),
            check=False,
            timeout=timeout,
            creationflags=_no_window_flags(),
            startupinfo=_hidden_startupinfo(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return completed.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"実行できませんでした: {cmd[0]} — {exc}")
        return 1


def spawn_hidden(cmd: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> subprocess.Popen | None:
    """起動して待たない。ウィンドウは出さない。"""
    try:
        return subprocess.Popen(
            cmd,
            cwd=cwd,
            env=child_env(env),
            creationflags=_no_window_flags(detached=True),
            startupinfo=_hidden_startupinfo(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        log(f"起動できませんでした: {cmd[0]} — {exc}")
        return None


def pythonw() -> str:
    """コンソールを持たない python。これで起動すると黒い画面が出ない。"""
    if FROZEN:
        return sys.executable
    venv = BRIDGE_DIR / "venv" / "Scripts" / "pythonw.exe"
    if venv.is_file():
        return str(venv)
    here = Path(sys.executable)
    sibling = here.with_name("pythonw.exe")
    if sibling.is_file():
        return str(sibling)
    return sys.executable


# ────────────────────────────────────────────────
# 窓を出しているあいだ、待ち時間や MT5・中継への問い合わせ中に Windows が
# 「応答なし」と出さないための部品。connect_all が窓を作ったら _UI_FOR_PUMP に入れる。
# ────────────────────────────────────────────────
_UI_FOR_PUMP = None


def _pump() -> None:
    ui = _UI_FOR_PUMP
    if ui is None:
        return
    try:
        ui.pump()
    except Exception:  # noqa: BLE001
        pass


def wait_seconds(sec: float) -> None:
    """time.sleep の代わり。待っているあいだも窓を動かす。"""
    end = time.time() + sec
    while True:
        _pump()
        left = end - time.time()
        if left <= 0:
            return
        time.sleep(min(0.1, left))


def run_pumping(fn):
    """時間のかかる処理（MT5 への問い合わせ・中継の確認など）を裏で走らせ、終わるまで窓を動かし続ける。

    窓が無いときは、そのまま呼ぶだけ。
    """
    if _UI_FOR_PUMP is None:
        return fn()
    box: dict = {}

    def work() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    while worker.is_alive():
        _pump()
        worker.join(0.05)
    if "error" in box:
        raise box["error"]
    return box.get("value")


def launch_command(*args: str) -> list[str]:
    """このツール自身を、画面を出さずに起動するためのコマンド"""
    if FROZEN:
        return [sys.executable, *args]
    return [pythonw(), str(ROOT / "connect.py"), *args]


# ────────────────────────────────────────────────
# サイトのボタンから起動できるようにする（aitrader://）
#   ブラウザは仕組み上、勝手にPCのソフトを起動できない。
#   一度この登録をしておけば、以後はサイトのボタン1つで起動できる。
# ────────────────────────────────────────────────
def _delete_protocol(name: str) -> None:
    try:
        import winreg
    except ImportError:
        return
    for sub in (
        rf"Software\Classes\{name}\shell\open\command",
        rf"Software\Classes\{name}\shell\open",
        rf"Software\Classes\{name}\shell",
        rf"Software\Classes\{name}\Application",
        rf"Software\Classes\{name}",
    ):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass


def register_protocol() -> bool:
    if os.name != "nt":
        log(f"Windows ではないので {PROTOCOL}:// の登録は省略します")
        return False
    try:
        import winreg
    except ImportError:
        return False

    command = " ".join(f'"{part}"' for part in launch_command("--silent", "--from-site")) + ' "%1"'
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f"URL:{PRODUCT_NAME}")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}\Application") as key:
            winreg.SetValueEx(key, "ApplicationName", 0, winreg.REG_SZ, PRODUCT_NAME)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}\shell\open\command") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
        if LEGACY_PROTOCOL != PROTOCOL:
            _delete_protocol(LEGACY_PROTOCOL)
        log(f"サイトから起動できるようにしました: {PROTOCOL}://")
        return True
    except OSError as exc:
        log(f"{PROTOCOL}:// を登録できませんでした: {exc}")
        return False


def register_startup() -> bool:
    """PCを立ち上げ直しても、また裏でつながるようにする。"""
    if os.name != "nt":
        return False
    try:
        import winreg
    except ImportError:
        return False

    command = " ".join(f'"{part}"' for part in launch_command("--silent", "--startup"))
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            for old in LEGACY_APP_NAMES:
                try:
                    winreg.DeleteValue(key, old)
                except OSError:
                    pass
        log("PCの起動時にも自動でつながるようにしました")
        return True
    except OSError as exc:
        log(f"スタートアップに登録できませんでした: {exc}")
        return False


def startup_command() -> str:
    """いま登録されている自動起動のコマンド。無ければ空。"""
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            for name in (APP_NAME, *LEGACY_APP_NAMES):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                    if value:
                        return str(value)
                except OSError:
                    continue
    except OSError:
        pass
    return ""


def unregister_startup(why: str = "") -> bool:
    """Windows の起動時に立ち上がる登録を消す（aitrader:// の登録は残す）。

    古い版が「そのときの exe の置き場」を指したまま登録しているので、
    新しい版を入れても、Windows は古い exe を起こし続けてしまう。
    連携していない PC では自動起動そのものが要らないので、見つけたら消す。
    """
    if os.name != "nt":
        return False
    try:
        import winreg
    except ImportError:
        return False
    removed = False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            for name in (APP_NAME, *LEGACY_APP_NAMES):
                try:
                    winreg.DeleteValue(key, name)
                    removed = True
                except OSError:
                    pass
    except OSError:
        return False
    if removed:
        log(f"自動起動の登録を消しました{f'（{why}）' if why else ''}")
    return removed


def unregister() -> int:
    if os.name != "nt":
        return 0
    try:
        import winreg
    except ImportError:
        return 0
    unregister_startup("登録をすべて消した")
    _delete_protocol(PROTOCOL)
    if LEGACY_PROTOCOL != PROTOCOL:
        _delete_protocol(LEGACY_PROTOCOL)
    log(f"{PROTOCOL}:// の登録を消しました")
    # EA は MT5 に置いたまま。サイトとの通信だけ止める
    connect_state.mark_install_only("登録を消した")
    return 0


# ────────────────────────────────────────────────
# MT5
# ────────────────────────────────────────────────
def find_mt5_exe() -> Path | None:
    for path in SEARCH_EXES:
        if path.is_file():
            return path
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    if pf.is_dir():
        for hit in pf.glob("**/terminal64.exe"):
            return hit
    return None


def download_mt5_installer() -> Path:
    dest = Path(os.environ.get("TEMP", ".")) / "trelab-mt5setup.exe"
    log("公式のMT5インストーラを取得しています")
    urllib.request.urlretrieve(MT5_SETUP_URL, dest)
    return dest


def ensure_mt5() -> Path | None:
    """MT5 が無ければ公式インストーラを開く。インストーラ自体の画面は出てよい。"""
    found = find_mt5_exe()
    if found:
        log(f"MT5 を見つけました: {found}")
        return found
    if os.name != "nt":
        log("Windows ではないので、MT5 の導入は行いません")
        return None

    banner("MT5 が入っていません")
    try:
        setup = download_mt5_installer()
    except Exception as exc:  # noqa: BLE001
        log(f"インストーラを取得できませんでした: {exc}")
        return None
    # インストーラは本人の操作が要るので、これだけは画面を出す
    subprocess.Popen([str(setup)], shell=False)
    log("インストーラの終了を待っています")
    for _ in range(300):
        found = find_mt5_exe()
        if found:
            log(f"MT5 を見つけました: {found}")
            return found
        time.sleep(2)
    log("MT5 が見つかりませんでした")
    return None


def launch_mt5(exe: Path) -> None:
    log(f"MT5 を起動します: {exe.name}")
    try:
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
    except OSError as exc:
        log(f"MT5 を起動できませんでした: {exc}")


def wait_for_login(timeout_sec: int = 600, prefer: str | None = None) -> dict | None:
    try:
        import MetaTrader5  # noqa: F401
    except ImportError as exc:
        # exe 版でここに来るのは「無い」のではなく DLL が読めなかったとき（セキュリティ
        # ソフトが展開先を消した等）。理由をそのまま残す
        log(f"MetaTrader5 を読み込めません: {exc}")
        if not FROZEN:
            log("setup-windows.bat を先に実行してください")
        return None

    existing = run_pumping(lambda: find_logged_in_terminal(prefer))
    if existing:
        log(f"ログイン済み: {existing['account']} / {existing['server']}")
        return existing

    banner(LOGIN_WAIT_TEXT)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        status = run_pumping(lambda: find_logged_in_terminal(prefer))
        if status:
            log(f"ログインを確認: {status['account']} / {status['server']}")
            return status
        wait_seconds(2)
    log("ログインを確認できませんでした（時間切れ）")
    return None


def verify_ea_install(data_path: str) -> tuple[bool, dict]:
    probe = probe_ea_files(data_path)
    # コンパイル済みが置けていることが条件。MetaEditor には頼らない
    ok = probe["include_ok"] and EA_NAME in probe["ea_compiled"]
    return ok, probe


def copy_ea_files(session: dict) -> Path:
    data_path = str(session.get("data_path") or "").strip()
    if not data_path:
        raise SystemExit("MT5 のデータフォルダが分かりません（MT5 が起動してログイン済みか確認）")

    data_root = Path(data_path)
    data_root.mkdir(parents=True, exist_ok=True)

    mql5 = data_root / "MQL5"
    experts = mql5 / "Experts"
    include = mql5 / "Include"
    experts.mkdir(parents=True, exist_ok=True)
    include.mkdir(parents=True, exist_ok=True)

    banner("システムの配置")
    log(f"口座 {session.get('account')} / {session.get('server')}")
    log(f"配置先 {experts}")

    for name in INCLUDE_FILES:
        src = BRIDGE_DIR / name
        if not src.is_file():
            raise SystemExit(f"元ファイルがありません: {src}")
        shutil.copy2(src, include / name)
        log(f"OK  Include\\{name}")

    for name in EA_FILES:
        src = EA_ASSETS_DIR / name
        if not src.is_file():
            raise SystemExit(f"元ファイルがありません: {src}")
        shutil.copy2(src, experts / name)
        log(f"OK  Experts\\{name}")

    # 以前配った余分なシステムを片づける（チャートに載っていると消せないことがある）
    for name in OLD_EA_NAMES:
        for suffix in (".mq5", ".ex5"):
            stale = experts / f"{name}{suffix}"
            if not stale.is_file():
                continue
            try:
                stale.unlink()
                log(f"片づけ  Experts\\{name}{suffix}")
            except OSError:
                log(f"注意  {name}{suffix} を消せません（チャートから外してから開き直してください）")

    # コンパイルはしない。配っているものがすでにコンパイル済みのため。
    ok, probe = verify_ea_install(data_path)
    log(f"確認 Include/TradingGate.mqh : {'OK' if probe['include_ok'] else 'なし'}")
    log(f"確認 Experts/{EA_NAME}.ex5 : {'OK' if EA_NAME in probe['ea_compiled'] else 'なし'}")

    # 画面に出さない方針なので、エクスプローラは調査モードのときだけ開く
    if CONSOLE and os.name == "nt":
        try:
            os.startfile(probe["experts_dir"])  # type: ignore[attr-defined]
        except OSError:
            pass

    if not ok:
        raise SystemExit("システムの配置が終わりませんでした（connect.log を確認）")
    return experts


def write_env_key(key: str, val: str) -> None:
    env_path = env_file()
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={val}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={val}")
    try:
        env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        log(f".env を書けませんでした: {exc}")


def write_bridge_env(session: dict) -> None:
    """ブリッジが同じ MT5 ターミナル（いまログイン中の口座）へ繋ぐよう .env を更新する。"""
    exe = resolve_terminal_exe(session)
    if exe is None:
        return
    write_env_key("MT5_PATH", str(exe))
    log(f"ブリッジが使う MT5: {exe}")


def adopt_room(room: str) -> None:
    """この PC の部屋（会員ID）を覚えて、連携済みにする。

    ここに渡ってよい部屋は、サイトが合図（token）と引き換えに返したものだけ。
    URL から直接受け取ってはいけない（会員IDを知っているだけの相手に
    連携されてしまう）。呼び出し口は connect_all 一本にしてある。
    """
    if not MEMBER_ROOM_RE.match(room):
        log(f"会員IDの形でない部屋は覚えません: {room[:40]}")
        return
    before = env_value("BRIDGE_ID")
    if before and before != room and MEMBER_ROOM_RE.match(before):
        # 別の会員の部屋へ移す指示。ふつうは起きない（起きるのは、同じPCを
        # 別の会員が使うときか、他人のサイトから開かせられたとき）。記録に残す。
        log(f"部屋を切り替えます: {before} → {room}")
    write_env_key("BRIDGE_ID", room)
    os.environ["BRIDGE_ID"] = room
    connect_state.mark_connected(room)
    log(f"このPCの部屋: {room}")


def is_protocol_url(raw: str) -> bool:
    lower = raw.lower()
    return lower.startswith(f"{PROTOCOL}:") or lower.startswith(f"{LEGACY_PROTOCOL}:")


# 合図の形。サイトが gen_random_bytes(32) を16進で作る
TOKEN_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def connect_token_from_args(argv: list[str]) -> str:
    """aitrader://connect?token=... から合図を読む。

    連携を始められる入口はここだけ。以前は `?room=<会員ID>` も受けていたが、
    この URL は**どのページからでも**開かせられるので、会員IDを知っている
    だけの相手にブリッジを他人の部屋へ移されてしまう。`from=` の照合まで
    足しても「自分たちのサイトを装って開かせる」余地が残るため、
    URL から部屋を受け取ること自体をやめた。
    いまは、サイトがその場で作った短命の合図と引き換えでなければ連携できない。
    """
    for raw in argv:
        if not is_protocol_url(raw):
            continue
        try:
            parsed = urllib.parse.urlparse(raw.replace("\\", "/"))
            query = urllib.parse.parse_qs(parsed.query)
            token = (query.get("token") or [""])[0].strip()
            if TOKEN_RE.match(token):
                return token
        except Exception:  # noqa: BLE001
            continue
    return ""


TOKEN_IN_TEXT = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{64})(?![0-9a-fA-F])")


LINK_WAIT_MIN = 60          # 設置のあと、合図を取りに行き続ける時間（分）
LINK_POLL_SEC = 5


def relay_claim(account: str) -> str:
    """中継に預けられた合図（この口座番号あて）を取りに行く。無ければ空。"""
    url = relay_url()
    origin = "http://127.0.0.1:8080" if relay_is_local(url) else relay_http_origin(url)
    if not origin or not account:
        return ""
    try:
        with urllib.request.urlopen(f"{origin}/claim?account={urllib.parse.quote(account)}", timeout=6) as res:
            data = json.loads(res.read().decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return ""
    token = str(data.get("token") or "") if isinstance(data, dict) and data.get("ok") else ""
    return token if TOKEN_RE.match(token) else ""


def wait_for_link() -> int:
    """設置のあと、サイトで「設置が終わった（つなぐ）」が押されるのを裏で待つ。

    ロビーは押された合図を中継に預ける。ここは、ログイン中の MT5 の口座番号で
    数秒おきに取りに行き、来たら aitrader://connect?token=… と同じ道で連携する
    （サイトからブラウザ経由で呼び出さなくてよい＝「開きますか？」が出ない）。
    """
    import ctypes

    if os.name == "nt":
        try:
            handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\AITraderConnect.waitlink")
            if handle and ctypes.windll.kernel32.GetLastError() == 183:
                log("合図を待つ係はもう動いています")
                return 0
        except Exception:  # noqa: BLE001
            pass
    log(f"サイトの「設置が終わった」を待ちます（最長 {LINK_WAIT_MIN} 分）")
    deadline = time.time() + LINK_WAIT_MIN * 60
    while time.time() < deadline:
        accounts: list[str] = []
        try:
            for t in mt5_detect.list_terminals():
                acct = str(account_of(t) or "").strip()
                if acct.isdigit() and acct not in accounts:
                    accounts.append(acct)
        except Exception as exc:  # noqa: BLE001
            log(f"MT5 の口座を読めませんでした: {exc}")
        if not accounts:
            # 入れたばかりの MT5 は表示名に口座番号が出ないことがある。ログイン中の MT5 から直接読む
            try:
                session = find_logged_in_terminal()
                acct = str((session or {}).get("account") or "").strip()
                if acct.isdigit():
                    accounts.append(acct)
            except Exception as exc:  # noqa: BLE001
                log(f"ログイン中の MT5 を読めませんでした: {exc}")
        if not accounts:
            log("ログイン中の MT5 が見つからないので、合図はまだ取りに行けません（MT5 にログインしてください）")
        for acct in accounts:
            token = relay_claim(acct)
            if token:
                log(f"合図を受け取りました（口座 …{acct[-4:]}）。連携します")
                # 初回の設定の窓が開いたままだと、二重起動の防止に当たって何もできない。閉じるまで待つ
                for _ in range(360):
                    if not setup_window_open():
                        break
                    time.sleep(5)
                url = f"{PROTOCOL}://connect?token={token}&account={acct}"
                if FROZEN:
                    spawn_hidden([sys.executable, url], cwd=str(CONFIG_DIR))
                else:
                    spawn_hidden([sys.executable, str(ROOT / "connect.py"), url], cwd=str(ROOT))
                return 0
        time.sleep(LINK_POLL_SEC)
    log("合図は来なかったので、待つのをやめます")
    return 0


def setup_window_open() -> bool:
    """初回の設定／接続の窓（二重起動の防止を持っている）が開いているか。"""
    if os.name != "nt":
        return False
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, "Local\\AITraderConnect.setup")
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def list_link_waiters() -> list[int]:
    """動いている「合図を待つ係」（--wait-link）の番号。自分と親は除く。"""
    if os.name != "nt":
        return []
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -like '*--wait-link*' } | "
        "ForEach-Object { \"$($_.ProcessId)\" }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, errors="replace", check=False, timeout=40,
            creationflags=_no_window_flags(), startupinfo=_hidden_startupinfo(),
        ).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"合図を待つ係の一覧を取れませんでした: {exc}")
        return []
    skip = {os.getpid(), os.getppid()}
    return [int(x) for x in out.split() if x.strip().isdigit() and int(x) not in skip]


def stop_link_waiters() -> None:
    """古い「合図を待つ係」を終える。

    前の版の係が壊れたまま残っていると（親の一時フォルダが消えて部品を読めない状態）、
    係の二重起動の歯止め（mutex）を握ったまま合図を横取りして落ちるので、
    新しい係も、サイトからの「つなぎ直す」も、永久に通らない（VPS の実機で起きた）。
    設置のとき・サイトから呼ばれたときに、まず片づける。
    """
    for pid in list_link_waiters():
        log(f"古い「合図を待つ係」（PID {pid}）を終了します")
        kill_process(pid)


def start_link_waiter() -> None:
    """合図を待つ係を裏で起こす（exe 版だけ。手元の Python では起こさない）。"""
    if not FROZEN:
        log("合図を待つ係は exe 版だけで起こします（手元では省略）")
        return
    stop_link_waiters()
    spawn_hidden([sys.executable, "--wait-link"], cwd=str(CONFIG_DIR))
    log("サイトの「設置が終わった」を裏で待ちます")


def connect_token_from_zone(exe: str | None = None) -> str:
    """ダウンロード元の URL から合図を読む。

    Windows は、ブラウザでダウンロードしたファイルに「どこから来たか」を
    Zone.Identifier（代替データストリーム）として記録する。Chrome / Edge は
    HostUrl= にダウンロード元の URL をそのまま書くので、ロビーが付けた ?k=<合図> が読める。
    無ければ空（手で削除した・ZIP 経由・別の入れ方）。
    """
    path = Path(exe or sys.executable)
    try:
        text = (str(path) + ":Zone.Identifier").encode("utf-8")
        with open(text.decode("utf-8"), "r", encoding="utf-8", errors="ignore") as fh:
            body = fh.read(8192)
    except OSError:
        return ""
    for line in body.splitlines():
        if line.lower().startswith(("hosturl=", "referrerurl=")):
            found = re.search(r"[?&]k=([0-9a-fA-F]{64})(?![0-9a-fA-F])", line)
            if found:
                return found.group(1)
    return ""


def connect_token_from_exe_name(exe: str | None = None) -> str:
    """ダウンロードしたファイルから合図を読む。

    ロビーは Windows 用を「/download/DreamlandPassport.exe?k=<合図>」から配る。
    お客様はそれを開くだけでよく、サイトから aitrader:// で呼び出し直す必要が無い
    （「開きますか？」が出ない）。合図は 64 桁の 16 進で、使い捨て。
    読む順: ① ダウンロード元の URL（Zone.Identifier） ② ファイル名（DreamlandPassport-<合図>.exe）。
    exe 版（frozen）で、引数なしで開かれたときにだけ使う（main を見よ）。
    """
    from_zone = connect_token_from_zone(exe)
    if from_zone:
        return from_zone
    name = Path(exe or sys.executable).stem
    found = TOKEN_IN_TEXT.search(name)
    return found.group(1) if found else ""


def account_from_args(argv: list[str]) -> str:
    """aitrader://connect?token=…&account=<口座番号> の口座番号（無ければ空）。
    どの MT5 を担当させるかを選ぶためだけに使う。部屋（会員）は合図を確かめて決める。"""
    for raw in argv:
        if not is_protocol_url(raw):
            continue
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(raw.replace("\\", "/")).query)
            acct = (query.get("account") or [""])[0].strip()
            if acct.isdigit():
                return acct
        except Exception:  # noqa: BLE001
            continue
    return ""


# ────────────────────────────────────────────────
# 追加口座（ロイヤルファーストクラスの 2 つ目）。MT5 ごとにブリッジを 1 本ずつ
#   1 本目＝これまでどおり（CONFIG_DIR 直下・BRIDGE_ID・aitrader-bridge.lock）。
#   2 本目以降＝CONFIG_DIR/accounts/<口座番号>/ に設定と記録を持ち、
#   BRIDGE_SLOT=<口座番号> で起動する。ロックと指令ファイルも口座番号で分かれる。
# ────────────────────────────────────────────────
def slot_dir(account: str) -> Path:
    d = CONFIG_DIR / "accounts" / account
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_slots() -> list[dict]:
    out: list[dict] = []
    base = CONFIG_DIR / "accounts"
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        f = d / "slot.json"
        if d.is_dir() and f.is_file():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, dict) and str(data.get("account") or "").isdigit():
                    out.append(data)
            except (OSError, ValueError):
                continue
    return out


def primary_account() -> str:
    """1 本目のブリッジが担当している口座番号（分からなければ空＝これまでどおり扱う）。"""
    acct = str(connect_state.read().get("account") or "").strip()
    return acct if acct.isdigit() else ""


def terminal_for_account(account: str):
    """その口座番号でログインしている MT5（表示名の「口座 N」で見る）。無ければ None。"""
    for t in mt5_detect.list_terminals():
        if account_of(t) == account:
            return t
    return None


def list_slot_bridge_processes(account: str) -> list[tuple[int, str]]:
    return [(pid, img) for pid, img, cmd in list_bridge_processes_with_cmdline() if f"--slot {account}" in cmd.lower()]


def connect_slot(room: str, account: str) -> int:
    """追加口座の連携。その口座の MT5 に EA を置き、口座専用のブリッジを起こす。1 本目は触らない。"""
    banner(f"追加口座の連携（口座 …{account[-4:]}）")
    target = terminal_for_account(account)
    if target is None:
        log(f"口座 {account} でログインしている MT5 が見つかりません")
        return show_failure(
            f"口座 {account} の MT5 が見つかりません。",
            "その口座で MT5 にログインしてから、サイトの「設置が終わった（つなぐ）」をもう一度押してください。",
        )
    source = ea_manager.load_source(BRIDGE_DIR)
    if source is None:
        return show_failure("自動売買の設定を取り出せませんでした。", "パスポートをダウンロードし直してください。")
    after = ea_manager.install(target.data_path, source, old_names=OLD_EA_NAMES, log=log)
    log(f"追加口座の EA: {after.as_dict()}")
    exe = target.exe
    data = {"account": account, "room": room, "terminal": str(target.data_path), "exe": str(exe or ""),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (slot_dir(account) / "slot.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"追加口座の部屋: {room}（MT5: {target.data_path}）")
    start_slot_bridge(data)
    return 0


def start_slot_bridge(slot: dict) -> None:
    """口座専用のブリッジを起こす（同じ口座の古いものが居れば止めてから）。"""
    account = str(slot.get("account") or "")
    if not account.isdigit():
        return
    for pid, image in list_slot_bridge_processes(account):
        log(f"追加口座（…{account[-4:]}）の古いブリッジ（PID {pid} / {image}）を終了します")
        kill_process(pid)
        wait_gone(pid)
    env = bridge_env(None)
    env["BRIDGE_ID"] = str(slot.get("room") or "")
    env["BRIDGE_SLOT"] = account
    env["LOG_FILE"] = str(slot_dir(account) / "bridge.log")
    if slot.get("exe"):
        env["MT5_PATH"] = str(slot["exe"])
    else:
        env.pop("MT5_PATH", None)
    if FROZEN:
        cmd = [sys.executable, "--run-bridge", "--slot", account]
    else:
        cmd = [pythonw(), str(BRIDGE_DIR / "bridge.py"), "--slot", account]
    log(f"追加口座（…{account[-4:]}）のブリッジを裏側で起動します")
    spawn_hidden(cmd, cwd=str(CONFIG_DIR if FROZEN else BRIDGE_DIR), env=env)


def start_slot_bridges() -> None:
    """自動起動のとき、追加口座のブリッジも全部起こす。"""
    for slot in list_slots():
        if not Path(str(slot.get("terminal") or "")).is_dir():
            log(f"追加口座（…{str(slot.get('account'))[-4:]}）の MT5 が見つからないので起こしません")
            continue
        start_slot_bridge(slot)


def site_url() -> str:
    return (env_value("TRELAB_SITE_URL") or PRODUCTION_SITE).rstrip("/")


def redeem_connect_token(token: str) -> str:
    """合図をサイトに確かめてもらい、この PC の部屋（会員ID）を受け取る。

    合図は一度しか使えない。ここで失敗したら連携しない（＝通信も始めない）。
    合言葉そのものは記録に残さない。
    """
    url = f"{site_url()}/api/connect"
    body = json.dumps({"token": token, "bridge_id": env_value("BRIDGE_ID") or ""}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # サイトが断った
        log(f"連携の合図を確かめられませんでした（{exc.code}）")
        return ""
    except Exception as exc:  # noqa: BLE001 通信できない
        log(f"サイトに問い合わせできませんでした: {type(exc).__name__}")
        return ""
    room = str(data.get("room") or "").strip()
    if not MEMBER_ROOM_RE.match(room):
        log("サイトの返事に部屋が入っていませんでした")
        return ""
    log("連携の合図を確認しました")
    return room


# ────────────────────────────────────────────────
# 中継とブリッジ
# ────────────────────────────────────────────────
def env_value(key: str) -> str:
    """設定ファイルから1項目だけ読む（環境変数が優先）"""
    if os.environ.get(key):
        return os.environ[key].strip()
    # exe 版はユーザーフォルダの bridge.env だけを見る（同梱物の .env は読まない）
    for path in ((env_file(),) if FROZEN else (env_file(), BRIDGE_DIR / ".env")):
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith(f"{key}="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return ""


def relay_url() -> str:
    """接続先の中継サーバー。本番はクラウド側にある。"""
    return env_value("TRELAB_WS_URL") or (PRODUCTION_RELAY if FROZEN else LOCAL_RELAY)


def relay_is_local(url: str) -> bool:
    return "127.0.0.1" in url or "localhost" in url


def relay_is_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1.5) as res:
            return res.status == 200
    except Exception:  # noqa: BLE001
        return False


def relay_http_origin(ws_url: str) -> str | None:
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://") :].split("/")[0]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://") :].split("/")[0]
    return None


def relay_health(room: str = "") -> dict | None:
    url = relay_url()
    origin = "http://127.0.0.1:8080" if relay_is_local(url) else relay_http_origin(url)
    if not origin:
        return None
    query = f"?room={urllib.parse.quote(room)}" if room else ""
    try:
        with urllib.request.urlopen(f"{origin}/health{query}", timeout=4) as res:
            return json.loads(res.read().decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None


def relay_bridge_count() -> int | None:
    data = relay_health()
    if data is None:
        return None
    try:
        return int(data.get("bridges", 0))
    except (TypeError, ValueError):
        return None


def relay_has_bridge(bridge_id: str) -> bool | None:
    """その部屋にブリッジが居るか。中継は部屋の一覧を出さないので、名指しで聞く。"""
    data = relay_health(bridge_id)
    if data is None:
        return None
    room = data.get("room")
    if not isinstance(room, dict):
        return None
    return bool(room.get("bridge"))


# 以前の版が使っていたロック名も見る。見落とすと古いブリッジを止められない。
LOCK_NAMES = ("aitrader-bridge.lock", "trelab-bridge.lock")


def bridge_lock_path() -> Path:
    return Path(os.environ.get("TEMP", "/tmp")) / LOCK_NAMES[0]


def all_lock_paths() -> list[Path]:
    base = Path(os.environ.get("TEMP", "/tmp"))
    return [base / name for name in LOCK_NAMES]


def process_image(pid: int) -> str:
    """その番号のプロセスの実行ファイル名。無ければ空。

    Windows の os.kill(pid, 0) は生存確認ではなく強制終了になるため使わない。
    """
    if pid <= 0:
        return ""
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=20,
                creationflags=_no_window_flags(),
                startupinfo=_hidden_startupinfo(),
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""
        line = out.strip().splitlines()[0].strip() if out.strip() else ""
        if not line.startswith('"'):
            return ""
        return line.split('","')[0].strip('"')
    try:
        os.kill(pid, 0)
        return "python"
    except PermissionError:
        return "python"
    except OSError:
        return ""


# ブリッジとして動いていそうな実行ファイルの名前。exe の名前を変えたらここにも足す。
# （MT5Automatic に変えたとき足し忘れ、動いている古いブリッジを「触らない」と判定して
#   止められず、新しいブリッジも起動しないまま「接続完了」と言っていた）
BRIDGE_IMAGE_HINTS = tuple(
    sorted({"python", "aitrader", "trelab", "mt5automatic", "dreamlandpassport", Path(sys.executable).stem.lower()})
)


def list_bridge_processes(include_slots: bool = False) -> list[tuple[int, str]]:
    """bridge.py（か exe の --run-bridge）として動いているプロセスを挙げる。

    既定では 1 本目の枠だけ（追加口座 --slot のブリッジは触らない）。
    include_slots=True で全部（--stop / --uninstall 用）。
    """
    out: list[tuple[int, str]] = []
    for pid, image, cmd in list_bridge_processes_with_cmdline():
        if not include_slots and "--slot" in cmd.lower():
            continue
        out.append((pid, image))
    return out


def list_bridge_processes_with_cmdline() -> list[tuple[int, str, str]]:
    """動いているブリッジを (番号, 実行ファイル名, 命令行) で挙げる。

    ロックファイルに番号が書かれていない古い版や、ロックが別の場所に
    できてしまった場合でも、これなら見つけられる。
    """
    me = os.getpid()
    found: list[tuple[int, str, str]] = []
    if os.name == "nt":
        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -and "
            "($_.CommandLine -like '*bridge.py*' -or $_.CommandLine -like '*--run-bridge*') } | "
            "ForEach-Object { \"$($_.ProcessId)|$($_.Name)|$($_.CommandLine)\" }"
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=40,
                creationflags=_no_window_flags(),
                startupinfo=_hidden_startupinfo(),
            ).stdout
        except (OSError, subprocess.TimeoutExpired) as exc:
            log(f"プロセス一覧を取れませんでした: {exc}")
            return found
    else:
        try:
            out = subprocess.run(
                ["ps", "-eo", "pid=,args="],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=20,
            ).stdout
            out = "\n".join(
                f"{ln.split()[0]}|{Path(ln.split()[1]).name}"
                for ln in out.splitlines()
                if ln.strip() and ("bridge.py" in ln or "--run-bridge" in ln)
            )
        except (OSError, subprocess.TimeoutExpired):
            return found
    skip = {me, os.getppid()}   # exe 版は「起動役の親 → 本体」の 2 つで、親も自分
    for line in out.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        pid_s, rest = line.split("|", 1)
        image, _, cmdline = rest.partition("|")
        if not pid_s.strip().isdigit():
            continue
        pid = int(pid_s)
        image = image.strip().lower()
        if pid in skip or pid <= 0:
            continue
        # 「--run-bridge」付きで起動されていれば、名前が何であれブリッジ（名前を書き換えられた exe も拾う。
        # 「MT5 autimatic.exe」に改名された古い版が止められず、VPS で永久につながらなかった）。
        # bridge.py はエディタで開いているだけのこともあるので、そちらは名前も見る
        if "--run-bridge" not in cmdline and not any(h in image for h in BRIDGE_IMAGE_HINTS):
            continue
        found.append((pid, image, cmdline))
    # PowerShell が使えない・コマンドラインを読めない PC では何も見つからない。
    # その場合は wmic（コマンドラインで探す）→ tasklist（パスポートの名前）→
    # ロックが取られているなら pythonw.exe（9 月に配った Python 版のブリッジ）の順に拾う。
    # 古いブリッジが残ったまま新しいブリッジが「別のブリッジがすでに動いています」で
    # 起動できず、サイトからは永久に「来ない」ままになった（Windows の実機・VPS で起きた）。
    if os.name == "nt" and not found:
        for pid, image, cmdline in list_bridge_processes_wmic():
            if pid not in skip:
                found.append((pid, image, cmdline))
    # 命令行が読めない保険（tasklist）は、枠を判定できないので「命令行の一覧が何も返さなかった」ときだけ
    if os.name == "nt" and not found and not out.strip():
        for pid, image in list_processes_by_name(include_python=bridge_lock_held()):
            if pid not in skip:
                found.append((pid, image, ""))
    return found


def bridge_lock_held() -> bool:
    """どれかのロック（古い名前も含む）が誰かに取られているか。取られていれば、ブリッジは確実に動いている。"""
    for path in all_lock_paths():
        if not path.is_file():
            continue
        try:
            with path.open("r+") as fh:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fh, fcntl.LOCK_UN)
        except OSError:
            return True
    return False


def list_bridge_processes_wmic() -> list[tuple[int, str, str]]:
    """wmic でコマンドラインから探す（PowerShell が使えない PC 向け。古い Windows Server にもある）。"""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "commandline like '%bridge.py%' or commandline like '%--run-bridge%'",
             "get", "CommandLine,Name,ProcessId", "/format:csv"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=40,
            creationflags=_no_window_flags(),
            startupinfo=_hidden_startupinfo(),
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    me, parent = os.getpid(), os.getppid()
    found: list[tuple[int, str, str]] = []
    for line in out.splitlines():
        parts = [x.strip() for x in line.strip().split(",")]
        if len(parts) < 3 or not parts[-1].isdigit():
            continue  # 見出し行や空行
        pid, image = int(parts[-1]), parts[-2].lower()
        cmdline = ",".join(parts[1:-2]).lower()   # 命令行にカンマがあっても拾えるように
        if pid in (me, parent):
            continue
        if "--run-bridge" in cmdline or any(h in image for h in BRIDGE_IMAGE_HINTS):
            found.append((pid, image, cmdline))
    return found


def list_processes_by_name(include_python: bool = False) -> list[tuple[int, str]]:
    """tasklist で、パスポート（ブリッジ）の名前のプロセスを挙げる。PowerShell が無くても動く。

    include_python=True のときは pythonw.exe も拾う（9 月に配った Python 版のブリッジ）。
    ロックが取られている（＝ブリッジが確実に動いている）のに名前で見つからないときだけ使う。
    """
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=30,
            creationflags=_no_window_flags(),
            startupinfo=_hidden_startupinfo(),
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    import csv
    import io

    found: list[tuple[int, str]] = []
    for row in csv.reader(io.StringIO(out)):
        if len(row) < 2 or not row[1].strip().isdigit():
            continue
        image = row[0].strip().lower()
        if image in ("python.exe", "pythonw.exe"):
            # Python は他の用途でも動く。名前だけでは止めない。
            # ただしロックが取られているのに他に見つからないときは、pythonw.exe が古いブリッジ
            if include_python and image == "pythonw.exe":
                found.append((int(row[1]), image))
            continue
        if any(h in image for h in BRIDGE_IMAGE_HINTS if h not in ("python",)):
            found.append((int(row[1]), image))
    return found


def kill_process(pid: int) -> None:
    if os.name == "nt":
        run_hidden(["taskkill", "/PID", str(pid), "/F", "/T"], timeout=30)
    else:
        try:
            os.kill(pid, 15)
        except OSError as exc:
            log(f"終了できませんでした: {exc}")


def wait_gone(pid: int, seconds: float = 10.0, tick=None) -> bool:
    for _ in range(int(seconds / 0.5)):
        if not process_image(pid):
            return True
        time.sleep(0.5)
        if tick:
            tick()  # 画面を固まらせない
    return not process_image(pid)


def stop_all_bridges(include_slots: bool = False) -> int:
    """動いているブリッジを終了する（古い名前・古い版のものも含めて）。

    画面を出さずに常駐する作りなので、止める手段をここに用意しておく。
    ロックの番号 → コマンドラインの検索、の順で探す。
    既定では 1 本目の枠だけ。追加口座のブリッジも止めるのは --stop / --uninstall のときだけ。
    """
    stopped = 0
    targets: list[tuple[int, str]] = []
    for path in all_lock_paths():
        if not path.is_file():
            continue
        try:
            first = path.read_text(encoding="ascii", errors="replace").splitlines()[0].strip()
            pid = int(first) if first.isdigit() else None
        except (OSError, IndexError, ValueError):
            pid = None
        if not pid:
            continue
        image = process_image(pid).lower()
        if not image:
            continue
        if not any(h in image for h in BRIDGE_IMAGE_HINTS):
            log(f"PID {pid} は {image} なので触りません")
            continue
        targets.append((pid, image))
    for pid, image in list_bridge_processes(include_slots=include_slots):
        if all(pid != t[0] for t in targets):
            targets.append((pid, image))

    for pid, image in targets:
        log(f"ブリッジ（PID {pid} / {image}）を終了します")
        kill_process(pid)
        if wait_gone(pid):
            stopped += 1
            log("終了しました")
        else:
            log(f"終了できませんでした（PID {pid}）。タスクマネージャーで {image} を終了してください")

    if stopped == 0 and not targets:
        log("動いているブリッジは見つかりませんでした")
    return stopped


def lock_pid() -> int | None:
    """ロックの1行目が番号(PID)、2行目が版"""
    path = bridge_lock_path()
    if not path.is_file():
        return None
    try:
        first = path.read_text(encoding="ascii", errors="replace").splitlines()[0].strip()
        return int(first) if first else None
    except (OSError, ValueError, IndexError):
        return None


def source_version() -> str:
    """いま手元にある bridge.py の版"""
    try:
        text = (BRIDGE_DIR / "bridge.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    hit = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return hit.group(1) if hit else ""


def running_version() -> str:
    """いま動いているブリッジの版（ロックの2行目）"""
    lock = bridge_lock_path()
    if not lock.is_file():
        return ""
    try:
        lines = lock.read_text(encoding="ascii", errors="ignore").splitlines()
    except OSError:
        return ""
    return lines[1].strip() if len(lines) > 1 else ""


def running_room() -> str:
    """いま動いているブリッジの部屋＝会員ID（ロックの3行目。古い版は空）"""
    lock = bridge_lock_path()
    if not lock.is_file():
        return ""
    try:
        lines = lock.read_text(encoding="ascii", errors="ignore").splitlines()
    except OSError:
        return ""
    return lines[2].strip() if len(lines) > 2 else ""


def bridge_in_other_room(our_id: str) -> bool:
    """サイトが見ている部屋と違う名前で動いていると、サイトからは居ないように見える（E003）。"""
    theirs = running_room()
    if not theirs or theirs == our_id:
        return False
    log(f"動いているブリッジの部屋が違います（動作中={theirs} / サイト={our_id}）")
    return True


def bridge_is_outdated() -> bool:
    """動いているブリッジが古いか。古いまま使うと、直した不具合がそのまま残る。"""
    mine = source_version()
    theirs = running_version()
    if not mine:
        return False
    if theirs == mine:
        return False
    log(f"動いているブリッジが古い版です（動作中={theirs or '不明'} / 手元={mine}）")
    return True


def stop_stale_bridge() -> None:
    """古い版、または中継に乗っていないブリッジを終了する。"""
    log("いま動いているブリッジを止めて、入れ替えます")
    stop_all_bridges()
    time.sleep(0.6)


def start_relay() -> None:
    """本番の中継はクラウド側にあるので、ここが動くのは検証用のローカルだけ。"""
    if not (SERVER_DIR / "index.js").is_file():
        log("server/ が無いので中継の起動は省略します")
        return
    if not (SERVER_DIR / "node_modules").is_dir():
        log("中継の依存を入れています")
        run_hidden(["npm.cmd" if os.name == "nt" else "npm", "install"], cwd=str(SERVER_DIR), timeout=600)
    log("中継を起動します（ポート 8080）")
    spawn_hidden(["npm.cmd" if os.name == "nt" else "npm", "start"], cwd=str(SERVER_DIR))


def bridge_already_running() -> bool:
    """bridge.py は二重起動をロックで弾く。ロックが取れなければ動いている。"""
    lock = bridge_lock_path()
    if not lock.is_file():
        return False
    try:
        # ロックを取れるなら、前のブリッジはもう居ない
        with lock.open("r+") as fh:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def embedded_risk_token() -> str:
    """exe に埋め込んだ AIリスク監督の合言葉。無ければ空（＝AIゲートは切のまま）。"""
    try:
        import risk_secret  # type: ignore[import-not-found]

        return str(getattr(risk_secret, "TOKEN", "")).strip()
    except Exception:  # noqa: BLE001
        return ""


def bridge_env(session: dict | None) -> dict[str, str]:
    env = dict(os.environ)
    env["TRELAB_WS_URL"] = relay_url()
    # 部屋の名前。exe には bridge/.env が入らないので、ここで渡さないと
    # ブリッジは既定の vps-01 に入ってしまい、サイトの指令が届かない。
    env["BRIDGE_ID"] = env_value("BRIDGE_ID") or "vps-01"
    token = env_value("TRELAB_TOKEN")
    if token:
        env["TRELAB_TOKEN"] = token
    # AIリスク監督（新規注文の許可・停止）の設定。bridge.env に書いてあれば渡す。
    # 合言葉が無ければブリッジ側で自動的に「切」になる（勝手に動き出さない）。
    for key in ("TRELAB_RISK_TOKEN", "RISK_API_URL", "RISK_GATE_ENABLED", "RISK_EVAL_SEC", "RISK_LIVE_MODE", "RISK_DEMO_MODE", "RISK_SYMBOL"):
        value = env_value(key)
        if value:
            env[key] = value
    if not env.get("TRELAB_RISK_TOKEN"):
        # ビルドのときに埋め込んだ合言葉（bridge/risk_secret.py）。お客様は何も入力しない
        env["TRELAB_RISK_TOKEN"] = embedded_risk_token()
    env["LOG_FILE"] = str(CONFIG_DIR / "bridge.log")
    # exe が自分自身をもう一度起こすときは、展開先の目印を持ち越さない。
    # 持ち越すと、子は「もう展開済み」と思ってこちらの一時フォルダを見に行き、
    # そこは親の終了と同時に消えるので MetaTrader5 の DLL を読めずに落ちる。
    for key in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL"):
        env.pop(key, None)
    # 証明書の場所も持ち越さない（親の一時展開フォルダを指していて、親が終わると消える。Mac）。子が自分で決める
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        env.pop(key, None)
    if session:
        exe = resolve_terminal_exe(session)
        if exe is not None:
            env["MT5_PATH"] = str(exe)
    return env


def start_bridge(session: dict | None = None) -> None:
    # サイトから正式に連携されるまでは、口座の情報を外へ出さない。
    # ここが最後の歯止め。呼び出し口が増えても、これで必ず止まる。
    if not connect_state.is_connected():
        log("まだサイトと連携していないので、通信は始めません（EA の設置だけ）")
        return
    our_id = env_value("BRIDGE_ID") or "vps-01"
    # ロックで見つからない古いブリッジ（別の場所にロックを持つ古い版など）も、
    # プロセスの名前で探して止める。残っていると新しいブリッジが起動できない
    if not bridge_already_running() and list_bridge_processes():
        log("古いブリッジが残っているので止めます")
        stop_stale_bridge()
    if bridge_already_running():
        local_missing = (
            relay_is_local(relay_url())
            and relay_is_up()
            and relay_has_bridge(our_id) is False
        )
        if local_missing or bridge_is_outdated() or bridge_in_other_room(our_id):
            stop_stale_bridge()
        else:
            log("ブリッジはすでに動いています")
            return
        if bridge_already_running():
            log("古いブリッジを終了できませんでした。tools\\停止する.bat を実行するか、")
            log("タスクマネージャーで pythonw.exe を終了してから、もう一度お試しください")
            return
    if FROZEN:
        cmd = [sys.executable, "--run-bridge"]
    else:
        cmd = [pythonw(), str(BRIDGE_DIR / "bridge.py")]
    log(f"ブリッジを裏側で起動します（接続先 {relay_url()}）")
    # 作業フォルダは、この exe が消えても残る場所にする。BRIDGE_DIR は exe の
    # 一時展開先（_MEIxxxx）で、こちらが終了すると消える。そこを作業フォルダに
    # したまま起こすと、裏のブリッジが道連れで落ちる。
    workdir = CONFIG_DIR if FROZEN else BRIDGE_DIR
    spawn_hidden(cmd, cwd=str(workdir), env=bridge_env(session))


# ────────────────────────────────────────────────
# 入口
# ────────────────────────────────────────────────
def self_test() -> int:
    banner("自己確認（MT5なし）")
    missing = [n for n in INCLUDE_FILES if not (BRIDGE_DIR / n).is_file()]
    missing += [n for n in EA_FILES if not (EA_ASSETS_DIR / n).is_file()]
    if missing:
        log(f"NG 元ファイルがありません: {missing}")
        return 1
    fake = ROOT / ".tmp-mt5-data"
    try:
        copy_ea_files({"data_path": str(fake), "account": 0, "server": "test"})
        log("OK  配置と確認の処理")
        return 0
    except SystemExit as exc:
        log(f"配置は動きました（コンパイルは環境次第）: {exc}")
        return 0
    finally:
        shutil.rmtree(fake, ignore_errors=True)


# ────────────────────────────────────────────────
# 初回の設定（Phase 1）
#   MT5 を探して EA を置くところまで。サイトとは一切通信しない。
#   サイトから正式に連携されるまで、この状態のまま動く。
# ────────────────────────────────────────────────
def tell(ui, message: str, hint: str = "") -> None:
    """うまくいかなかったことを知らせる。

    窓を作れていないときも、Windows の小さな画面だけは出す。
    黙って終わると、お客様には「壊れている」としか見えない。
    """
    log(f"{message} {hint}".strip())
    release_single_instance()  # 窓を出して待つ前に、次の合図を受け取れるようにしておく
    if ui:
        ui.fail(message, hint)
    else:
        installer_ui.message_box(f"{message}\n\n{hint}".strip())


_INSTANCE_MUTEX = None


def hold_single_instance() -> bool:
    """同じアプリを二つ開かない。二つ目なら False。

    exe は開くのに数秒かかるので、お客様は「反応が無い」と思ってもう一度押す。
    二つ同時に EA を置きに行くと、片方が書けずに「保存できませんでした」になる。
    """
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Local\\AITraderConnect.setup")
        if not handle:
            return True
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False
        _INSTANCE_MUTEX = handle  # 終わるまで持ち続ける（終われば Windows が外す）
        return True
    except Exception:  # noqa: BLE001
        return True


def release_single_instance() -> None:
    """二重起動防止を外す。

    「接続完了」や失敗の窓を開いたまま待つ前に呼ぶ。この窓はお客様が閉じるまで
    残るので、持ったままだと、そのあとサイトの合図（aitrader://）で開いた 2 つ目が
    「すでに開いています」で何もせず終わり、合図（使い捨て）だけが消える。
    ロビーは名乗りを待ち続け、「パスポートを呼び出しています」から一生進まない（実機で起きた）。
    窓を出して待つだけの段階では、置く・つなぐの作業は終わっているので、外してよい。
    """
    global _INSTANCE_MUTEX
    if _INSTANCE_MUTEX is None:
        return
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(_INSTANCE_MUTEX)
    except Exception:  # noqa: BLE001
        pass
    _INSTANCE_MUTEX = None


def setup_phase1() -> int:
    """お客様が exe を開いたときの既定の動き。EA を置いて終わる。"""
    banner("初回の設定")
    ui = installer_ui.open_window()

    def say(text: str) -> None:
        log(text)
        if ui:
            ui.say(text)

    # 次にサイトから呼べるように、URL の登録だけしておく（お客様には見えない）。
    # 自動起動（スタートアップ）は連携が済むまで登録しない。
    register_protocol()
    # 古い版が登録した自動起動が残っていると、Windows は古い exe を起こし続ける。
    # まだ連携していないこの状態では、自動起動そのものが要らないので消しておく。
    stale = startup_command()
    if stale:
        log(f"古い自動起動の登録が残っていました: {stale[:120]}")
        unregister_startup("まだ連携していない")

    say("MT5を確認しています…")
    terminals = mt5_detect.list_terminals()
    log(f"見つかった MT5: {mt5_detect.describe(terminals)}")
    if not terminals:
        log("MT5 のデータフォルダが1つも無い")
        tell(
            ui,
            "MT5が見つかりませんでした。",
            "MT5を一度起動してログインしてから、もう一度このアプリを開いてください。",
        )
        return 1

    target = terminals[0]
    # 1台しか無くても選んでもらう。「どの口座に入れたか」をお客様の目で確かめるため
    # （口座番号が画面に出るので、違う口座なら気づける）
    if ui:
        picked = ui.choose_terminal([(str(t.data_path), t.label) for t in terminals])
        if not picked:
            log("選ばずに閉じられたので、何もしません")
            return 1
        for t in terminals:
            if str(t.data_path) == picked:
                target = t
                break
    elif len(terminals) > 1:
        log("画面を出せないので、最後に使った MT5 を選びます")
    say(f"{target.label} が見つかりました。")
    log(f"対象 {target.data_path}")

    source = ea_manager.load_source(BRIDGE_DIR)
    if source is None:
        log(f"同梱の EA が読めない: {BRIDGE_DIR}")
        tell(ui, "設定に必要なファイルが見つかりませんでした。", "アプリを入れ直してから、もう一度お試しください。")
        return 1

    # すでに入っているときは、黙って置き直して終わらせない。
    # ダブルクリックして何も起きないと、お客様は「動いていない」と感じる。
    # いま何が入っているかを見せて、やることを選んでもらう。
    force = False
    while True:
        before = ea_manager.status(target.data_path, source)
        log(f"EA の状態: {before.as_dict()}")
        if ui is None or force or before.state != ea_manager.LATEST:
            break
        choice = ask_what_to_do(ui, target, before, can_switch=len(terminals) > 1)
        log(f"選ばれた操作: {choice}")
        if choice is None:
            log("画面を閉じられたので、何もしません")
            return 0
        if choice == "again":
            force = True
        elif choice == "other":
            picked = ui.choose_terminal([(str(t.data_path), t.label) for t in terminals])
            if not picked:
                log("選ばずに閉じられたので、何もしません")
                return 0
            for t in terminals:
                if str(t.data_path) == picked:
                    target = t
                    break
            say(f"{target.label} に入れます。")
        else:  # このまま使う
            break

    if ui:
        ui.clear_body()
        ui.add_step("mt5", "MT5の確認")
        ui.mark("mt5", True)
        ui.add_step("ea", "自動売買の設定")
    say("自動売買の設定をしています…")

    after = ea_manager.install(target.data_path, source, old_names=OLD_EA_NAMES, force=force, log=log)
    log(f"配置のあとの状態: {after.as_dict()}")
    # MT5 に最初から入っているサンプルを片づける。
    # 十数個並んでいると、お客様がうちのシステムを見つけられない
    ea_manager.tidy_samples(target.data_path, log=log)
    if after.state == ea_manager.ERROR:
        if ui:
            ui.mark("ea", False)
        tell(ui, "設定を保存できませんでした。", "MT5を閉じてから、もう一度このアプリを開いてください。")
        return 1

    if ui:
        ui.mark("ea", True)

    connect_state.write(connect_state.INSTALL_ONLY, terminal=str(target.data_path), ea=after.state)
    # ここから先はサイトで「設置が終わった（つなぐ）」が押されるのを裏で待つ（押されたら自分で紐づく）。
    # 置く作業は終わったので、二重起動の防止もここで外す。外さないと、案内の窓を閉じるまで
    # 合図を受け取っても連携に進めない（VPS で実際に止まった）
    start_link_waiter()
    release_single_instance()

    # その MT5 が動いているかは、プロセス一覧で見る。
    # mt5.initialize() で確かめてはいけない（動いていなければ MT5 を起こしてしまうし、
    # 複数あるときはどれを起こすかも選べない）。
    running = bool(mt5_pids(target.exe))
    log(f"MT5 は{'起動中' if running else '停止中'}: {target.exe}")
    # ついでに、金の銘柄を気配値に出しておく（そのままチャートに出せる）。
    # 動いているときだけ。動いていない MT5 につなぎに行くと、起こしてしまう
    shown = gold_symbol.show_in_market_watch(target.exe, log=log) if running else ""
    restarted = False

    # MT5 を開いたまま置いても、一覧にはすぐ出てこない。開き直すと確実に出る
    if running and ui:
        if ui.ask(
            "MT5を開き直しますか？",
            "開き直す（おすすめ）",
            "あとで自分でやる",
            [
                "MT5は、開いたままだと新しく入れたものを一覧に出しません。",
                "開き直すと、入れたものがすぐ一覧に出ます。",
                "取引中のポジションは消えません。チャートも元に戻ります。",
            ],
        ):
            ui.clear_body()
            ui.clear_buttons()
            ui.say("MT5を開き直しています…")
            restarted = restart_mt5(target, tick=ui.pump)
            running = not restarted

    guide_after_install(
        ui,
        placed=before.state,
        shown=shown,
        needs_restart=running and not restarted,
        account=account_of(target),
    )
    log("初回の設定が終わりました（サイトとは接続していません）")
    return 0


def st_name(st) -> str:
    """お客様に見せる「入っているもの」。MT5 の一覧に出る名前で言う。"""
    version = st.installed_version or st.source_version
    return f"{EA_NAME}（版 {version}）" if version else EA_NAME


def account_of(terminal) -> str:
    """選んだ MT5 の口座番号（表示名「…（口座 123）」から取る）。分からなければ空。"""
    m = re.search(r"口座\s*(\d+)", str(getattr(terminal, "label", "") or ""))
    return m.group(1) if m else ""


def ea_running_here(beat: dict) -> bool:
    """この MT5 で、うちの EA がゴールドのチャートで動いているか。"""
    return bool(beat.get("fresh")) and beat.get("ours") is not False and beat.get("gold") is not False


def beat_hint(beat: dict) -> str:
    """動いていないとき、何が違うかを一言で。該当が無ければ空。"""
    if beat.get("other_account"):
        return f"（いま動いているのは別のMT5（口座 {beat.get('account')}）です。このMT5のチャートに載せてください）"
    if beat.get("fresh") and beat.get("ours") is False:
        return f"（載っているのは「{beat.get('ea')}」です。{EA_NAME} を載せてください）"
    if beat.get("fresh") and beat.get("gold") is False:
        return f"（{beat.get('symbol')} のチャートに載っています。ゴールドのチャートに載せてください）"
    if beat.get("seen") and not beat.get("fresh"):
        return "（前は動いていましたが、いまは止まっています）"
    return ""


def ask_what_to_do(ui, target, st, *, can_switch: bool) -> str | None:
    """すでに入っているときに出す画面。

    「いま入っているのはこれです」を見せてから、やることを選んでもらう。
    ここで黙って終わると、押しても何も起きないアプリになってしまう。
    """
    beat = ea_manager.heartbeat(account=account_of(target))
    log(f"EA の動き: {beat}")
    lines = [
        f"入っているもの： {st_name(st)}",
        f"入れたMT5： {target.label}",
    ]
    hint = beat_hint(beat)
    if ea_running_here(beat):
        where = beat["symbol"] or "チャート"
        lines.append(f"いまの様子： {where} のチャートで動いています")
    elif hint:
        lines.append("いまの様子： " + hint.strip("（）"))
    else:
        lines.append("いまの様子： まだチャートに載せていません")

    options = [("use", "このまま使う"), ("again", "設置しなおす")]
    if can_switch:
        options.append(("other", "別のMT5に入れる"))
    return ui.menu("パスポートは、すでに設定が済んでいます。", lines, options)


# MT5 でお願いする操作。ここだけは外から自動化できない
# （チャートを開くことも、時間足を変えることも、MT5 は外部に開いていない）
CHART_STEPS = (
    "1. MT5の左側にある「ナビゲーター」を開きます。",
    f"2. 「{EA_NAME}」を、ゴールドの1分足チャートにドラッグします。",
    "3. 画面の上にある「アルゴ取引」のボタンを押して、緑色にします。",
)


def guide_after_install(ui, *, placed: str, shown: str, needs_restart: bool, account: str = "") -> None:
    """設置が済んだあとの案内。

    「すでに入っています」で終わると、お客様はそこで止まってしまう。
    置いただけでは何も動かない（チャートに載せて初めて動く）ので、
    いまどこまで進んだかを見せて、次の一手だけを出す。

    済んだかどうかは EA 自身が書く控えで分かるので、「できたので確かめる」を
    押してもらえば、その場で見て次へ進める。
    """
    if placed == ea_manager.NOT_INSTALLED:
        head = f"「{EA_NAME}」をMT5に追加しました。"
    elif placed == ea_manager.UPDATE_AVAILABLE:
        head = f"「{EA_NAME}」を新しい内容に更新しました。"
    else:
        head = f"「{EA_NAME}」はすでにMT5に入っています。"

    if ui is None:
        # 窓を作れなかったとき。せめて「何が起きたか」だけは見せる
        beat = ea_manager.heartbeat(account=account)
        lines = [head] if ea_running_here(beat) else [head, "", *CHART_STEPS]
        installer_ui.message_box("\n".join(lines))
        return

    while ui.alive():
        beat = ea_manager.heartbeat(account=account)
        log(f"EA の動き: {beat}")
        if ea_running_here(beat):
            lines = [head]
            where = beat["symbol"] or "チャート"
            lines.append(f"{where} で動いています。準備ができました。")
            lines.append("このアプリは閉じていただいて構いません。")
            release_single_instance()
            ui.finish(lines, ok=True)
            return

        lines = [head, ""]
        lines.extend(CHART_STEPS)
        lines.append("")
        if shown:
            lines.append(f"（{shown} は、すぐ出せるように気配値表示に出してあります）")
        if needs_restart:
            lines.append("（一覧に出てこないときは、MT5を一度閉じて開き直してください）")
        hint = beat_hint(beat)
        if hint:
            lines.append(hint)

        if not ui.ask("あと1つだけ、MT5での操作をお願いします。", "できたので確かめる", "あとでやる", lines):
            log("チャートへの設置は、あとで行うことになりました")
            return


def mt5_pids(exe: Path | None) -> list[int]:
    """その MT5（terminal64.exe）が動いていれば、その番号。"""
    if os.name != "nt" or exe is None:
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
             "ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)\" }"],
            capture_output=True, text=True, errors="replace", timeout=30,
            creationflags=_no_window_flags(), startupinfo=_hidden_startupinfo(),
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    want = str(exe).lower()
    pids: list[int] = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        pid_text, _, path = line.partition("|")
        if path.strip().lower() == want:
            try:
                pids.append(int(pid_text.strip()))
            except ValueError:
                continue
    return pids


def restart_mt5(terminal: "mt5_detect.Terminal", tick=None) -> bool:
    """MT5 を開き直して、ナビゲーターに新しい EA を出す。

    MT5 は、開いたまま置いた EA をすぐには一覧に出さない（更新を押すまで）。
    外から「更新」を押させる方法が無いので、開き直すのがいちばん確実。

    建玉や注文はサーバー側にあるので、開き直しても消えない。
    チャートや時間足も、MT5 が覚えていて元に戻る。

    tick は待っているあいだに呼ぶ（画面を固まらせないため）。
    """
    exe = terminal.exe
    if exe is None:
        log("MT5 の実行ファイルが分からないので、開き直しは省きます")
        return False
    pids = mt5_pids(exe)
    if not pids:
        log("MT5 は起動していないので、開き直しは要りません")
        return False

    log(f"MT5 を閉じます（{len(pids)} 個）")
    for pid in pids:
        try:
            run_hidden(["taskkill", "/PID", str(pid)], timeout=30)  # まず穏やかに
        except Exception:  # noqa: BLE001
            pass
    for pid in pids:
        if not wait_gone(pid, 20.0, tick=tick):
            log(f"閉じないので、強制的に終了します（{pid}）")
            kill_process(pid)
            wait_gone(pid, 10.0, tick=tick)

    for _ in range(4):
        time.sleep(0.5)
        if tick:
            tick()
    log(f"MT5 を開き直します: {exe}")
    # ここは spawn_hidden を使わない。あれは「窓を出さない」指定つきで起こすので、
    # MT5 がその指定に従うと、開き直したはずの MT5 が画面に出てこない。
    launch_mt5(exe)
    return True


def choose_terminal() -> int:
    """使う MT5 を選び直す（--choose）。

    MT5 が何台もある PC で、別の MT5 に入ってしまったときに使う。
    選んだ結果を覚えるので、次からはそこに固定される。
    """
    banner("使う MT5 を選び直す")
    terminals = mt5_detect.list_terminals()
    if not terminals:
        log("MT5 が見つかりません")
        return 1
    log(f"見つかった MT5: {mt5_detect.describe(terminals)}")

    ui = installer_ui.open_window()
    target = terminals[0]
    if ui:
        picked = ui.choose_terminal([(str(t.data_path), t.label) for t in terminals])
        if not picked:
            # ✕ で閉じられた。勝手に1台目を選ばない
            log("選ばずに閉じられたので、何もしません")
            return 1
        for t in terminals:
            if str(t.data_path) == picked:
                target = t
                break
    elif len(terminals) > 1:
        log("画面を出せないので、最後に使った MT5 を選びます")

    connect_state.write(connect_state.current(), terminal=str(target.data_path))
    log(f"これから使う MT5: {target.label} / {target.data_path}")

    source = ea_manager.load_source(BRIDGE_DIR)
    if source is not None:
        after = ea_manager.install(target.data_path, source, old_names=OLD_EA_NAMES, log=log)
        log(f"EA の状態: {after.as_dict()}")
    shown = gold_symbol.show_in_market_watch(target.exe, log=log)

    if ui:
        lines = [f"{target.label} を使うようにしました。"]
        if shown:
            lines.append(f"{shown} を気配値表示に出しました。")
        lines.append("このアプリは閉じていただいて構いません。")
        release_single_instance()
        ui.finish(lines, ok=True)
    return 0


def install_ea_only() -> int:
    banner("システムの配置だけ")
    session = find_logged_in_terminal()
    if not session:
        log("MT5 にログインしていません")
        return 1
    copy_ea_files(session)
    write_bridge_env(session)
    return 0


def _tail(path: Path, n: int = 25) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _protocol_command() -> str:
    """aitrader:// を押したときに Windows が実行するコマンド（登録が無ければ空）"""
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}\shell\open\command") as key:
            return str(winreg.QueryValueEx(key, None)[0])
    except (ImportError, OSError):
        return ""


def show_status() -> int:
    """つながらないとき、原因を一目で見られるように、いまの状態を全部出す。"""
    banner("いまの状態")
    state = connect_state.read()
    log(f"連携            : {state.get('state')}"
        + (f"（{state.get('room')}）" if state.get("room") else "")
        + "  ※ INSTALL_ONLY はEAを置くだけ／CONNECTED はサイトと通信する")
    terminals = mt5_detect.list_terminals()
    log(f"見つかった MT5  : {mt5_detect.describe(terminals)}")
    source = ea_manager.load_source(BRIDGE_DIR)
    for t in terminals:
        log(f"  {t.label}: EA {ea_manager.status(t.data_path, source).state}")
    log(f"手元の版        : {source_version() or '不明'}")
    log(f"中継の接続先    : {relay_url()}")
    log(f"この PC の部屋  : {env_value('BRIDGE_ID') or '（未設定 → vps-01）'}")
    log(f"設定ファイル    : {env_file()}")
    print()
    lock = bridge_lock_path()
    if lock.is_file():
        log(f"ロック          : {lock}")
        log(f"  番号 / 版 / 部屋: {lock_pid() or '不明'} / {running_version() or '不明'} / {running_room() or '不明'}")
        log(f"  ロック中        : {'はい（ブリッジが動いている）' if bridge_already_running() else 'いいえ'}")
    else:
        log(f"ロック          : なし（{lock}）")
    procs = list_bridge_processes()
    if procs:
        for pid, image in procs:
            log(f"動いているブリッジ: PID {pid} / {image}")
    else:
        log("動いているブリッジ: 見つかりません")
    print()
    our_id = env_value("BRIDGE_ID") or "vps-01"
    health = relay_health(our_id)
    if health is None:
        log("中継 /health    : 応答なし（中継が動いていない、または届かない）")
    else:
        here = (health.get("room") or {}).get("bridge")
        log(f"中継 /health    : 応答あり  ブリッジ {health.get('bridges', '?')} 台 / この部屋（{our_id}）に居る = {'はい' if here else 'いいえ'}")
    cmd = _protocol_command()
    log(f"{PROTOCOL}:// の登録: {cmd or '未登録（サイトのボタンから起動できません）'}")
    print()
    for name in ("connect.log", "bridge.log"):
        path = CONFIG_DIR / name
        log(f"--- {path} の末尾 ---")
        for line in _tail(path):
            print(f"    {line}")
        print()
    return 0


# 「選んだ MT5 にログインしていません」のときの案内。
# Windows は MT5 本体に聞くのでこの文でよいが、Mac は EA がチャートで書く控えでしか
# 口座を読めないので、connect_mac._patch が「EA を載せてください」に差し替える。
LOGIN_MISSING_TITLE = "{label} にログインしていません。"
LOGIN_MISSING_LINES = (
    "そのMT5でログインしてから、もう一度このアプリを開いてください。",
    "ほかのMT5を使うときは「別のMT5を選ぶ」を押してください。",
)
# 空なら「別のMT5を選ぶ／閉じる」の2択。文字があれば「<これ>／別のMT5を選ぶ」になり、
# 押すと（または条件が整うと）確かめ直す
LOGIN_RETRY_LABEL = ""
LOGIN_WAIT_TEXT = "MT5 へのログインを待っています"
LOGIN_TIMEOUT_MESSAGE = ("MT5にログインできていません。", "MT5で口座にログインしてから、もう一度このアプリを開いてください。")
# 繋ぐ MT5 が決まった直後に呼ぶ（Mac は、ログインを読み取る前に EA を置いておく必要がある）
PREPARE_TERMINAL = None


def connect_all(room: str = "", show: bool = False) -> int:
    """サイトのボタン1つで呼ばれる本体。

    show=True のときだけ、小さな画面を出す。
    連携が済むと初回の設定（setup_phase1）は走らないので、お客様が自分で
    アプリを開いても何も起きなくなる。それでは「開かない・壊れた」としか
    見えないため、手で開いたときだけ結果を知らせる。
    サイトから呼ばれたとき（合図つき）と自動起動では、これまでどおり出さない。
    """
    banner("接続開始")
    ui = installer_ui.open_window() if show else None
    global _UI_FOR_PUMP
    _UI_FOR_PUMP = ui

    def say(text: str) -> None:
        log(text)
        if ui:
            ui.say(text)

    def give_up(message: str, hint: str = "") -> int:
        tell(ui, message, hint)
        return 1

    if room:
        adopt_room(room)
        # 設置のあとに残った「合図を待つ係」は、もう要らない（壊れた係が合図を横取りするのを防ぐ）
        run_pumping(stop_link_waiters)
        if run_pumping(lambda: bridge_already_running() and relay_has_bridge(room) is not True):
            run_pumping(stop_stale_bridge)

    # 次からサイトのボタンで起動できるようにする（初回だけ効く）
    register_protocol()
    register_startup()

    # どの MT5 に繋ぐか。覚えていればそこ。覚えていなくて複数あれば、選んでもらう。
    # 「ログイン中のどれか」に黙って繋ぐと、MT5 が何台もある PC では
    # 別の口座につながってしまう（しかもお客様には分からない）。
    say("MT5を確認しています…")
    # 手で開いたときは毎回選んでもらう。黙って繋ぐと、お客様は「勝手に繋いだ」としか見えない
    picked = choose_session(ui, log=log, always_ask=ui is not None)
    if picked is None:
        return 1
    session, chosen = picked
    if session is None:
        say("MT5を開いています…")
        target = next((t for t in mt5_detect.list_terminals() if _same_path(t.data_path, chosen)), None) if chosen else None
        exe = (target.exe if target else None) or find_mt5_exe() or ensure_mt5()
        if exe is None:
            return give_up(
                "MT5が見つかりませんでした。",
                "MT5を開いてログインしてから、もう一度このアプリを開いてください。",
            )
        launch_mt5(exe)
        say(LOGIN_WAIT_TEXT + "…")
        session = wait_for_login(prefer=chosen or None)
        if session is None or (chosen and not _same_path(session.get("data_path", ""), chosen)):
            return give_up(*LOGIN_TIMEOUT_MESSAGE)

    try:
        run_pumping(lambda: copy_ea_files(session))
    except SystemExit as exc:
        log(str(exc))
        return give_up(
            "設定を保存できませんでした。",
            "MT5を閉じてから、もう一度このアプリを開いてください。",
        )
    write_bridge_env(session)
    # 使った MT5 を覚える。次からはここが優先され、別の MT5 に入らない。
    # 口座番号も覚える（追加口座＝別の口座番号の合図が来たときに、1 本目と見分けるため）
    used = str(session.get("data_path") or "")
    if used:
        connect_state.write(connect_state.current(), terminal=used, account=str(session.get("account") or ""))
    run_pumping(lambda: gold_symbol.show_in_market_watch(resolve_terminal_exe(session), log=log))

    url = relay_url()
    if relay_is_local(url) and not relay_is_up():
        start_relay()
        wait_seconds(2)
    say("サイトにつないでいます…")
    run_pumping(lambda: start_bridge(session))

    banner("接続完了")
    log(f"口座 {session['account']} / {session['server']}")
    if show:
        # 待つのは1回だけ（ここで最大25秒。二度聞くと待ち時間も二倍になる）。
        # ブリッジは同じ exe をもう一度展開して起きるので、名乗り出るまで 6〜15 秒かかる。
        seen = relay_sees_us()
        lines = connect_result_lines(session, seen)
        release_single_instance()  # 窓を開いたままでも、次にサイトから呼ばれたら動けるように
        if ui:
            # MT5 につながっていれば設定は済んでいる。中継にまだ届いていないのは
            # 「失敗」ではなく「時間がかかっている」だけなので、見出しは完了にする
            ui.finish(lines, ok=True)
        else:
            installer_ui.message_box("\n".join(lines))
    return 0


def _same_path(a: object, b: object) -> bool:
    return str(a or "").rstrip("\\/").lower() == str(b or "").rstrip("\\/").lower()


def choose_session(ui, log=log, always_ask: bool = False) -> tuple[dict | None, str] | None:
    """繋ぐ MT5 を決めて、ログイン済みならそのセッションを返す。

    返り値は (session, 選んだ MT5 のデータフォルダ)。session が None なら
    「選んだ MT5 にまだログインしていない」。None（全体）は「お客様がやめた」。

      ・always_ask（手で開いたとき）は、覚えていても毎回選んでもらう。
        覚え書きは前の版が勝手に書いたものかもしれないので、信じて黙って繋がない。
        覚えているものは一覧の先頭に出す
      ・画面が無いとき（自動起動など）は、覚えている MT5 にしか繋がない。
        別の MT5 にログインしていても乗り換えない
      ・覚えていなければ、選んでもらって覚える（1台でも画面に出して確かめてもらう）
    """
    terminals = mt5_detect.list_terminals()
    chosen = str(connect_state.read().get("terminal") or "")
    if chosen and not any(_same_path(t.data_path, chosen) for t in terminals):
        log(f"覚えていた MT5 がもう無いので、選び直します: {chosen}")
        chosen = ""

    def remember(path: str) -> None:
        connect_state.write(connect_state.current(), terminal=path)

    def ask_pick() -> str:
        # 1台でも選んでもらう（口座番号を見て確かめてもらうため）。覚えているものを先頭に
        if ui is None:
            return str(terminals[0].data_path) if terminals else ""
        ordered = sorted(terminals, key=lambda t: 0 if _same_path(t.data_path, chosen) else 1)
        got = ui.choose_terminal([(str(t.data_path), t.label) for t in ordered])
        return str(got or "")

    if ui is not None and always_ask and terminals:
        picked = ask_pick()
        if not picked:
            log("選ばずに閉じられたので、何もしません")
            return None
        if chosen and not _same_path(picked, chosen):
            log(f"MT5 を選び直しました: {chosen} → {picked}")
        chosen = picked
        remember(chosen)

    if not chosen:
        if len(terminals) > 1 and ui is None:
            log("画面を出せないので、ログイン中の MT5 を使います")
            session = find_logged_in_terminal()
            return (session, str(session.get("data_path", "")) if session else "")
        chosen = ask_pick()
        if not chosen:
            log("選ばずに閉じられたので、何もしません")
            return None
        remember(chosen)

    if chosen and PREPARE_TERMINAL:
        PREPARE_TERMINAL(chosen)

    # Mac（LOGIN_RETRY_LABEL あり）は EA が載るまで何度でも確かめ直す。Windows はこれまでどおり 3 回
    for _ in range(60 if LOGIN_RETRY_LABEL else 3):
        session = run_pumping(lambda: find_logged_in_terminal(chosen))
        if session and _same_path(session.get("data_path", ""), chosen):
            log(f"選んだ MT5 を使います: {session.get('account')} / {session.get('server')}")
            return (session, chosen)
        label = next((t.label for t in terminals if _same_path(t.data_path, chosen)), "選んだMT5")
        if session:
            log(f"選んだ MT5 に繋げません。ログイン中なのは別の MT5: {session.get('account')}")
        else:
            log("選んだ MT5 にログインしていません")
        if ui is None:
            # 画面が無い（自動起動など）ときは、乗り換えずに「まだログインしていない」扱い
            return (None, chosen)
        title = LOGIN_MISSING_TITLE.format(label=label)
        if LOGIN_RETRY_LABEL:
            # 「確かめ直す／別のMT5を選ぶ」。条件が整えば（EA が載れば）押さなくても先へ進む
            ready = lambda: find_logged_in_terminal(chosen) is not None  # noqa: E731
            if hasattr(ui, "ask_or_wait"):
                answer = ui.ask_or_wait(title, LOGIN_RETRY_LABEL, "別のMT5を選ぶ", list(LOGIN_MISSING_LINES), check=ready)
            else:
                answer = "yes" if ui.ask(title, LOGIN_RETRY_LABEL, "別のMT5を選ぶ", list(LOGIN_MISSING_LINES)) else "no"
            if answer == "closed":
                return None
            if answer in ("yes", "ready"):
                continue
        elif not ui.ask(title, "別のMT5を選ぶ", "閉じる", list(LOGIN_MISSING_LINES)):
            return None
        picked = ask_pick()
        if not picked:
            return None
        chosen = picked
        remember(chosen)
    return (None, chosen)


def show_failure(message: str, hint: str = "") -> int:
    """画面を出して「次に何をすればいいか」だけ伝え、1 を返す。

    画面を出せない環境（tkinter が無いなど）では、記録に残すだけで済ませる。
    """
    tell(installer_ui.open_window(), message, hint)
    return 1


def relay_sees_us(tries: int = 25) -> bool | None:
    """サイトから、この PC のブリッジが見えているか。

    ブリッジは起こしてから名乗り出るまで数秒かかるので、少し待って何度か聞く。
    中継に届かないときは None（つながっていない、とは言い切れない）。
    """
    our_id = env_value("BRIDGE_ID") or "vps-01"
    seen: bool | None = None
    for i in range(max(1, tries)):
        seen = run_pumping(lambda: relay_has_bridge(our_id))
        if seen:
            return True
        if i + 1 < tries:
            wait_seconds(1)
    return seen


def connect_result_lines(session: dict, seen: bool | None) -> list[str]:
    """手で開いたときに見せる、結果のことば。専門用語は出さない。"""
    lines = [f"MT5（口座 {session['account']}）につながりました。"]
    if seen is True:
        lines.append("サイトからも見えています。そのままお使いください。")
    elif seen is False:
        lines.append("サイトからはまだ見えていません。")
        lines.append("30秒ほど待ってから、サイトの画面を開き直してください。")
    else:
        lines.append("インターネットにつながっているか確かめてから、もう一度お試しください。")
    return lines


def main() -> int:
    global CONSOLE
    raw_args = [a for a in sys.argv[1:]]
    # 外から連携を始められる入口は、合図（token）ただ1つ。
    # aitrader://connect?room=... は受け付けない（会員IDを知っているだけの相手が
    # 勝手に連携できてしまうため）。すでに使っているお客様の引き継ぎは、
    # URL ではなく、その PC に残っている bridge.env から行う（adopt_legacy）。
    connect_token = connect_token_from_args(raw_args)
    room = ""
    args = [a for a in raw_args if not is_protocol_url(a)]
    CONSOLE = "--console" in args or "--self-test" in args
    # ダウンロードしたファイルを「開いただけ」のとき（引数なし）は、ファイル名の合図で連携する。
    # 以前に別の口座でつないだ PC でも、その合図の口座へ切り替える（adopt_room）。
    # 同じファイルを後で開き直したとき（合図は使い終わっている）は、連携済みならふつうに開いた扱いにする。
    # 自動起動（--startup）や裏のブリッジ（--run-bridge）は同じ exe なので、引数があれば見ない。
    exe_token = False
    if not connect_token and FROZEN and not args:
        connect_token = connect_token_from_exe_name()
        exe_token = bool(connect_token)
        if connect_token:
            log("ファイル名の合図で連携します")

    os.chdir(str(ROOT))
    log(f"起動 argv={raw_args} frozen={FROZEN} room={room or '-'}")
    # 窓を出さずに動く経路（自動起動・裏のブリッジ・道具類）では、
    # 起動中の画像を出したままにしない。窓を出す経路では、窓が出たときに消える
    if "--startup" in args or "--run-bridge" in args or connect_token or CONSOLE or any(
        a.startswith("--") for a in args if a not in ("--silent", "--from-site")
    ):
        installer_ui.close_splash()

    # はじめる.bat から「中継の接続先」を受け取る。.env を丸ごと書き直すと
    # サイトから受け取った部屋（BRIDGE_ID）が消えて E003 になるので、1項目だけ直す。
    if "--relay" in args:
        idx = args.index("--relay")
        target = args[idx + 1].strip() if idx + 1 < len(args) else ""
        if target:
            write_env_key("TRELAB_WS_URL", target)
            os.environ["TRELAB_WS_URL"] = target
            log(f"中継の接続先: {target}")
        del args[idx : idx + 2]

    if "--wait-link" in args:  # 設置のあと、サイトの「設置が終わった」を裏で待つ係
        return wait_for_link()
    if "--run-bridge" in args:  # exe 版が自分自身をブリッジとして動かすとき
        sys.argv = [sys.argv[0]]
        import bridge

        return bridge.main()
    if "--self-test" in args:
        return self_test()
    if "--install-ea" in args:
        return install_ea_only()
    if "--register" in args:
        return 0 if (register_protocol() and register_startup()) else 1
    if "--status" in args:
        return show_status()
    if "--stop" in args:
        banner("接続をやめる")
        stop_all_bridges(include_slots=True)
        return 0
    if "--uninstall" in args:
        banner("登録をすべて消す")
        stop_all_bridges(include_slots=True)
        return unregister()

    if "--setup" in args:
        return setup_phase1()
    if "--choose" in args:
        code = choose_terminal()
        if code == 0 and connect_state.is_connected():
            # 選び直したので、ブリッジもそちらでつなぎ直す
            stop_all_bridges()
            return connect_all("")
        return code

    # 同じアプリがもう開いていれば、そちらに任せる（二つ同時に置きに行かない）。
    # 合図（使い捨て）を確かめる前に見る。あとで見ると、合図だけ消えて何も起きない。
    if not hold_single_instance():
        log("すでに開いているので、こちらは何もしない")
        if connect_token:
            installer_ui.message_box(
                "パスポートの画面が開いたままです。\n\n"
                "その画面を閉じてから、サイトの「設置が終わった（つなぐ）」をもう一度押してください。"
            )
        else:
            installer_ui.message_box("パスポートは、すでに開いています。\n開いている画面をご覧ください。")
        return 0

    # サイトの「MT5と連携する」から呼ばれたとき。
    # 合図が正しいときだけ連携する（アプリ単体では連携できない）。
    if connect_token:
        banner("サイトとの連携")
        room = redeem_connect_token(connect_token)
        if not room and exe_token and connect_state.is_connected():
            # 同じファイルを後で開き直した（合図は使い終わっている）。連携済みなので、
            # 失敗と言わずに、ふつうに開いたときと同じ動きにする
            log("ファイル名の合図は使えませんでしたが、連携済みなのでそのまま続けます")
            connect_token = ""
        elif not room and exe_token:
            # ダウンロードしたファイルの合図が切れている（時間が経ってから開いた）。
            # 失敗と言わずに初回の設定へ進む。設置のあとは「設置が終わった」の合図を裏で待つので、
            # ロビーで押してもらえば紐づく
            log("ファイル名／ダウンロード元の合図は切れていました。初回の設定へ進みます")
            connect_token = ""
        elif not room:
            # ここで黙って終わると、サイトのボタンを押しても何も起きないように見える
            log("連携できませんでした。サイトでもう一度お試しください")
            return show_failure(
                "サイトとつなげませんでした。",
                "サイトの画面に戻って、もう一度「初期設定をはじめる」を押してください。",
            )

    # すでにサイトと連携して使っている PC を引き継ぐ（state.json がまだ無い場合）
    if connect_state.adopt_legacy(env_value("BRIDGE_ID")):
        log("これまでの設定から、連携済みとして引き継ぎました")

    # 追加口座（ロイヤルファーストクラスの 2 つ目）：この PC はすでに別の口座で連携済みで、
    # 合図に付いてきた口座番号が 1 本目と違い、その口座の MT5 がこの PC にある → その MT5 専用の
    # ブリッジを 1 本足す。1 本目はそのまま。該当しなければ、これまでどおり 1 本目を切り替える
    if room and os.name == "nt":
        wanted = account_from_args(raw_args)
        mine = primary_account()
        if wanted and mine and wanted != mine and connect_state.is_connected() and terminal_for_account(wanted) is not None:
            return connect_slot(room, wanted)

    # Windows の起動時に呼ばれたとき（--startup）。
    # 自動起動は「つながっていたものを戻す」ためのもの。まだ連携していない PC では
    # 戻すものが無いので、何もしないで終わる。ここで初回の設定を始めると、
    # ログインのたびに画面が開いてしまう（古い版が登録した自動起動が残っている PC）。
    if "--startup" in args and not connect_state.is_connected():
        log("自動起動で呼ばれたが、まだ連携していないので、合図を待つだけにする")
        start_link_waiter()
        return 0

    # 部屋が渡されていない（＝サイトからではなく、自分で開いた）とき。
    # 連携が済んでいなければ、EA を置くだけで終わる。
    if not room and not connect_state.is_connected():
        code = setup_phase1()
        if CONSOLE:
            print()
            input("  続けるには Enter を押してください...")
        return code

    # 黙って動いてよいのは自動起動のときだけ。
    # それ以外（手で開く・サイトのボタン）は、必ず結果を画面に出す。
    # 何も出ないと、お客様には「開かない・壊れた」としか見えない。
    code = connect_all(room, show="--startup" not in args and not CONSOLE)
    if "--startup" in args and os.name == "nt":
        start_slot_bridges()
    if CONSOLE:
        print()
        input("  続けるには Enter を押してください...")
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
