#!/usr/bin/env python3
"""MT5 Automatic の Mac 版の入口。

Windows 版の本体（connect.py）をそのまま読み込み、OS に依存する関数だけ
ここで差し替えて動かす。初回の設定（EA を置く）・サイトからの合図（token）・
ブリッジの起動と見張りは Windows と同じ流れ。

Windows と違うところ:
  ・MT5 は Wine の上で動いているので、データは
      ~/Library/Application Support/<アプリ>/drive_c/users/<user>/AppData/Roaming/MetaQuotes/Terminal/<ID>/
    にある（bridge/mt5_detect_mac.py が探す）。見つけたら APPDATA をそこへ向け、
    Windows 向けの部品（mt5_terminal / ea_manager）をそのまま使う
  ・MetaQuotes の Python 部品（MetaTrader5）が無いので、EA が書くファイルを読む
    bridge/mt5_files.py を MetaTrader5 として差し込む（docs/mac-ea-files.md）
  ・aitrader:// は .app の Info.plist が受け、tools/mac/launcher.applescript が
    この実行ファイルを `--silent --from-site <url>` で起こす（登録は要らない）
  ・自動起動は ~/Library/LaunchAgents の plist
  ・設定と記録は ~/Library/Application Support/MT5Automatic/AITrader/（LOCALAPPDATA に見せる）

exe と同じく、画面は installer_ui（tkinter）。黒い画面（Terminal）は出さない。
"""
from __future__ import annotations

import os
import plistlib
import signal
import subprocess
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
HERE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
ASSETS = Path(getattr(sys, "_MEIPASS", HERE))

# 設定と記録の置き場（Windows の %LOCALAPPDATA% に相当）
HOME_DIR = Path.home() / "Library" / "Application Support" / "MT5Automatic"
HOME_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("LOCALAPPDATA", str(HOME_DIR))
# まだ MT5 を選んでいないときの APPDATA（EA は置けないが、部品が落ちないように）
os.environ.setdefault("APPDATA", str(HOME_DIR / "appdata"))

sys.path.insert(0, str(ASSETS))
sys.path.insert(0, str(ASSETS / "bridge"))

# Mac の Python（python.org 版も PyInstaller で固めたものも）は HTTPS の証明書を持たず、
# 中継（wss://）にもサイト（https://）にも「証明書を確認できない」でつながらない。
# 同梱した certifi の証明書を使わせる。環境変数なので、裏で起こすブリッジにも引き継がれる
try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:  # pragma: no cover - 部品を入れ忘れたとき
    pass

import mt5_detect_mac  # noqa: E402
import mt5_files  # noqa: E402

# ブリッジ・mt5_terminal・gold_symbol が MetaTrader5 を import したら、これを渡す
sys.modules["MetaTrader5"] = mt5_files

import connect  # noqa: E402  Windows 版の本体
import installer_ui  # noqa: E402

AGENT_ID = "jp.trelab.mt5automatic"
PRODUCT_NAME = connect.PRODUCT_NAME
log = connect.log


# ────────────────────────────────────────────────
# MT5 を探す・つなぐ
# ────────────────────────────────────────────────
def list_terminals() -> list[mt5_detect_mac.MacTerminal]:
    terminals = mt5_detect_mac.find_terminals()
    if len(terminals) == 1:
        # 1台なら迷わない。部品がすぐ正しい場所を見られるように向けておく
        mt5_detect_mac.point_appdata_at(terminals[0])
    return terminals


def describe(terminals: list) -> str:
    if not terminals:
        return "MT5 なし"
    return " / ".join(f"{t.label}[{t.terminal_id[:8]}]" for t in terminals)


def find_logged_in_terminal(prefer_data_path: str | Path | None = None) -> dict | None:
    """EA が口座の控えを書いている MT5 を「ログイン済み」とみなす。

    Windows 版は MT5 本体に聞くが、Mac では EA の控え（trelab_account.ini）しか無い。
    prefer（初回に選んだ MT5）があれば、それ以外には繋がない。
    """
    for t in mt5_detect_mac.find_terminals():
        if prefer_data_path and not connect._same_path(t.data_path, prefer_data_path):
            continue
        mt5_detect_mac.point_appdata_at(t)
        if not mt5_files.initialize():
            continue
        acc = mt5_files.account_info()
        if acc is None:
            continue
        return {
            "data_path": str(t.data_path),
            "account": acc.login,
            "server": acc.server,
            "exe": None,
            "platform": "mac",
        }
    return None


def account_of(terminal) -> str:
    """選んだ MT5 の口座番号。ついでに、部品がその MT5 を見るように向ける。"""
    if isinstance(terminal, mt5_detect_mac.MacTerminal):
        mt5_detect_mac.point_appdata_at(terminal)
        if terminal.account:
            return terminal.account
    return _orig_account_of(terminal)


