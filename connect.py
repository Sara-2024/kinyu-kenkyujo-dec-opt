#!/usr/bin/env python3
"""
お客様向け接続ツール。

普段は画面に何も出さずに動く（黒い画面を出さない）。やることは4つ:

  1. 起動中の MT5 があればそれを使う（無ければ起動／未導入なら公式インストーラ）
  2. ログイン済みターミナルへ システム(EA) をコピーしてコンパイル
  3. ブリッジを裏側で起動して、中継サーバーにつなぐ
  4. サイトのボタンから起動できるよう trelab:// を登録し、
     次回からPCの起動時にも自動でつながるようにする

サイトに口座パスワードは一切渡さない。

  TrelabConnect.vbs をダブルクリック   … 画面を出さずに全部やる
  python connect.py --console          … 経過を画面に出す（調査用）
  python connect.py --install-ea       … システムの配置だけ
  python connect.py --register         … サイト連携の登録だけ
  python connect.py --uninstall        … 登録の解除
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
# PyInstaller で1つの exe にまとめた場合、EA などの同梱物はここに展開される
ASSETS = Path(getattr(sys, "_MEIPASS", ROOT))
BRIDGE_DIR = ASSETS / "bridge"
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(BRIDGE_DIR))

from mt5_terminal import (  # noqa: E402
    find_logged_in_terminal,
    find_metaeditor,
    probe_ea_files,
    resolve_terminal_exe,
    terminal_dir_from_data_path,
)

MT5_SETUP_URL = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"

EA_FILES = ("SiteTestEA.mq5", "TrelabEA.mq5", "TrelabGate.mq5")
INCLUDE_FILES = ("TradingGate.mqh",)

APP_NAME = "TrelabConnect"
PROTOCOL = "trelab"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

SEARCH_EXES = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "MetaTrader 5" / "terminal64.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "MetaTrader 5" / "terminal.exe",
]

# 画面に出すかどうか。既定は「出さない」
CONSOLE = False


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TMPDIR") or "/tmp"
    path = Path(base) / "Trelab"
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


def run_hidden(cmd: list[str], cwd: str | None = None, timeout: float | None = None) -> int:
    """終わるまで待つ。ウィンドウは出さない。"""
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
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
            env=env,
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


def launch_command(*args: str) -> list[str]:
    """このツール自身を、画面を出さずに起動するためのコマンド"""
    if FROZEN:
        return [sys.executable, *args]
    return [pythonw(), str(ROOT / "connect.py"), *args]


# ────────────────────────────────────────────────
# サイトのボタンから起動できるようにする（trelab://）
#   ブラウザは仕組み上、勝手にPCのソフトを起動できない。
#   一度この登録をしておけば、以後はサイトのボタン1つで起動できる。
# ────────────────────────────────────────────────
def register_protocol() -> bool:
    if os.name != "nt":
        log("Windows ではないので trelab:// の登録は省略します")
        return False
    try:
        import winreg
    except ImportError:
        return False

    command = " ".join(f'"{part}"' for part in launch_command("--silent", "--from-site")) + ' "%1"'
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:Trelab Connect")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}\shell\open\command") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
        log(f"サイトから起動できるようにしました: {PROTOCOL}://")
        return True
    except OSError as exc:
        log(f"trelab:// を登録できませんでした: {exc}")
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
        log("PCの起動時にも自動でつながるようにしました")
        return True
    except OSError as exc:
        log(f"スタートアップに登録できませんでした: {exc}")
        return False


def unregister() -> int:
    if os.name != "nt":
        return 0
    try:
        import winreg
    except ImportError:
        return 0
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        log("スタートアップの登録を消しました")
    except OSError:
        pass
    for sub in (
        rf"Software\Classes\{PROTOCOL}\shell\open\command",
        rf"Software\Classes\{PROTOCOL}\shell\open",
        rf"Software\Classes\{PROTOCOL}\shell",
        rf"Software\Classes\{PROTOCOL}",
    ):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass
    log("trelab:// の登録を消しました")
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


def wait_for_login(timeout_sec: int = 600) -> dict | None:
    try:
        import MetaTrader5  # noqa: F401
    except ImportError:
        log("MetaTrader5 パッケージがありません（setup-windows.bat を先に実行してください）")
        return None

    existing = find_logged_in_terminal()
    if existing:
        log(f"ログイン済み: {existing['account']} / {existing['server']}")
        return existing

    banner("MT5 へのログインを待っています")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        status = find_logged_in_terminal()
        if status:
            log(f"ログインを確認: {status['account']} / {status['server']}")
            return status
        time.sleep(2)
    log("ログインを確認できませんでした（時間切れ）")
    return None


def read_compile_log(mq5: Path) -> str:
    for candidate in (mq5.with_suffix(".log"), mq5.parent / "MQL5" / "Logs" / "metaeditor.log"):
        if not candidate.is_file():
            continue
        for encoding in ("utf-16", "utf-8", "cp932"):
            try:
                text = candidate.read_text(encoding=encoding, errors="ignore")
            except OSError:
                continue
            if text.strip():
                return text.strip()[-2500:]
    return ""


def compile_mq5(editor: Path, mq5: Path, terminal_dir: Path | None) -> bool:
    log(f"コンパイル: {mq5.name}")
    ex5 = mq5.with_suffix(".ex5")
    if ex5.is_file():
        try:
            ex5.unlink()
        except OSError:
            pass

    run_hidden(
        [str(editor), f"/compile:{mq5}", "/log"],
        cwd=str(terminal_dir) if terminal_dir else None,
        timeout=180,
    )

    for _ in range(120):
        if ex5.is_file():
            log(f"OK  {ex5.name}")
            return True
        time.sleep(0.25)

    log(f"注意  {ex5.name} ができませんでした")
    tail = read_compile_log(mq5)
    for line in tail.splitlines()[-12:]:
        log(f"  | {line}")
    return False


def verify_ea_install(data_path: str) -> tuple[bool, dict]:
    probe = probe_ea_files(data_path)
    ok = probe["include_ok"] and "SiteTestEA" in probe["ea_found"]
    if ok and "SiteTestEA" not in probe["ea_compiled"]:
        log("注意  SiteTestEA.mq5 はありますが .ex5 がまだありません")
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

    terminal_exe = resolve_terminal_exe(session)
    terminal_dir = terminal_exe.parent if terminal_exe else terminal_dir_from_data_path(data_path)

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
        src = BRIDGE_DIR / name
        if not src.is_file():
            raise SystemExit(f"元ファイルがありません: {src}")
        shutil.copy2(src, experts / name)
        log(f"OK  Experts\\{name}")

    editor = find_metaeditor(data_path, terminal_exe)
    if editor:
        for name in EA_FILES:
            compile_mq5(editor, experts / name, terminal_dir)
    else:
        log("注意  metaeditor64.exe が見つかりません（MT5 の F4 から手動コンパイル）")

    ok, probe = verify_ea_install(data_path)
    if editor and "SiteTestEA" not in probe["ea_compiled"]:
        ok = False
    log(f"確認 Include/TradingGate.mqh : {'OK' if probe['include_ok'] else 'なし'}")
    log(f"確認 Experts/SiteTestEA.mq5 : {'OK' if 'SiteTestEA' in probe['ea_found'] else 'なし'}")
    log(f"確認 Experts/SiteTestEA.ex5 : {'OK' if 'SiteTestEA' in probe['ea_compiled'] else 'なし'}")

    # 画面に出さない方針なので、エクスプローラは調査モードのときだけ開く
    if CONSOLE and os.name == "nt":
        try:
            os.startfile(probe["experts_dir"])  # type: ignore[attr-defined]
        except OSError:
            pass

    if not ok:
        raise SystemExit("システムの配置が終わりませんでした（connect.log を確認）")
    return experts


def write_bridge_env(session: dict) -> None:
    """ブリッジが同じ MT5 ターミナル（いまログイン中の口座）へ繋ぐよう .env を更新する。"""
    exe = resolve_terminal_exe(session)
    if exe is None:
        return
    env_path = env_file()
    key = "MT5_PATH"
    val = str(exe)
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
        log(f"ブリッジが使う MT5: {val}")
    except OSError as exc:
        log(f".env を書けませんでした: {exc}")


# ────────────────────────────────────────────────
# 中継とブリッジ
# ────────────────────────────────────────────────
def env_value(key: str) -> str:
    """設定ファイルから1項目だけ読む（環境変数が優先）"""
    if os.environ.get(key):
        return os.environ[key].strip()
    for path in (env_file(), BRIDGE_DIR / ".env"):
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
    return env_value("TRELAB_WS_URL") or "ws://127.0.0.1:8080/bridge"


def relay_is_local(url: str) -> bool:
    return "127.0.0.1" in url or "localhost" in url


def relay_is_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1.5) as res:
            return res.status == 200
    except Exception:  # noqa: BLE001
        return False


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
    lock = Path(os.environ.get("TEMP", "/tmp")) / "trelab-bridge.lock"
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


def bridge_env(session: dict | None) -> dict[str, str]:
    env = dict(os.environ)
    env["TRELAB_WS_URL"] = relay_url()
    token = env_value("TRELAB_TOKEN")
    if token:
        env["TRELAB_TOKEN"] = token
    env["LOG_FILE"] = str(CONFIG_DIR / "bridge.log")
    if session:
        exe = resolve_terminal_exe(session)
        if exe is not None:
            env["MT5_PATH"] = str(exe)
    return env


def start_bridge(session: dict | None = None) -> None:
    if bridge_already_running():
        log("ブリッジはすでに動いています")
        return
    if FROZEN:
        cmd = [sys.executable, "--run-bridge"]
    else:
        cmd = [pythonw(), str(BRIDGE_DIR / "bridge.py")]
    log(f"ブリッジを裏側で起動します（接続先 {relay_url()}）")
    spawn_hidden(cmd, cwd=str(BRIDGE_DIR), env=bridge_env(session))


# ────────────────────────────────────────────────
# 入口
# ────────────────────────────────────────────────
def self_test() -> int:
    banner("自己確認（MT5なし）")
    missing = [n for n in (*INCLUDE_FILES, *EA_FILES) if not (BRIDGE_DIR / n).is_file()]
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


def install_ea_only() -> int:
    banner("システムの配置だけ")
    session = find_logged_in_terminal()
    if not session:
        log("MT5 にログインしていません")
        return 1
    copy_ea_files(session)
    write_bridge_env(session)
    return 0


def connect_all() -> int:
    """サイトのボタン1つで呼ばれる本体。画面は出さない。"""
    banner("接続開始")

    # 次からサイトのボタンで起動できるようにする（初回だけ効く）
    register_protocol()
    register_startup()

    session = find_logged_in_terminal()
    if session:
        log("すでにログイン中の MT5 を使います")
    else:
        exe = find_mt5_exe() or ensure_mt5()
        if exe is None:
            log("MT5 が用意できませんでした")
            return 1
        launch_mt5(exe)
        session = wait_for_login()
        if session is None:
            return 1

    try:
        copy_ea_files(session)
    except SystemExit as exc:
        log(str(exc))
        return 1
    write_bridge_env(session)

    url = relay_url()
    if relay_is_local(url) and not relay_is_up():
        start_relay()
        time.sleep(2)
    start_bridge(session)

    banner("接続完了")
    log(f"口座 {session['account']} / {session['server']}")
    return 0


def main() -> int:
    global CONSOLE
    args = [a for a in sys.argv[1:]]
    # trelab://connect のように渡ってくる引数は、いまは合図としてだけ使う
    args = [a for a in args if not a.lower().startswith(f"{PROTOCOL}:")]
    CONSOLE = "--console" in args or "--self-test" in args

    os.chdir(str(ROOT))
    log(f"起動 argv={sys.argv[1:]} frozen={FROZEN}")

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
    if "--uninstall" in args:
        return unregister()

    code = connect_all()
    if CONSOLE:
        print()
        input("  続けるには Enter を押してください...")
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
