#!/usr/bin/env python3
"""
お客様向け接続ツール。ダブルクリックで:

  1. 起動中の MT5 があればそれを使う（無ければ起動／未導入なら公式インストーラ）
  2. ログイン済みターミナルへ EA をコピーしてコンパイル
  3. 中継サーバーとブリッジを起動

サイトに口座パスワードは一切渡さない。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRIDGE_DIR = ROOT / "bridge"
SERVER_DIR = ROOT / "server"
MT5_SETUP_URL = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"

EA_FILES = ("SiteTestEA.mq5", "TrelabEA.mq5", "TrelabGate.mq5")
INCLUDE_FILES = ("TradingGate.mqh",)

SEARCH_EXES = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "MetaTrader 5" / "terminal64.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "MetaTrader 5" / "terminal.exe",
]


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def banner(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def find_mt5_exe() -> Path | None:
    for path in SEARCH_EXES:
        if path.is_file():
            return path
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    if pf.is_dir():
        for hit in pf.glob("**/terminal64.exe"):
            return hit
    return None


def terminal_dir_from_data_path(data_path: str) -> Path | None:
    """data_path の origin.txt から、実際に動いているターミナルのフォルダを取る。"""
    origin = Path(data_path) / "origin.txt"
    if not origin.is_file():
        return None
    try:
        text = origin.read_text(encoding="utf-16", errors="ignore").strip()
    except OSError:
        return None
    if not text:
        try:
            text = origin.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return None
    line = text.splitlines()[0].strip() if text else ""
    folder = Path(line)
    if (folder / "terminal64.exe").is_file() or (folder / "metaeditor64.exe").is_file():
        return folder
    return folder if folder.is_dir() else None


def find_metaeditor(mt5_exe: Path | None, data_path: str) -> Path | None:
    candidates: list[Path] = []
    origin_dir = terminal_dir_from_data_path(data_path)
    if origin_dir:
        candidates.append(origin_dir / "metaeditor64.exe")
    if mt5_exe:
        candidates.append(mt5_exe.parent / "metaeditor64.exe")
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    if pf.is_dir():
        candidates.extend(pf.glob("**/metaeditor64.exe"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def download_mt5_installer() -> Path:
    dest = Path(os.environ.get("TEMP", ".")) / "trelab-mt5setup.exe"
    log("Downloading official MT5 installer...")
    log(MT5_SETUP_URL)
    urllib.request.urlretrieve(MT5_SETUP_URL, dest)
    return dest


def ensure_mt5() -> Path:
    found = find_mt5_exe()
    if found:
        log(f"Found MT5: {found}")
        return found
    banner("MT5 is not installed")
    log("The system will open the official installer.")
    log("Click Next in that window. Do NOT type your password here.")
    log("After install, log in to your broker inside MT5 as usual.")
    input("  Press Enter to download and start the installer...")
    setup = download_mt5_installer()
    subprocess.Popen([str(setup)], shell=False)
    log("Waiting for terminal64.exe ...")
    for _ in range(120):
        found = find_mt5_exe()
        if found:
            log(f"Found MT5: {found}")
            return found
        time.sleep(2)
    raise SystemExit("MT5 was not found after the installer. Finish install, then run this tool again.")


def launch_mt5(exe: Path) -> None:
    log(f"Starting {exe.name} ...")
    subprocess.Popen([str(exe)], cwd=str(exe.parent))


def read_login_status() -> dict | None:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None
    if not mt5.initialize():
        return None
    info = mt5.account_info()
    term = mt5.terminal_info()
    if info is None or not getattr(info, "login", None):
        mt5.shutdown()
        return None
    return {
        "account": info.login,
        "server": getattr(info, "server", ""),
        "data_path": getattr(term, "data_path", "") if term else "",
        "build": getattr(term, "build", "") if term else "",
    }


def wait_for_login(timeout_sec: int = 600) -> dict:
    try:
        import MetaTrader5 as mt5  # noqa: F401
    except ImportError as exc:
        raise SystemExit("MetaTrader5 Python package missing. Run setup-windows.bat first.") from exc

    existing = read_login_status()
    if existing:
        log(f"Already logged in: {existing['account']} / {existing['server']}")
        return existing

    banner("Log in to MT5 yourself")
    log("Use the normal MT5 login window (broker / ID / password).")
    log("This tool never asks for that password.")
    log("Waiting for a logged-in account...")

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        status = read_login_status()
        if status:
            log(f"Logged in: {status['account']} / {status['server']}")
            return status
        time.sleep(2)
    raise SystemExit("Timed out waiting for MT5 login.")


def compile_mq5(editor: Path, mq5: Path) -> bool:
    log(f"Compiling {mq5.name} ...")
    # パスに空白があっても通るように /compile:"..." 形式
    subprocess.run([str(editor), f'/compile:{mq5}', "/log"], check=False)
    ex5 = mq5.with_suffix(".ex5")
    for _ in range(20):
        if ex5.is_file():
            log(f"OK  {ex5.name}")
            return True
        time.sleep(0.25)
    log(f"WARN  {ex5.name} was not created. Compile in MetaEditor if Navigator is empty.")
    return False


def copy_ea_files(data_path: str, mt5_exe: Path | None) -> Path:
    if not data_path:
        raise SystemExit("MT5 data_path is empty.")
    mql5 = Path(data_path) / "MQL5"
    experts = mql5 / "Experts"
    include = mql5 / "Include"
    experts.mkdir(parents=True, exist_ok=True)
    include.mkdir(parents=True, exist_ok=True)

    banner("Installing EA files")
    log(f"MT5 data folder: {data_path}")

    for name in INCLUDE_FILES:
        src = BRIDGE_DIR / name
        dst = include / name
        if not src.is_file():
            raise SystemExit(f"Missing {src}")
        shutil.copy2(src, dst)
        log(f"OK  Include\\{name}")

    for name in EA_FILES:
        src = BRIDGE_DIR / name
        dst = experts / name
        if not src.is_file():
            raise SystemExit(f"Missing {src}")
        shutil.copy2(src, dst)
        log(f"OK  Experts\\{name}")

    editor = find_metaeditor(mt5_exe, data_path)
    if editor:
        log(f"MetaEditor: {editor}")
        compile_mq5(editor, experts / "SiteTestEA.mq5")
        compile_mq5(editor, experts / "TrelabEA.mq5")
    else:
        log("WARN  metaeditor64.exe not found. Open MetaEditor and compile SiteTestEA.mq5")

    site_ex5 = experts / "SiteTestEA.ex5"
    if site_ex5.is_file():
        log("Navigator -> Expert Advisors -> SiteTestEA  (compiled)")
    else:
        log("Navigator may show SiteTestEA.mq5 only until you compile it.")
    return experts


def start_relay() -> subprocess.Popen | None:
    if not (SERVER_DIR / "index.js").is_file():
        log("server/ missing — skip relay")
        return None
    if not (SERVER_DIR / "node_modules").is_dir():
        log("npm install in server/ ...")
        subprocess.run(["npm", "install"], cwd=str(SERVER_DIR), check=False, shell=True)
    log("Starting relay on port 8080 ...")
    return subprocess.Popen(["npm", "start"], cwd=str(SERVER_DIR), shell=True)


def start_bridge() -> subprocess.Popen:
    venv_py = BRIDGE_DIR / "venv" / "Scripts" / "python.exe"
    py = str(venv_py) if venv_py.is_file() else sys.executable
    log("Starting bridge ...")
    return subprocess.Popen([py, str(BRIDGE_DIR / "bridge.py")])


def self_test() -> int:
    banner("Self-test (no MT5)")
    missing = [n for n in (*INCLUDE_FILES, *EA_FILES) if not (BRIDGE_DIR / n).is_file()]
    if missing:
        log(f"FAIL missing files: {missing}")
        return 1
    fake = ROOT / ".tmp-mt5-data" / "MQL5"
    try:
        experts = copy_ea_files(str(ROOT / ".tmp-mt5-data"), None)
        for name in EA_FILES:
            if not (experts / name).is_file():
                log(f"FAIL not copied: {name}")
                return 1
        log("PASS  source EA files copy into the MT5 Experts folder")
        return 0
    finally:
        shutil.rmtree(ROOT / ".tmp-mt5-data", ignore_errors=True)


def main() -> int:
    os.chdir(ROOT)
    if "--self-test" in sys.argv:
        return self_test()

    banner("Connection tool")
    log("You only log in inside MT5. This window never asks for a password.")

    status = read_login_status()
    exe = find_mt5_exe()
    if status:
        log("Using the MT5 that is already logged in. Will not start a second terminal.")
        if not exe:
            origin = terminal_dir_from_data_path(str(status["data_path"]))
            if origin and (origin / "terminal64.exe").is_file():
                exe = origin / "terminal64.exe"
    else:
        exe = ensure_mt5()
        launch_mt5(exe)
        status = wait_for_login()

    copy_ea_files(str(status["data_path"]), exe)

    banner("Connecting to the lab")
    start_relay()
    time.sleep(2)
    start_bridge()

    banner("Done")
    log(f"Account {status['account']} / {status['server']}")
    log("In MT5: Navigator (Ctrl+N) -> Expert Advisors -> SiteTestEA")
    log("Drag SiteTestEA onto a chart, enable AutoTrading.")
    log("Leave this window open.")
    print()
    input("  Press Enter to keep running (or close to stop)...")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