# ────────────────────────────────────────────────
# MT5 本体（Wine のアプリ）を見る・開き直す
# ────────────────────────────────────────────────
def mt5_pids(_exe=None) -> list[int]:
    """Wine の中で動いている MT5（terminal64.exe）のプロセス。"""
    try:
        out = subprocess.run(["pgrep", "-f", "terminal64.exe"], capture_output=True, text=True, check=False).stdout
    except OSError:
        return []
    return [int(p) for p in out.split() if p.isdigit()]


def restart_mt5(terminal, tick=None) -> bool:
    """MT5 を閉じて開き直す（ナビゲーターに新しい EA を出すため）。"""
    app_id = getattr(terminal, "app_id", "") or "net.metaquotes.wine.metatrader5"
    try:
        subprocess.run(["osascript", "-e", f'tell application id "{app_id}" to quit'], check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    for _ in range(60):
        if tick:
            tick()
        if not mt5_pids():
            break
        import time

        time.sleep(0.5)
    try:
        subprocess.Popen(["open", "-b", app_id])
        log(f"MT5 を開き直しました: {app_id}")
        return True
    except OSError as exc:
        log(f"MT5 を開き直せません: {exc}")
        return False


def find_mt5_exe() -> Path | None:
    """/Applications にある MT5 のアプリ。無ければ None。"""
    apps = Path("/Applications")
    try:
        for p in sorted(apps.glob("*.app")):
            name = p.name.lower()
            if "metatrader 5" in name or "metatrader5" in name or "mt5" in name:
                return p
    except OSError:
        pass
    return None


def launch_mt5(exe: Path) -> None:
    try:
        subprocess.Popen(["open", str(exe)])
        log(f"MT5 を起動します: {exe.name}")
    except OSError as exc:
        log(f"MT5 を起動できません: {exc}")


def ensure_mt5() -> Path | None:
    # Mac では自動でインストールしない（業者ごとに配布が違う）
    return find_mt5_exe()


# ────────────────────────────────────────────────
# 自動起動（LaunchAgent）と URL の登録
# ────────────────────────────────────────────────
def agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{AGENT_ID}.plist"


def _program() -> list[str]:
    if FROZEN:
        return [sys.executable, "--startup"]
    return [sys.executable, str(HERE / "connect_mac.py"), "--startup"]


def register_protocol() -> bool:
    # aitrader:// は .app の Info.plist（CFBundleURLTypes）が受ける。ここでやることは無い
    return True


def register_startup() -> bool:
    path = agent_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        plist = {
            "Label": AGENT_ID,
            "ProgramArguments": _program(),
            "RunAtLoad": True,
            "StandardOutPath": str(connect.CONFIG_DIR / "launchagent.log"),
            "StandardErrorPath": str(connect.CONFIG_DIR / "launchagent.log"),
        }
        with path.open("wb") as fh:
            plistlib.dump(plist, fh)
        subprocess.run(["launchctl", "load", "-w", str(path)], check=False, capture_output=True, timeout=10)
        log("ログイン時にも自動でつながるようにしました")
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"自動起動を登録できません: {exc}")
        return False


def startup_command() -> str:
    path = agent_path()
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as fh:
            return " ".join(plistlib.load(fh).get("ProgramArguments", []))
    except Exception:  # noqa: BLE001
        return ""


def unregister_startup(why: str = "") -> bool:
    path = agent_path()
    if not path.exists():
        return True
    try:
        subprocess.run(["launchctl", "unload", "-w", str(path)], check=False, capture_output=True, timeout=10)
        path.unlink()
        log(f"自動起動の登録を消しました{'（' + why + '）' if why else ''}")
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"自動起動の登録を消せません: {exc}")
        return False


def unregister() -> int:
    unregister_startup("登録をすべて消す")
    return 0


# ────────────────────────────────────────────────
# プロセス（ブリッジの二重起動を止める）
# ────────────────────────────────────────────────
def list_bridge_processes() -> list[tuple[int, str]]:
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False).stdout
    except OSError:
        return []
    found: list[tuple[int, str]] = []
    for line in out.splitlines():
        pid_s, _, cmd = line.strip().partition(" ")
        if not pid_s.isdigit() or int(pid_s) == os.getpid():
            continue
        if "--run-bridge" in cmd or "bridge.py" in cmd:
            found.append((int(pid_s), cmd))
    return found


def process_image(pid: int) -> str:
    try:
        return subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return ""


def kill_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


