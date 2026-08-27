#!/usr/bin/env python3
"""
お客様向け接続ツール。ダブルクリックで:

  1. MT5 が無ければ公式インストーラを起動（ログインはお客様が MT5 上で行う）
  2. EA / ゲートをターミナルへコピー
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


def download_mt5_installer() -> Path:
    dest = Path(os.environ.get("TEMP", ".")) / "trelab-mt5setup.exe"
    log(f"Downloading official MT5 installer...")
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


def wait_for_login(timeout_sec: int = 600) -> dict:
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise SystemExit("MetaTrader5 Python package missing. Run setup-windows.bat first.") from exc

    banner("Log in to MT5 yourself")
    log("Use the normal MT5 login window (broker / ID / password).")
    log("This tool never asks for that password.")
    log("Waiting for a logged-in account...")

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if mt5.initialize():
            info = mt5.account_info()
            term = mt5.terminal_info()
            if info is not None and getattr(info, "login", None):
                status = {
                    "account": info.login,
                    "server": getattr(info, "server", ""),
                    "data_path": getattr(term, "data_path", "") if term else "",
                    "build": getattr(term, "build", "") if term else "",
                }
                log(f"Logged in: {status['account']} / {status['server']}")
                return status
            mt5.shutdown()
        time.sleep(2)
    raise SystemExit("Timed out waiting for MT5 login.")


def copy_ea_files(data_path: str, mt5_exe: Path) -> None:
    if not data_path:
        raise SystemExit("MT5 data_path is empty.")
    mql5 = Path(data_path) / "MQL5"
    experts = mql5 / "Experts"
    include = mql5 / "Include"
    experts.mkdir(parents=True, exist_ok=True)
    include.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BRIDGE_DIR / "TradingGate.mqh", include / "TradingGate.mqh")
    shutil.copy2(BRIDGE_DIR / "TrelabEA.mq5", experts / "TrelabEA.mq5")
    shutil.copy2(BRIDGE_DIR / "TrelabGate.mq5", experts / "TrelabGate.mq5")
    log(f"Copied TradingGate.mqh -> {include}")
    log(f"Copied TrelabEA.mq5 -> {experts}")

    editor = mt5_exe.parent / "metaeditor64.exe"
    if editor.is_file():
        log("Compiling TrelabEA ...")
        subprocess.run(
            [str(editor), f"/compile:{experts / 'TrelabEA.mq5'}", "/log"],
            check=False,
        )


def start_relay() -> subprocess.Popen | None:
    if not (SERVER_DIR / "index.js").is_file():
        log("server/ missing — skip relay")
        return None
    node_modules = SERVER_DIR / "node_modules"
    if not node_modules.is_dir():
        log("npm install in server/ ...")
        subprocess.run(["npm", "install"], cwd=str(SERVER_DIR), check=False, shell=True)
    log("Starting relay on port 8080 ...")
    return subprocess.Popen(["npm", "start"], cwd=str(SERVER_DIR), shell=True)


def start_bridge() -> subprocess.Popen:
    venv_py = BRIDGE_DIR / "venv" / "Scripts" / "python.exe"
    py = str(venv_py) if venv_py.is_file() else sys.executable
    log("Starting bridge ...")
    return subprocess.Popen([py, str(BRIDGE_DIR / "bridge.py")])


def main() -> int:
    os.chdir(ROOT)
    banner("Trelab connection tool")
    log("You only log in inside MT5. This window never asks for a password.")

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
    log("Drag TrelabEA onto a chart in MT5 (Navigator -> Expert Advisors).")
    log("Then open the lab site and use Algo's control panel.")
    log("Leave this window and the black relay/bridge windows open.")
    print()
    input("  Press Enter to keep running in the background (or close to stop)...")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
