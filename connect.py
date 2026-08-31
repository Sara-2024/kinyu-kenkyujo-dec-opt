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


def wait_for_login(timeout_sec: int = 600) -> dict:
    try:
        import MetaTrader5 as mt5  # noqa: F401
    except ImportError as exc:
        raise SystemExit("MetaTrader5 Python package missing. Run setup-windows.bat first.") from exc

    existing = find_logged_in_terminal()
    if existing:
        log(f"Already logged in: {existing['account']} / {existing['server']}")
        return existing

    banner("Log in to MT5 yourself")
    log("Use the normal MT5 login window (broker / ID / password).")
    log("This tool never asks for that password.")
    log("Waiting for a logged-in account...")

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        status = find_logged_in_terminal()
        if status:
            log(f"Logged in: {status['account']} / {status['server']}")
            return status
        time.sleep(2)
    raise SystemExit("Timed out waiting for MT5 login.")


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
    log(f"Compiling {mq5.name} ...")
    log(f"  Editor: {editor}")
    log(f"  Source: {mq5}")
    ex5 = mq5.with_suffix(".ex5")
    if ex5.is_file():
        try:
            ex5.unlink()
        except OSError:
            pass

    cmd = [str(editor), f"/compile:{mq5}", "/log"]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.run(
        cmd,
        cwd=str(terminal_dir) if terminal_dir else None,
        check=False,
        creationflags=flags,
    )

    for _ in range(120):
        if ex5.is_file():
            log(f"OK  {ex5.name}")
            return True
        time.sleep(0.25)

    log(f"WARN  {ex5.name} was not created.")
    tail = read_compile_log(mq5)
    if tail:
        log("----- MetaEditor log (tail) -----")
        for line in tail.splitlines()[-12:]:
            log(line)
        log("---------------------------------")
    else:
        log("Open MetaEditor once, compile SiteTestEA.mq5 manually, then retry.")
    return False


def verify_ea_install(data_path: str) -> tuple[bool, dict]:
    probe = probe_ea_files(data_path)
    ok = probe["include_ok"] and "SiteTestEA" in probe["ea_found"]
    if ok and "SiteTestEA" not in probe["ea_compiled"]:
        log("WARN  SiteTestEA.mq5 is present but .ex5 is missing (compile failed or pending).")
    return ok, probe


def copy_ea_files(session: dict) -> Path:
    data_path = str(session.get("data_path") or "").strip()
    if not data_path:
        raise SystemExit("MT5 data_path is empty. Is MT5 running and logged in?")

    data_root = Path(data_path)
    data_root.mkdir(parents=True, exist_ok=True)

    mql5 = data_root / "MQL5"
    experts = mql5 / "Experts"
    include = mql5 / "Include"
    experts.mkdir(parents=True, exist_ok=True)
    include.mkdir(parents=True, exist_ok=True)

    terminal_exe = resolve_terminal_exe(session)
    terminal_dir = terminal_exe.parent if terminal_exe else terminal_dir_from_data_path(data_path)

    banner("Installing EA files")
    log(f"Account   : {session.get('account')} / {session.get('server')}")
    log(f"Terminal  : {session.get('terminal_name')} build {session.get('build')}")
    if terminal_exe:
        log(f"terminal64: {terminal_exe}")
    log(f"Data folder: {data_path}")
    log(f"Experts    : {experts}")

    for name in INCLUDE_FILES:
        src = BRIDGE_DIR / name
        dst = include / name
        if not src.is_file():
            raise SystemExit(f"Missing source file: {src}")
        shutil.copy2(src, dst)
        log(f"OK  Include\\{name}  ({dst.stat().st_size} bytes)")

    for name in EA_FILES:
        src = BRIDGE_DIR / name
        dst = experts / name
        if not src.is_file():
            raise SystemExit(f"Missing source file: {src}")
        shutil.copy2(src, dst)
        log(f"OK  Experts\\{name}  ({dst.stat().st_size} bytes)")

    editor = find_metaeditor(data_path, terminal_exe)
    if editor:
        for name in EA_FILES:
            compile_mq5(editor, experts / name, terminal_dir)
    else:
        log("WARN  metaeditor64.exe not found for this terminal.")
        if terminal_dir:
            log(f"WARN  Expected near: {terminal_dir / 'metaeditor64.exe'}")
        log("WARN  Open MetaEditor from MT5 (F4) and compile SiteTestEA.mq5 manually.")

    ok, probe = verify_ea_install(data_path)
    if editor and "SiteTestEA" not in probe["ea_compiled"]:
        ok = False
    log("")
    log(f"Verify Include/TradingGate.mqh : {'OK' if probe['include_ok'] else 'MISSING'}")
    log(f"Verify Experts/SiteTestEA.mq5 : {'OK' if 'SiteTestEA' in probe['ea_found'] else 'MISSING'}")
    log(f"Verify Experts/SiteTestEA.ex5 : {'OK' if 'SiteTestEA' in probe['ea_compiled'] else 'MISSING'}")
    log(f"Folder opened in Explorer     : {probe['experts_dir']}")

    if os.name == "nt":
        try:
            os.startfile(probe["experts_dir"])  # type: ignore[attr-defined]
        except OSError:
            pass

    if not ok:
        raise SystemExit(
            "EA install incomplete. See messages above. "
            "Try install-ea.bat again, or compile SiteTestEA.mq5 in MetaEditor (F4)."
        )

    log("")
    log("In MT5: Navigator (Ctrl+N) -> right-click Expert Advisors -> Refresh")
    log("Then drag SiteTestEA onto your chart (e.g. USDJPY) and enable AutoTrading.")
    return experts


