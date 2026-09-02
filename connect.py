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

  AITrader.vbs をダブルクリック       … 画面を出さずに全部やる
  python connect.py --console          … 経過を画面に出す（調査用）
  python connect.py --install-ea       … システムの配置だけ
  python connect.py --register         … サイト連携の登録だけ
  python connect.py --stop             … 裏で動いているブリッジを止める
  python connect.py --uninstall        … 停止して、登録も消す
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
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

PRODUCT_NAME = "AIトレーダー"
APP_NAME = "AIトレーダー"
PROTOCOL = "aitrader"
LEGACY_PROTOCOL = "trelab"
LEGACY_APP_NAMES = ("TrelabConnect",)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ROOM_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")

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


def unregister() -> int:
    if os.name != "nt":
        return 0
    try:
        import winreg
    except ImportError:
        return 0
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            for name in (APP_NAME, *LEGACY_APP_NAMES):
                try:
                    winreg.DeleteValue(key, name)
                except OSError:
                    pass
        log("スタートアップの登録を消しました")
    except OSError:
        pass
    _delete_protocol(PROTOCOL)
    if LEGACY_PROTOCOL != PROTOCOL:
        _delete_protocol(LEGACY_PROTOCOL)
    log(f"{PROTOCOL}:// の登録を消しました")
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
    """サイトから渡された会員IDを、このPCのブリッジ名として覚える。"""
    if not ROOM_RE.match(room):
        return
    write_env_key("BRIDGE_ID", room)
    os.environ["BRIDGE_ID"] = room
    log(f"このPCの部屋: {room}")


def is_protocol_url(raw: str) -> bool:
    lower = raw.lower()
    return lower.startswith(f"{PROTOCOL}:") or lower.startswith(f"{LEGACY_PROTOCOL}:")


def site_room_from_args(argv: list[str]) -> str:
    """aitrader://connect?room=<会員ID> から部屋を読む。"""
    for raw in argv:
        if not is_protocol_url(raw):
            continue
        try:
            parsed = urllib.parse.urlparse(raw.replace("\\", "/"))
            query = urllib.parse.parse_qs(parsed.query)
            room = (query.get("room") or [""])[0].strip()
            if ROOM_RE.match(room):
                return room
        except Exception:  # noqa: BLE001
            continue
    return ""


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


def relay_http_origin(ws_url: str) -> str | None:
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://") :].split("/")[0]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://") :].split("/")[0]
    return None


def relay_health() -> dict | None:
    url = relay_url()
    origin = "http://127.0.0.1:8080" if relay_is_local(url) else relay_http_origin(url)
    if not origin:
        return None
    try:
        with urllib.request.urlopen(f"{origin}/health", timeout=4) as res:
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
    data = relay_health()
    if data is None:
        return None
    rooms = data.get("rooms")
    if not isinstance(rooms, list):
        return None
    return bridge_id in rooms


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


def stop_all_bridges() -> int:
    """動いているブリッジを終了する（古い名前のものも含めて）。

    画面を出さずに常駐する作りなので、止める手段をここに用意しておく。
    """
    stopped = 0
    for path in all_lock_paths():
        if not path.is_file():
            continue
        try:
            first = path.read_text(encoding="ascii", errors="replace").splitlines()[0].strip()
            pid = int(first) if first.isdigit() else None
        except (OSError, IndexError, ValueError):
            pid = None
        if pid is None:
            continue
        image = process_image(pid).lower()
        if not image:
            continue
        if "python" not in image and image != Path(sys.executable).name.lower():
            log(f"PID {pid} は {image} なので触りません")
            continue
        log(f"ブリッジ（PID {pid} / {image}）を終了します")
        if os.name == "nt":
            run_hidden(["taskkill", "/PID", str(pid), "/F", "/T"], timeout=30)
        else:
            try:
                os.kill(pid, 15)
            except OSError as exc:
                log(f"終了できませんでした: {exc}")
        for _ in range(20):
            if not process_image(pid):
                stopped += 1
                log("終了しました")
                break
            time.sleep(0.5)
        else:
            log(f"終了できませんでした（PID {pid}）。タスクマネージャーで pythonw.exe を終了してください")
    if stopped == 0:
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
    """ロックは残っているが中継に乗っていないプロセスを終了する。"""
    pid = lock_pid()
    if pid is None:
        return
    log(f"中継に乗っていないブリッジ (pid={pid}) を終了します")
    if os.name == "nt":
        run_hidden(["taskkill", "/PID", str(pid), "/F"])
    else:
        try:
            os.kill(pid, 15)
        except OSError as exc:
            log(f"終了できませんでした: {exc}")
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
    our_id = env_value("BRIDGE_ID") or "vps-01"
    if bridge_already_running():
        local_missing = (
            relay_is_local(relay_url())
            and relay_is_up()
            and relay_has_bridge(our_id) is False
        )
        if local_missing or bridge_is_outdated():
            stop_stale_bridge()
        else:
            log("ブリッジはすでに動いています")
            return
        if bridge_already_running():
            log("古いブリッジを終了できませんでした")
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


def connect_all(room: str = "") -> int:
    """サイトのボタン1つで呼ばれる本体。画面は出さない。"""
    banner("接続開始")

    if room:
        adopt_room(room)
        if bridge_already_running() and relay_has_bridge(room) is not True:
            stop_stale_bridge()

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
    raw_args = [a for a in sys.argv[1:]]
    room = site_room_from_args(raw_args)
    args = [a for a in raw_args if not is_protocol_url(a)]
    CONSOLE = "--console" in args or "--self-test" in args

    os.chdir(str(ROOT))
    log(f"起動 argv={raw_args} frozen={FROZEN} room={room or '-'}")

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
    if "--stop" in args:
        banner("接続をやめる")
        stop_all_bridges()
        return 0
    if "--uninstall" in args:
        banner("登録をすべて消す")
        stop_all_bridges()
        return unregister()

    code = connect_all(room)
    if CONSOLE:
        print()
        input("  続けるには Enter を押してください...")
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