# ────────────────────────────────────────────────
# ブリッジの起動（自分自身を --run-bridge で起こす）
# ────────────────────────────────────────────────
def start_bridge(session: dict | None = None) -> None:
    import connect_state

    if not connect_state.is_connected():
        log("まだサイトと連携していないので、通信は始めません（EA の設置だけ）")
        return
    our_id = connect.env_value("BRIDGE_ID") or "vps-01"
    if connect.bridge_already_running():
        if connect.bridge_is_outdated() or connect.bridge_in_other_room(our_id):
            connect.stop_stale_bridge()
        else:
            log("ブリッジはすでに動いています")
            return
        if connect.bridge_already_running():
            log("古いブリッジを終了できませんでした。アクティビティモニタで MT5Automatic を終了してから、もう一度お試しください")
            return
    cmd = [sys.executable, "--run-bridge"] if FROZEN else [sys.executable, str(HERE / "connect_mac.py"), "--run-bridge"]
    log(f"ブリッジを裏側で起動します（接続先 {connect.relay_url()}）")
    env = connect.bridge_env(session)
    env["PLATFORM"] = "mac"
    connect.spawn_hidden(cmd, cwd=str(connect.CONFIG_DIR), env=env)


# ────────────────────────────────────────────────
# 画面の小物（Windows の MessageBox の代わり）
# ────────────────────────────────────────────────
def message_box(text: str, title: str = PRODUCT_NAME) -> bool:
    body = str(text).replace("\\", "\\\\").replace('"', '\\"')
    head = str(title).replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(
            ["osascript", "-e", f'display dialog "{body}" with title "{head}" buttons {{"OK"}} default button 1'],
            check=False,
            capture_output=True,
            timeout=120,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


# ────────────────────────────────────────────────
# 差し替え
# ────────────────────────────────────────────────
_orig_account_of = connect.account_of


def _patch() -> None:
    connect.mt5_detect.list_terminals = list_terminals
    connect.mt5_detect.describe = describe
    connect.find_logged_in_terminal = find_logged_in_terminal
    connect.account_of = account_of
    connect.mt5_pids = mt5_pids
    connect.restart_mt5 = restart_mt5
    connect.find_mt5_exe = find_mt5_exe
    connect.launch_mt5 = launch_mt5
    connect.ensure_mt5 = ensure_mt5
    connect.register_protocol = register_protocol
    # --status の「aitrader:// の登録」は Windows のレジストリを見る。Mac では .app が受ける
    connect._protocol_command = lambda: "MT5 Automatic.app（Info.plist の CFBundleURLTypes）"
    connect.register_startup = register_startup
    connect.startup_command = startup_command
    connect.unregister_startup = unregister_startup
    connect.unregister = unregister
    connect.list_bridge_processes = list_bridge_processes
    connect.process_image = process_image
    connect.kill_process = kill_process
    connect.start_bridge = start_bridge
    # Mac では「別名の Yumekku」を片づけない。手で置いた検証用の EA を「前の版」として
    # 消してしまった（実機で起きた）。Mac は台数が少なく、並んでいても案内文の名前
    #（YumekkuEA_mac）で見分けられるので、消さずに残す
    import ea_manager

    def _keep_other_versions(experts, keep, *, log=lambda _m: None):
        log("Mac では、ほかの名前の EA は片づけません")
        return []

    ea_manager.cleanup_other_versions = _keep_other_versions

    # 同梱している EA は Mac 用（YumekkuEA_mac）。connect.py は読み込み時に Windows 用の名前
    #（EA_NAMES[0]）で EA_NAME / EA_FILES を決めるので、同梱の .ex5 の名前に差し替える。
    # 差し替えないと、自己確認が「YumekkuEA_win.ex5 が無い」で止まり、案内文も Windows の名前になる。
    # .app では bridge/ に Mac 用だけが入っている。手元（frozen でない）では bridge/mac/ を見る
    import mt5_terminal

    ea_dir = connect.BRIDGE_DIR if FROZEN else connect.BRIDGE_DIR / "mac"
    mac_ea = ea_manager.find_source_file(ea_dir) if ea_dir.is_dir() else None
    if mac_ea is not None:
        connect.EA_NAME = mac_ea.stem
        connect.EA_FILES = (mac_ea.name,)
        connect.EA_ASSETS_DIR = ea_dir
        for mod_name in ("mt5_terminal", "bridge"):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, "EA_NAMES"):
                mod.EA_NAMES = (mac_ea.stem,)
        if not FROZEN:
            # 手元では .ex5 と控えが bridge/mac/、TradingGate.mqh は bridge/ にある
            _orig_load_source = ea_manager.load_source

            def _load_mac_source(assets_dir):
                src = _orig_load_source(ea_dir)
                if src is None:
                    return None
                src.includes = tuple(
                    Path(assets_dir) / n for n in ea_manager.INCLUDE_FILES if (Path(assets_dir) / n).is_file()
                )
                if src.broken.startswith("同梱物が足りない") and len(src.includes) == len(ea_manager.INCLUDE_FILES):
                    src.broken = ""
                return src

            ea_manager.load_source = _load_mac_source
    # 気配値への表示は MT5 本体に聞かないとできない。Mac では EA 側に任せる
    connect.gold_symbol.show_in_market_watch = lambda *_a, **_k: ""
    installer_ui.message_box = message_box


_patch()


def main() -> int:
    return connect.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