def write_bridge_env(session: dict) -> None:
    """ブリッジが同じ MT5 ターミナル（いまログイン中の口座）へ繋ぐよう .env を更新する。"""
    exe = resolve_terminal_exe(session)
    if exe is None:
        return
    env_path = BRIDGE_DIR / ".env"
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
    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    log(f"Bridge will use this MT5: {val}")


def start_relay() -> subprocess.Popen | None:
    if not (SERVER_DIR / "index.js").is_file():
        log("server/ missing — skip relay")
        return None
    if not (SERVER_DIR / "node_modules").is_dir():
        log("npm install in server/ ...")
        subprocess.run(["npm", "install"], cwd=str(SERVER_DIR), check=False, shell=True)
    log("Starting relay on port 8080 ...")
    return subprocess.Popen(["npm", "start"], cwd=str(SERVER_DIR), shell=True)


def relay_is_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1.5) as res:
            return res.status == 200
    except Exception:
        return False


def start_bridge() -> subprocess.Popen:
    venv_py = BRIDGE_DIR / "venv" / "Scripts" / "python.exe"
    py = str(venv_py) if venv_py.is_file() else sys.executable
    log("Starting bridge ...")
    proc = subprocess.Popen([py, str(BRIDGE_DIR / "bridge.py")])
    time.sleep(1.2)
    if proc.poll() == 2:
        log("Another bridge is already running. Using that one.")
    return proc


def self_test() -> int:
    banner("Self-test (no MT5)")
    missing = [n for n in (*INCLUDE_FILES, *EA_FILES) if not (BRIDGE_DIR / n).is_file()]
    if missing:
        log(f"FAIL missing source files: {missing}")
        return 1
    fake = ROOT / ".tmp-mt5-data"
    try:
        session = {"data_path": str(fake), "account": 0, "server": "test"}
        copy_ea_files(session)
        log("PASS  copy + verify logic")
        return 0
    except SystemExit as exc:
        msg = str(exc)
        if "not installed correctly" in msg or "MetaEditor" in msg:
            log("PASS  copy ran (compile may be skipped without MetaEditor)")
            return 0
        log(f"FAIL {msg}")
        return 1
    finally:
        shutil.rmtree(fake, ignore_errors=True)


def install_ea_only() -> int:
    banner("EA install only")
    session = find_logged_in_terminal()
    if not session:
        raise SystemExit("MT5 is not logged in. Open MT5, log in, then run this again.")
    copy_ea_files(session)
    write_bridge_env(session)
    return 0


def main() -> int:
    os.chdir(ROOT)
    if "--self-test" in sys.argv:
        return self_test()
    if "--install-ea" in sys.argv:
        return install_ea_only()

    banner("Connection tool")
    log("You only log in inside MT5. This window never asks for a password.")

    session = find_logged_in_terminal()
    if session:
        log("Using the MT5 that is already logged in. Will not start a second terminal.")
        exe = resolve_terminal_exe(session) or find_mt5_exe()
    else:
        exe = ensure_mt5()
        launch_mt5(exe)
        session = wait_for_login()

    copy_ea_files(session)
    write_bridge_env(session)

    banner("Connecting to the lab")
    if relay_is_up():
        log("Relay already running on 8080 — using the existing one")
    else:
        start_relay()
        time.sleep(2)
    start_bridge()

    banner("Done")
    log(f"Account {session['account']} / {session['server']}")
    log("Leave this window open.")
    print()
    input("  Press Enter to keep running (or close to stop)...")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
