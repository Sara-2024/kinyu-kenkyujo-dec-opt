#!/usr/bin/env python3
"""
トレラボ ⇔ MT5 ブリッジ (bridge.py)

Webアプリ（トレラボ）からの指令を WebSocket で常時待ち受け、
MT5 のターミナル・グローバル変数を書き換えて EA の売買可否を制御する。

設計の要点:
  * ポーリングしない。asyncio の await で待つのでアイドル時の CPU はほぼ 0%。
  * MetaTrader5 パッケージは同期(ブロッキング)API のため、専用の単一スレッドへ
    逃がしてイベントループを止めない。MT5 の呼び出しが常に同じスレッドから
    行われることも同時に保証する。
  * 回線が切れても指数バックオフで再接続し続ける。
  * 任意で「デッドマンスイッチ」: サーバーと一定時間つながらない場合に
    自動で売買を停止する（FAILSAFE_DISCONNECT_SEC）。

使い方:
    python bridge.py           常駐開始
    python bridge.py --check   MT5への接続と現在値だけ確認して終了
"""
from __future__ import annotations

import argparse
import asyncio
import re
import urllib.request
import calendar
import functools
import inspect
import json
import logging
import os
import random
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

# .env があれば読む（無くても動く）
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import websockets
from websockets.exceptions import WebSocketException

# websockets 13 以降は asyncio.client、それ以前は client モジュール
try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:  # websockets < 13
    from websockets.client import connect as ws_connect  # type: ignore[no-redef]

# ヘッダー引数の名前がバージョンで違うので実際のシグネチャから判定する
_CONNECT_PARAMS = inspect.signature(ws_connect).parameters
_HEADER_KW = "additional_headers" if "additional_headers" in _CONNECT_PARAMS else "extra_headers"

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - Windows以外では import できない
    mt5 = None  # type: ignore[assignment]

try:
    from mt5_terminal import (
        EA_NAMES,
        find_logged_in_terminal,
        is_gold_symbol as _is_gold_symbol,
        is_our_ea as _is_our_ea,
        resolve_terminal_exe,
    )
except ImportError:
    EA_NAMES = ("YumekkuEA-1年版",)

    def _is_our_ea(stem: str) -> bool:
        return "yumekku" in str(stem).lower()

    def _is_gold_symbol(name: str) -> bool:
        upper = str(name or "").upper()
        return "XAUUSD" in upper or "GOLD" in upper
    find_logged_in_terminal = None  # type: ignore[assignment,misc]
    resolve_terminal_exe = None  # type: ignore[assignment,misc]


log = logging.getLogger("bridge")
_LOCK_FH = None

# どの版のブリッジが動いているかを画面とログで確認できるようにする。
# 「直したのに直っていない」ときは、たいてい古いブリッジが残っている。
VERSION = "2026-09-10.1"
# どのパソコンで動いているか（サイトの管理者画面・一斉制御に出す）
_PLATFORM = "windows" if os.name == "nt" else ("mac" if sys.platform == "darwin" else sys.platform)
# 同じ会員の部屋に、別の口座のブリッジがすでに動いているとき（中継が 4002 で断る）に待つ秒数。
# すぐ繋ぎ直すと、動いているほうと追い出し合いになる。
BUSY_WAIT_SEC = 300
# exe 版は、作り直すたびに版が変わるようにする。同じ版だと「すでに動いている」と
# みなして古いブリッジがそのまま残り、作り直した exe が効かない。
if getattr(sys, "frozen", False):
    try:
        VERSION = f"{VERSION}+{int(os.path.getmtime(sys.executable))}"
    except OSError:
        pass


# 以前の版が使っていたロック名。名前が変わったせいで、
# 古いブリッジと新しいブリッジが同時に動けてしまっていた。
LOCK_NAMES = ("aitrader-bridge.lock", "trelab-bridge.lock")

# 追加口座（ロイヤルファーストクラスの 2 つ目）。1 台の PC で MT5 ごとにブリッジを 1 本ずつ動かすとき、
# 2 本目以降は BRIDGE_SLOT=<口座番号> で起動する。ロック・設定・指令ファイルを口座番号で分け、
# 1 本目（SLOT 無し＝これまでどおり）とは互いに干渉しない。
SLOT = os.environ.get("BRIDGE_SLOT", "").strip()
# このブリッジが担当する口座番号（接続ツールが渡す。追加口座は SLOT と同じ）。
# 繋いだ MT5 の口座がこれと違えば、担当の MT5 を探して繋ぎ直す。指令も担当の口座あてにしか書かない
OWN_ACCOUNT = os.environ.get("BRIDGE_ACCOUNT", "").strip() or SLOT
if not SLOT.isdigit():
    SLOT = ""
# この口座のチャートに載っているべき EA の名前。1 本目は配っている EA（EA_NAMES[0]）、
# 追加口座は接続ツールが BRIDGE_EA_NAME で渡す（安定低月利ver）。画面の「○○を載せてください」に使う
EXPECTED_EA = os.environ.get("BRIDGE_EA_NAME", "").strip() or EA_NAMES[0]


def _lock_name() -> str:
    return f"aitrader-bridge-{SLOT}.lock" if SLOT else LOCK_NAMES[0]


def _slot_ok(cmdline: str) -> bool:
    """そのプロセスが「自分と同じ枠」のブリッジか。1 本目は --slot 付きを触らず、追加口座は自分の口座だけ。"""
    low = (cmdline or "").lower()
    if SLOT:
        return f"--slot {SLOT}" in low
    return "--slot" not in low

# サイトから書き換えてよい変数と、その範囲（下限, 上限）。
# 画面の `src/data/eaSettings.ts` と同じ値をここにも置く。
# 画面だけの制限にしないのは、中継に直接つないだ相手を通さないため。
# 項目を増やすときは両方に足すこと。
ALLOWED_VARIABLES: dict[str, tuple[float, float]] = {
    "AI_TRADING_ALLOWED": (0.0, 1.0),
    "AI_LOT": (0.01, 5.0),
    "AI_MAX_POSITIONS": (1.0, 10.0),
    "AI_DAY_LOSS_LIMIT": (5000.0, 200000.0),
}
LOCK_RECORD_LEN = 128  # 番号・版・部屋を固定長で書く（切り詰めない）


def _lock_dir() -> Path:
    return Path(os.environ.get("TEMP", "."))


def _read_lock(path: Path) -> tuple[int | None, str]:
    """ロックの1行目=番号(PID)、2行目=版"""
    try:
        lines = path.read_text(encoding="ascii", errors="ignore").splitlines()
    except OSError:
        return None, ""
    pid = None
    if lines and lines[0].strip().isdigit():
        pid = int(lines[0].strip())
    version = lines[1].strip() if len(lines) > 1 else ""
    return pid, version


def _process_image(pid: int) -> str:
    """その番号のプロセスの実行ファイル名。無ければ空。

    Windows の os.kill(pid, 0) は「生きているか確認」ではなく
    その場で強制終了してしまう（Python の仕様）。番号が使い回されて
    別のソフトを巻き添えにしかねないので、名前で確かめてから触る。
    """
    if pid <= 0:
        return ""
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=20,
                creationflags=flags,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""
        line = out.strip().splitlines()[0].strip() if out.strip() else ""
        if not line.startswith('"'):
            return ""  # 「該当するプロセスはありません」
        return line.split('","')[0].strip('"')
    try:
        os.kill(pid, 0)  # POSIX ではシグナル0が生存確認
        return "python"
    except PermissionError:
        return "python"
    except OSError:
        return ""


def _process_alive(pid: int) -> bool:
    return bool(_process_image(pid))


def _is_bridge_process(pid: int) -> bool:
    """ブリッジ（python か、自分と同じ実行ファイル）かどうか。

    番号の使い回しで無関係なソフトを終了させないための確認。
    """
    image = _process_image(pid).lower()
    if not image:
        return False
    # 前の名前（AITrader.exe）で動いている古いブリッジも、自分と同じ名前のものも相手にする。
    # exe の名前を変えたらここにも足す（connect.py の BRIDGE_IMAGE_HINTS と同じ考え方）
    hints = ("python", "aitrader", "mt5automatic", "dreamlandpassport", "trelab", Path(sys.executable).name.lower())
    return any(h in image for h in hints)


def _terminate(pid: int) -> None:
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            check=False,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def _list_bridge_processes() -> list[int]:
    """bridge.py（か exe の --run-bridge）として動いている、自分以外のプロセス番号。

    古い版はロックに番号を書いていないので、ロックだけでは見つけられない。
    """
    me = os.getpid()
    # exe 版（PyInstaller onefile）は「起動役の親 → 本体」の2プロセスで、どちらも
    # コマンドラインが同じ。親を古いブリッジと間違えて終了させると自分も道連れになる。
    skip = {me, os.getppid()}
    if os.name == "nt":
        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -and "
            "($_.CommandLine -like '*bridge.py*' -or $_.CommandLine -like '*--run-bridge*') } | "
            "ForEach-Object { \"$($_.ProcessId)|$($_.Name)|$($_.CommandLine)\" }"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=40,
                creationflags=flags,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
    else:
        try:
            raw = subprocess.run(
                ["ps", "-eo", "pid=,args="],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=20,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        out = "\n".join(
            f"{ln.split()[0]}|{Path(ln.split()[1]).name}"
            for ln in raw.splitlines()
            if ln.strip() and ("bridge.py" in ln or "--run-bridge" in ln)
        )
    pids: list[int] = []
    own_exe = Path(sys.executable).name.lower()
    for line in out.splitlines():
        if "|" not in line:
            continue
        pid_s, rest = line.strip().split("|", 1)
        image, _, cmdline = rest.partition("|")
        if not pid_s.isdigit():
            continue
        pid = int(pid_s)
        image = image.lower()
        if pid in skip:
            continue
        # 「--run-bridge」付きで起動されていれば名前が何であれブリッジ（名前を書き換えられた exe も拾う）。
        # 同じ名前しか見ないと、別名の古いブリッジを「触らない」と判定して止められず、
        # 新しいブリッジは「別のブリッジがすでに動いています」で起動できない（実機・VPS で起きた）
        if not _slot_ok(cmdline):
            continue   # 別の枠（1 本目／別の追加口座）のブリッジは触らない
        if "--run-bridge" in cmdline or "python" in image or image == own_exe or any(h in image for h in ("aitrader", "mt5automatic", "dreamlandpassport", "trelab")):
            pids.append(pid)
    # PowerShell が使えない・コマンドラインを読めない PC への保険①：wmic でコマンドラインから探す
    if os.name == "nt" and not pids:
        try:
            raw = subprocess.run(
                ["wmic", "process", "where", "commandline like '%bridge.py%' or commandline like '%--run-bridge%'",
                 "get", "CommandLine,Name,ProcessId", "/format:csv"],
                capture_output=True, text=True, errors="replace", check=False, timeout=40,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            raw = ""
        for line in raw.splitlines():
            parts = [x.strip() for x in line.strip().split(",")]
            if len(parts) < 3 or not parts[-1].isdigit():
                continue
            pid, name = int(parts[-1]), parts[-2].lower()
            cmdline = ",".join(parts[1:-2]).lower()
            if pid in skip or not _slot_ok(cmdline):
                continue
            if "--run-bridge" in cmdline or "python" in name or any(h in name for h in ("aitrader", "mt5automatic", "dreamlandpassport", "trelab")):
                pids.append(pid)
    # 保険②：tasklist でパスポートの名前のプロセスを拾う（自分と親は除く）。
    # ロックのファイルがあるのに他に見つからなければ、pythonw.exe（9 月の Python 版）も拾う
    lock_exists = any((_lock_dir() / name).is_file() for name in LOCK_NAMES)
    if os.name == "nt" and not pids and not SLOT and not out.strip():
        try:
            raw = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, errors="replace", check=False, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            raw = ""
        import csv
        import io
        for row in csv.reader(io.StringIO(raw)):
            if len(row) < 2 or not row[1].strip().isdigit():
                continue
            name = row[0].strip().lower()
            pid = int(row[1])
            if pid in skip or name == "python.exe":
                continue
            if name == "pythonw.exe":
                if lock_exists:
                    pids.append(pid)
                continue
            if any(h in name for h in ("aitrader", "mt5automatic", "dreamlandpassport", "trelab")):
                pids.append(pid)
    return pids

def _hand_over_to_link_waiter() -> None:
    """会員が消された・止められたとき、接続ツールの「合図を待つ係」を起こしてから終わる。

    お客様がロビーで登録し直して「設置が終わった」を押せば、その係が合図を受け取って
    新しい会員の部屋に紐づけ直す（接続ツールを開き直してもらわなくてよい）。exe 版だけ。
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
        subprocess.Popen([sys.executable, "--wait-link"], creationflags=flags, close_fds=True)
        log.info("接続ツールに「設置が終わった」待ちを引き継ぎました")
    except Exception as exc:  # noqa: BLE001
        log.warning("「設置が終わった」待ちを起こせませんでした: %s", exc)


def takeover_old_bridges() -> None:
    """自分より古い版のブリッジが残っていたら終わらせる。

    二重に動くと、両方が売買フラグを書きにいって取り合いになる。
    「触っていないのに稼働中と停止中が入れ替わる」のはこれが原因だった。
    """
    me = os.getpid()
    parent = os.getppid()
    same_version: set[int] = set()
    targets: dict[int, str] = {}
    # 追加口座は自分のロックだけを見る。1 本目は古い名前のロックも見る
    for name in ((_lock_name(),) if SLOT else LOCK_NAMES):
        path = _lock_dir() / name
        if not path.is_file():
            continue
        pid, version = _read_lock(path)
        if pid is None or pid == me or pid == parent:
            continue
        if version == VERSION:
            same_version.add(pid)
            continue  # 同じ版なら二重起動チェックに任せる
        if not _is_bridge_process(pid):
            continue  # もう居ない、または番号が使い回されている
        targets[pid] = version or "不明"
    # ロックに番号を書かない古い版は、コマンドラインから探す
    for pid in _list_bridge_processes():
        if pid not in same_version and pid not in targets:
            targets[pid] = "不明"
    for pid, version in targets.items():
        log.warning(
            "古いブリッジ（PID %s / 版 %s）が動いています。指令が競合するので終了させます",
            pid,
            version,
        )
        _terminate(pid)
        for _ in range(20):
            if not _process_alive(pid):
                log.info("古いブリッジを終了しました")
                break
            time.sleep(0.25)
        else:
            log.error(
                "古いブリッジ（PID %s）を終了できませんでした。"
                "タスクマネージャーで pythonw.exe を終了するか、"
                "tools\\停止する.bat を実行してください",
                pid,
            )


def acquire_instance_lock() -> None:
    """同じPCで bridge.py を二重起動すると、中継が切断と再接続を繰り返す。"""
    global _LOCK_FH
    takeover_old_bridges()
    path = _lock_dir() / _lock_name()
    try:
        path.touch(exist_ok=True)
    except OSError:
        pass
    _LOCK_FH = open(path, "r+b")  # 追記モードだと seek しても末尾に書かれてしまう
    try:
        _LOCK_FH.seek(0)
        if os.name == "nt":
            import msvcrt

            if _LOCK_FH.read(1) == b"":
                _LOCK_FH.seek(0)
                _LOCK_FH.write(b"0")
                _LOCK_FH.flush()
            _LOCK_FH.seek(0)
            msvcrt.locking(_LOCK_FH.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_LOCK_FH.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("別のブリッジがすでに動いています。")
        log.error("tools\\停止する.bat で止めてから、もう一度お試しください。")
        raise SystemExit(2)
    # 接続ツールが「いま動いているブリッジが古くないか」を見られるよう、
    # 番号(PID)と版をロックに書いておく。ロックを取れた側だけが書く。
    # 切り詰めずに固定長で上書きする（ロック中の領域でも自分の handle からは書ける）。
    # 3行目は部屋（会員ID）。接続ツールが「サイトと違う部屋で動いていないか」を見る。
    room = os.environ.get("BRIDGE_ID", "").strip() or "vps-01"
    stamp = f"{os.getpid()}\n{VERSION}\n{room}\n".encode("ascii", "replace").ljust(LOCK_RECORD_LEN, b" ")
    try:
        _LOCK_FH.seek(0)
        _LOCK_FH.write(stamp)
        _LOCK_FH.flush()
    except OSError as exc:
        log.warning("ロックに番号を書けませんでした: %s", exc)


# ============================================================
# 設定（すべて環境変数から。.env でも可）
# ============================================================
def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _load_clock_offset() -> int:
    """前回おぼえた「サーバー時計と UTC の差」。

    休場中（週末・お正月）に起動すると、最後のティックが何日も前なので
    時差を割り出せない。そのとき 0（＝UTC）に戻ると、ブローカーとの時差ぶん
    日付の境目がずれて、「今日の成績」が前日ぶんになったり、直近の取引が
    窓から外れたりする。前回の値を覚えておけば、開くまでの間もずれない。
    """
    try:
        raw = json.loads((_config_dir() / "clock.json").read_text(encoding="utf-8"))
        offset = int(raw.get("server_offset_sec", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0
    return offset if abs(offset) <= 14 * 3600 else 0


def _save_clock_offset(offset: int) -> None:
    try:
        (_config_dir() / "clock.json").write_text(
            json.dumps({"server_offset_sec": int(offset)}, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:  # 書けなくても動作は変わらない
        log.debug("サーバー時計の覚え書きを保存できません: %s", exc)


def _config_dir() -> Path:
    """設定の置き場。intent.json と同じ %LOCALAPPDATA%\\AITrader。

    AIリスク監督が「反映 / 記録のみ / 切」の選択を覚えておくのに使う。
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
    folder = Path(base) / "AITrader"
    if SLOT:
        folder = folder / "accounts" / SLOT   # 追加口座は口座番号ごとに分ける
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(os.environ.get("TEMP", "."))
    return folder


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, "").strip() or default)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, "").strip() or default)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass
class Config:
    # 接続先
    ws_url: str = field(default_factory=lambda: _env_str("TRELAB_WS_URL", "ws://127.0.0.1:8080/bridge"))
    token: str = field(default_factory=lambda: _env_str("TRELAB_TOKEN"))
    bridge_id: str = field(default_factory=lambda: _env_str("BRIDGE_ID", "vps-01"))

    # MT5
    mt5_path: str = field(default_factory=lambda: _env_str("MT5_PATH"))
    mt5_login: int = field(default_factory=lambda: _env_int("MT5_LOGIN", 0))
    mt5_password: str = field(default_factory=lambda: _env_str("MT5_PASSWORD"))
    mt5_server: str = field(default_factory=lambda: _env_str("MT5_SERVER"))
    mt5_timeout: int = field(default_factory=lambda: _env_int("MT5_TIMEOUT", 60_000))

    # EAが毎Tick読むグローバル変数
    gv_name: str = field(default_factory=lambda: _env_str("GV_NAME", "AI_TRADING_ALLOWED"))
    gv_default: float = field(default_factory=lambda: _env_float("GV_DEFAULT", 1.0))

    # 再接続（指数バックオフ）
    reconnect_min: float = field(default_factory=lambda: _env_float("RECONNECT_MIN_SEC", 3.0))
    reconnect_max: float = field(default_factory=lambda: _env_float("RECONNECT_MAX_SEC", 60.0))

    # WebSocketのキープアライブ。切断検知はライブラリのpingに任せる
    ping_interval: float = field(default_factory=lambda: _env_float("PING_INTERVAL_SEC", 20.0))
    # ping_timeout は「返事が来なくて切る」までの猶予。短いと、回線が数十秒
    # 詰まっただけで切れてしまい、そのたび再接続のやり直しになる。
    # 切断の検知が遅れても困るのは失効までの数十秒だけなので、長めに取る。
    ping_timeout: float = field(default_factory=lambda: _env_float("PING_TIMEOUT_SEC", 60.0))
    open_timeout: float = field(default_factory=lambda: _env_float("OPEN_TIMEOUT_SEC", 15.0))

    # 見張り
    watchdog_interval: float = field(default_factory=lambda: _env_float("WATCHDOG_INTERVAL_SEC", 30.0))
    # 口座の数字（残高・建玉・今日の成績）を画面へ送り直す間隔
    push_interval: float = field(default_factory=lambda: _env_float("PUSH_INTERVAL_SEC", 5.0))
    reassert: bool = field(default_factory=lambda: _env_bool("REASSERT_STATE", True))
    # 0 より大きいと、その秒数だけ切断が続いた時に自動で売買を止める（デッドマンスイッチ）
    failsafe_sec: float = field(default_factory=lambda: _env_float("FAILSAFE_DISCONNECT_SEC", 0.0))

    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO").upper())
    log_file: str = field(default_factory=lambda: _env_str("LOG_FILE"))


def setup_logging(cfg: Config) -> None:
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.log_level, logging.INFO))

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    if cfg.log_file:
        rotating = RotatingFileHandler(cfg.log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        rotating.setFormatter(fmt)
        root.addHandler(rotating)

    # websockets 自身のログは煩いので一段落とす
    logging.getLogger("websockets").setLevel(logging.WARNING)


# ============================================================
# MT5 の面倒を見る係
#   MetaTrader5 は同期APIなので、専用スレッド1本に閉じ込めて
#   イベントループからは run_in_executor 経由でのみ触る。
# ============================================================
def _terminal_exes() -> list[Path]:
    """この PC の MT5（terminal64.exe）を全部。担当の口座の MT5 を探すのに使う。"""
    out: list[Path] = []
    try:
        from mt5_terminal import iter_terminal_data_dirs, terminal_dir_from_data_path
    except Exception:  # noqa: BLE001
        return out
    try:
        for data_dir in iter_terminal_data_dirs():
            folder = terminal_dir_from_data_path(data_dir)
            exe = folder / "terminal64.exe" if folder is not None else None
            if exe is not None and exe.is_file() and exe not in out:
                out.append(exe)
    except Exception:  # noqa: BLE001
        pass
    return out


def _attach_to(exe: Path, timeout_ms: int) -> dict[str, Any] | None:
    """名指しした MT5（terminal64.exe）に繋ぐ。ログインしていなければ None。

    path を渡さない initialize は「どれか」に繋ぐので、MT5 が何台もある PC では
    EA を載せたのと別のターミナルに繋がることがある。初回に選んだものへ繋ぐ入口。
    """
    if mt5 is None:
        return None
    try:
        mt5.shutdown()
    except Exception:  # noqa: BLE001
        pass
    try:
        if not mt5.initialize(path=str(exe), timeout=timeout_ms):
            return None
        info = mt5.account_info()
    except Exception as exc:  # noqa: BLE001
        log.debug("名指しの MT5 に繋げません: %s", exc)
        return None
    if info is None or not getattr(info, "login", None):
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass
        return None
    return {"account": getattr(info, "login", None), "server": getattr(info, "server", "")}


class MT5Controller:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")
        self._lock = asyncio.Lock()
        self.ready = False
        self.mt5_error = ""   # 最後に MT5 へつなげなかった理由（サイトに見せる）
        # 「サーバーから最後に指示された状態」。再接続や再起動のあとで復元する。
        # 起動時は adopt_current_state() で MT5 側の実際の値を引き継ぐので、
        # ここでの初期値は「MT5 側にも記録が無かったとき」だけ使われる。
        self.desired_value: float = cfg.gv_default
        # ブローカーのサーバー時刻と UTC の差（秒）。履歴の日付はこれで判断する
        self._server_offset: int = _load_clock_offset()
        self._server_offset_at: float = 0.0

    async def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """ブロッキングなMT5呼び出しを専用スレッドで実行する"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, functools.partial(fn, *args, **kwargs))

    # ---------- 初期化 ----------
    def _initialize_blocking(self) -> bool:
        ok = self._initialize_any_blocking()
        if not ok or not OWN_ACCOUNT:
            return ok
        if self._login() == OWN_ACCOUNT:
            return True
        # 担当と違う口座の MT5 に繋がった。担当の口座でログインしている MT5 を探して繋ぎ直す
        log.warning("担当の口座 …%s ではない MT5（口座 …%s）に繋がりました。担当の MT5 を探します",
                    OWN_ACCOUNT[-4:], (self._login() or "?")[-4:])
        for exe in _terminal_exes():
            session = _attach_to(exe, self.cfg.mt5_timeout)
            if session and str(session.get("account") or "") == OWN_ACCOUNT:
                log.info("担当の MT5 に繋ぎ直しました: 口座 …%s  %s", OWN_ACCOUNT[-4:], exe)
                return True
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass
        log.error("担当の口座 …%s でログインしている MT5 が見つかりません（別の口座は操作しません）", OWN_ACCOUNT[-4:])
        return False

    def _initialize_any_blocking(self) -> bool:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 パッケージが見つかりません（Windows + 64bit Python が必要です）")

        # 初回の設定で選んだ MT5（接続ツールが MT5_PATH で渡してくる）を最優先にする。
        # ここを飛ばして「ログイン中のどれか」に繋ぐと、MT5 が何台もある PC では
        # 別のターミナルに繋がり、EA を載せた側の「アルゴ取引」が ON でも
        # サイトには OFF と見えたまま（terminal_trade_allowed は繋いだ側の値）になる。
        chosen = Path(self.cfg.mt5_path) if self.cfg.mt5_path else None
        if chosen is not None and chosen.is_file():
            session = _attach_to(chosen, self.cfg.mt5_timeout)
            if session:
                log.info(
                    "MT5 接続成功（初回に選んだターミナル）  口座=%s  サーバー=%s  %s",
                    session.get("account"),
                    session.get("server"),
                    chosen,
                )
                return True
            log.warning("初回に選んだ MT5 に繋げません（ログインしていない？）: %s。ほかを探します", chosen)

        # いまログインしている MT5 を優先（複数ターミナル・古い MT5_PATH より信頼できる）
        if find_logged_in_terminal is not None:
            session = find_logged_in_terminal()
            if session:
                info = mt5.account_info()
                term = mt5.terminal_info()
                log.info(
                    "MT5 接続成功（ログイン中ターミナル）  口座=%s  サーバー=%s  ターミナル=%s",
                    getattr(info, "login", session.get("account")),
                    getattr(info, "server", session.get("server")),
                    getattr(term, "name", session.get("terminal_name")),
                )
                return True

        kwargs: dict[str, Any] = {"timeout": self.cfg.mt5_timeout}
        terminal_path = self.cfg.mt5_path
        if terminal_path:
            kwargs["path"] = terminal_path
        if self.cfg.mt5_login:
            kwargs["login"] = self.cfg.mt5_login
            kwargs["password"] = self.cfg.mt5_password
            kwargs["server"] = self.cfg.mt5_server

        if not mt5.initialize(**kwargs):
            log.error("MT5 初期化に失敗: %s", mt5.last_error())
            self.mt5_error = f"MT5 初期化に失敗: {mt5.last_error()}"
            return False
        self.mt5_error = ""
        return True

    async def connect(self) -> bool:
        async with self._lock:
            ok = await self._call(self._initialize_blocking)
            self.ready = bool(ok)
            if ok:
                info = await self._call(mt5.account_info)
                term = await self._call(mt5.terminal_info)
                log.info(
                    "MT5 接続成功  口座=%s  サーバー=%s  ターミナル=%s build %s",
                    getattr(info, "login", "?"),
                    getattr(info, "server", "?"),
                    getattr(term, "name", "?"),
                    getattr(term, "build", "?"),
                )
                if term is not None and not getattr(term, "trade_allowed", True):
                    log.warning("ターミナル側の自動売買が無効です（AutoTradingボタンを確認してください）")
            return self.ready

    async def connect_with_retry(self, stop: asyncio.Event) -> None:
        """MT5に繋がるまで諦めずに待つ（ターミナル起動待ちを想定）"""
        backoff = Backoff(self.cfg.reconnect_min, self.cfg.reconnect_max)
        while not stop.is_set():
            if await self.connect():
                return
            delay = backoff.next()
            log.warning("MT5 に接続できません。%.1f 秒後に再試行します", delay)
            await _sleep_or_stop(delay, stop)

    async def shutdown(self) -> None:
        if mt5 is not None and self.ready:
            try:
                await self._call(mt5.shutdown)
            except Exception as exc:  # noqa: BLE001
                log.debug("MT5 shutdown 中の例外: %s", exc)
        self.ready = False
        self._pool.shutdown(wait=False)

    # ---------- お客様の意思（稼働 / 停止） ----------
    # 売買フラグを動かしてよいのは「サイトからの指示」だけ。
    # 起動しなおしても、ブリッジが増えても、ここに書いてある値に必ず揃える。
    def _intent_path(self) -> Path:
        folder = _config_dir()   # 追加口座は口座番号ごとのフォルダ
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return Path(os.environ.get("TEMP", ".")) / "aitrader-intent.json"
        return folder / "intent.json"

    def _load_intent(self) -> dict[str, Any] | None:
        path = self._intent_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or "allowed" not in data:
            return None
        return data

    def _save_intent(self, allowed: float, by: str) -> None:
        data = {
            "allowed": float(allowed),
            "by": by,
            "at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            self._intent_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("意思を保存できません: %s", exc)
        self.intent_by = by
        self.intent_at = data["at"]

    # ---------- 指令ファイル（Python API に global_variable_set が無いため） ----------
    GATE_FILE = "trelab_gate.ini"

    def _login(self) -> str:
        """いまつないでいる口座番号（読めなければ空）。指令ファイルを口座ごとに分けるのに使う。"""
        try:
            info = mt5.account_info() if (mt5 is not None and self.ready) else None
            login = int(getattr(info, "login", 0) or 0)
            return str(login) if login else ""
        except Exception:  # noqa: BLE001
            return ""

    def _gate_name(self) -> str:
        # 追加口座は口座番号付きの名前だけを使う。1 本目はこれまでどおりの名前（古い EA も読める）
        return f"trelab_gate_{SLOT}.ini" if SLOT else self.GATE_FILE

    def _gate_dir(self) -> Path:
        term = mt5.terminal_info() if mt5 is not None else None
        common = getattr(term, "commondata_path", None) if term is not None else None
        if not common:
            common = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", "Common")
        folder = Path(str(common)) / "Files"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _gate_path(self) -> Path:
        return self._gate_dir() / self._gate_name()

    def _load_gate(self) -> dict[str, float]:
        path = self._gate_path()
        values: dict[str, float] = {}
        if not path.exists():
            return values
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, raw = line.split("=", 1)
                try:
                    values[key.strip()] = float(raw.strip())
                except ValueError:
                    continue
        except OSError as exc:
            log.warning("指令ファイルを読めません: %s", exc)
        return values

    def _save_gate(self, values: dict[str, float]) -> Path:
        path = self._gate_path()
        # 「名前=数値」1行の形しか書かない。名前に改行が混じると、
        # 指令ファイルに好きな行を足せてしまう（EA はそれを設定として読む）。
        safe = {
            k: float(v)
            for k, v in values.items()
            if isinstance(k, str) and k.replace("_", "").isalnum() and isinstance(v, (int, float))
        }
        for k in values.keys() - safe.keys():
            log.warning("指令ファイルに書けない名前を捨てました: %r", str(k)[:40])
        path_values = safe
        body = "".join(f"{k}={v}\n" for k, v in sorted(path_values.items()))
        tmp = path.with_suffix(".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
        # 1 本目は、口座番号付きの名前にも同じ中身を置く。新しい EA は口座番号付きがあればそちらを読むので、
        # 同じ PC に追加口座（別の MT5）があっても、EA が別口座の指令を読むことがない
        if not SLOT:
            login = self._login()
            if OWN_ACCOUNT and login and login != OWN_ACCOUNT:
                # 別の口座の MT5 に繋がっているときは、その口座あてには書かない（別の口座の EA が動いてしまう）
                log.warning("繋いでいる口座 …%s は担当（…%s）と違うので、口座番号付きの指令は書きません", login[-4:], OWN_ACCOUNT[-4:])
                login = ""
            if login:
                try:
                    mirror = path.with_name(f"trelab_gate_{login}.ini")
                    tmp2 = mirror.with_suffix(".tmp")
                    tmp2.write_text(body, encoding="utf-8")
                    tmp2.replace(mirror)
                except OSError as exc:
                    log.debug("口座番号付きの指令ファイルを書けませんでした: %s", exc)
        return path

    def _set_gv_blocking(self, name: str, value: float) -> tuple[bool, float | None]:
        # 公式 Python API には GlobalVariableSet が無い。Common/Files に書いて EA が読む。
        setter = getattr(mt5, "global_variable_set", None) if mt5 is not None else None
        if callable(setter):
            ok = bool(setter(name, float(value)))
            if not ok:
                log.error("グローバル変数の書き込みに失敗 %s=%s: %s", name, value, mt5.last_error())
                return False, None
            getter = getattr(mt5, "global_variable_get", None)
            readback = getter(name) if callable(getter) else float(value)
            return True, readback

        values = self._load_gate()
        values[name] = float(value)
        path = self._save_gate(values)
        self._backup_settings_blocking({name: float(value)})
        log.info("指令ファイルに書き込み: %s=%s  (%s)", name, value, path)
        return True, values[name]

    def _get_gv_blocking(self, name: str) -> float | None:
        getter = getattr(mt5, "global_variable_get", None) if mt5 is not None else None
        if callable(getter):
            try:
                return getter(name)
            except Exception:  # noqa: BLE001
                pass
        return self._load_gate().get(name)

    async def set_variable(self, name: str, value: float) -> tuple[bool, float | None]:
        if not self.ready:
            log.error("MT5 未接続のため %s を設定できません", name)
            return False, None
        async with self._lock:
            return await self._call(self._set_gv_blocking, name, value)

    # サイトから受けた設定（ロット・同時保有・1日の損失上限・稼働/停止）は、
    # 指令ファイルとは別に控えておく。指令ファイルは MT5 の入れ直しや掃除で
    # 消えることがあり、消えたままだと EA は上限なしで動いてしまう。
    SETTING_KEYS = ("AI_LOT", "AI_MAX_POSITIONS", "AI_DAY_LOSS_LIMIT", "AI_TRADING_ALLOWED")

    def _settings_backup_path(self) -> Path:
        return _config_dir() / "gate_settings.json"

    def _backup_settings_blocking(self, values: dict[str, float]) -> None:
        keep = {k: float(v) for k, v in values.items() if k in self.SETTING_KEYS}
        if not keep:
            return
        path = self._settings_backup_path()
        try:
            current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            current = {}
        current.update(keep)
        try:
            path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.debug("設定の控えを書けませんでした: %s", exc)

    def _restore_settings_blocking(self) -> list[str]:
        """指令ファイルから消えた設定を、控えから書き戻す。"""
        path = self._settings_backup_path()
        if not path.is_file():
            return []
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        gate = self._load_gate()
        missing = {k: float(v) for k, v in saved.items() if k in self.SETTING_KEYS and k not in gate}
        if not missing:
            return []
        gate.update(missing)
        self._save_gate(gate)
        return sorted(missing)

    async def restore_settings(self) -> list[str]:
        if not self.ready:
            return []
        async with self._lock:
            return await self._call(self._restore_settings_blocking)

    def _set_gvs_blocking(self, values: dict[str, float]) -> bool:
        """複数の値をまとめて指令ファイルへ。EA が中途半端な組み合わせを読まないようにする。"""
        current = self._load_gate()
        current.update({k: float(v) for k, v in values.items()})
        self._save_gate(current)
        self._backup_settings_blocking(values)
        setter = getattr(mt5, "global_variable_set", None) if mt5 is not None else None
        if callable(setter):
            for key, value in values.items():
                try:
                    setter(key, float(value))
                except Exception:  # noqa: BLE001 指令ファイル側が本命なので握りつぶす
                    pass
        return True

    # EA のパネルに「ユメックAIと連携済み」を出すための合図。指令ファイルに PC の時計
    # （UNIX 秒・ローカル時刻。EA の TimeLocal() と同じ数え方）を書き、EA は
    # それが 3 分より古ければ「未接続」と出す（TradingGate.mqh の GateBridgeAlive）。
    GATE_HEARTBEAT = "AI_BRIDGE_AT"

    def _touch_gate_blocking(self) -> bool:
        values = self._load_gate()
        values[self.GATE_HEARTBEAT] = float(calendar.timegm(time.localtime()))
        try:
            self._save_gate(values)
        except OSError as exc:
            log.debug("合図を書けませんでした: %s", exc)
            return False
        return True

    async def touch_gate(self) -> bool:
        if not self.ready:
            return False
        async with self._lock:
            return await self._call(self._touch_gate_blocking)

    async def set_variables(self, values: dict[str, float]) -> bool:
        if not self.ready or not values:
            return False
        async with self._lock:
            return await self._call(self._set_gvs_blocking, values)

    async def get_variable(self, name: str) -> float | None:
        if not self.ready:
            return None
        async with self._lock:
            return await self._call(self._get_gv_blocking, name)

    async def adopt_current_state(self) -> float:
        """起動時は「お客様の意思」に MT5 を合わせる。

        意思の記録が無い＝まだ一度も操作していないので、安全側の
        「停止」から始める。稼働に変わるのはサイトで押されたときだけ。
        """
        intent = self._load_intent()
        if intent is not None:
            self.desired_value = float(intent.get("allowed", 0.0))
            self.intent_by = str(intent.get("by", ""))
            self.intent_at = str(intent.get("at", ""))
            log.info(
                "前回の指示を引き継ぎます: %s (%s に %s から)",
                "稼働" if self.desired_value != 0 else "停止",
                self.intent_at or "不明",
                self.intent_by or "不明",
            )
        else:
            self.desired_value = 0.0
            self._save_intent(0.0, "init")
            log.info("指示の記録が無いので、停止の状態から始めます")

        current = await self.get_variable(self.cfg.gv_name)
        if current is None or float(current) != float(self.desired_value):
            log.info(
                "MT5 側を指示に合わせます: %s = %s（MT5は %s でした）",
                self.cfg.gv_name,
                self.desired_value,
                current,
            )
            await self.set_variable(self.cfg.gv_name, self.desired_value)
        return self.desired_value

    async def set_trading(self, allowed: bool, by: str = "サイト") -> tuple[bool, float | None]:
        value = 1.0 if allowed else 0.0
        self.desired_value = value
        self._save_intent(value, by)
        ok, readback = await self.set_variable(self.cfg.gv_name, value)
        if ok:
            log.info(
                "売買フラグを更新: %s = %s (%s)",
                self.cfg.gv_name,
                value,
                "許可" if allowed else "停止",
            )
        return ok, readback

    # ---------- 全決済（一斉制御の「新規を止めて全ポジションも決済」で使う） ----------
    async def close_all(self) -> dict[str, Any]:
        if not self.ready:
            return {"closed": 0, "removed": 0, "failed": [], "error": "MT5に接続していません"}
        return await self._call(self._close_all_blocking)

    @staticmethod
    def _filling_for(symbol: str) -> int:
        """その銘柄で使える約定方式。業者によって違うので symbol_info から選ぶ。"""
        try:
            info = mt5.symbol_info(symbol)
            flags = int(getattr(info, "filling_mode", 0) or 0)
        except Exception:  # noqa: BLE001
            flags = 0
        fok = int(getattr(mt5, "SYMBOL_FILLING_FOK", 1))
        ioc = int(getattr(mt5, "SYMBOL_FILLING_IOC", 2))
        if flags & ioc:
            return int(getattr(mt5, "ORDER_FILLING_IOC", 1))
        if flags & fok:
            return int(getattr(mt5, "ORDER_FILLING_FOK", 0))
        return int(getattr(mt5, "ORDER_FILLING_RETURN", 2))

    def _close_all_blocking(self) -> dict[str, Any]:
        """持っている建玉を全部閉じ、待機注文も全部取り消す。

        手動・EA を問わず、この口座にあるものを全部対象にする（一斉停止の意図は
        「この口座をいったん空にする」なので、magic で選り分けない）。
        1件の失敗で止めず、最後まで回して失敗した番号を返す。
        """
        done = int(getattr(mt5, "TRADE_RETCODE_DONE", 10009))
        placed = int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008))
        closed = 0
        removed = 0
        failed: list[dict[str, Any]] = []

        try:
            positions = list(mt5.positions_get() or ())
        except Exception as exc:  # noqa: BLE001
            return {"closed": 0, "removed": 0, "failed": [], "error": f"建玉を読めません: {exc}"}
        type_buy = int(getattr(mt5, "POSITION_TYPE_BUY", 0))
        for pos in positions:
            ticket = int(getattr(pos, "ticket", 0) or 0)
            symbol = str(getattr(pos, "symbol", "") or "")
            volume = float(getattr(pos, "volume", 0) or 0)
            is_buy = int(getattr(pos, "type", type_buy)) == type_buy
            tick = mt5.symbol_info_tick(symbol)
            price = float(getattr(tick, "bid" if is_buy else "ask", 0) or 0)
            request = {
                "action": int(getattr(mt5, "TRADE_ACTION_DEAL", 1)),
                "position": ticket,
                "symbol": symbol,
                "volume": volume,
                "type": int(getattr(mt5, "ORDER_TYPE_SELL" if is_buy else "ORDER_TYPE_BUY", 1 if is_buy else 0)),
                "price": price,
                "deviation": 50,
                "magic": int(getattr(pos, "magic", 0) or 0),
                "comment": "fleet close",
                "type_time": int(getattr(mt5, "ORDER_TIME_GTC", 0)),
                "type_filling": self._filling_for(symbol),
            }
            try:
                result = mt5.order_send(request)
            except Exception as exc:  # noqa: BLE001
                failed.append({"ticket": ticket, "error": str(exc)})
                continue
            code = int(getattr(result, "retcode", -1)) if result is not None else -1
            if code in (done, placed):
                closed += 1
            else:
                failed.append({"ticket": ticket, "retcode": code, "error": str(getattr(result, "comment", "") or "")})

        try:
            orders = list(mt5.orders_get() or ())
        except Exception as exc:  # noqa: BLE001
            orders = []
            failed.append({"ticket": 0, "error": f"待機注文を読めません: {exc}"})
        for order in orders:
            ticket = int(getattr(order, "ticket", 0) or 0)
            request = {"action": int(getattr(mt5, "TRADE_ACTION_REMOVE", 8)), "order": ticket}
            try:
                result = mt5.order_send(request)
            except Exception as exc:  # noqa: BLE001
                failed.append({"ticket": ticket, "error": str(exc)})
                continue
            code = int(getattr(result, "retcode", -1)) if result is not None else -1
            if code in (done, placed):
                removed += 1
            else:
                failed.append({"ticket": ticket, "retcode": code, "error": str(getattr(result, "comment", "") or "")})

        log.warning("全決済: 建玉 %d 件を決済、待機注文 %d 件を取り消し、失敗 %d 件", closed, removed, len(failed))
        return {"closed": closed, "removed": removed, "failed": failed}

    STATE_FILE = "trelab_state.ini"

    def _ea_state_blocking(self) -> dict[str, Any]:
        """MT5 のチャートに出ている状態（EA が書き出したもの）。

        サイトの表示と突き合わせるために読む。ここが食い違っていたら、
        EA とブリッジが別のフォルダを見ている（または EA が止まっている）。
        """
        # 追加口座は口座番号付きの控えだけ。1 本目は口座番号付きがあればそちら、無ければこれまでの名前（古い EA）
        folder = self._gate_dir()
        if SLOT:
            path = folder / f"trelab_state_{SLOT}.ini"
        else:
            login = self._login()
            path = folder / f"trelab_state_{login}.ini" if login else folder / self.STATE_FILE
            if not path.is_file():
                path = folder / self.STATE_FILE
        out: dict[str, Any] = {}
        try:
            if not path.is_file():
                return {"ea_state": None, "ea_alive": False, "ea_ready": False, "ea_problem": None, "ea_expected": EXPECTED_EA}
            # EA(MQL5)の書き出しは環境によって文字コードが変わる。読めるもので読む
            raw = path.read_bytes()
            text = ""
            for encoding in ("utf-8", "utf-16", "cp932"):
                try:
                    candidate = raw.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    continue
                if "state=" in candidate:
                    text = candidate
                    break
            if not text:
                text = raw.decode("utf-8", "ignore")
            for line in text.splitlines():
                if "=" not in line:
                    continue
                key, raw = line.split("=", 1)
                out[key.strip()] = raw.strip()
            age = time.time() - path.stat().st_mtime
        except OSError:
            return {"ea_state": None, "ea_alive": False, "ea_ready": False, "ea_problem": None, "ea_expected": EXPECTED_EA}
        skipped = {
            key: int(float(out[key]))
            for key in ("ai_skip_buy", "ai_skip_sell", "ai_shadow_buy", "ai_shadow_sell")
            if key in out and str(out[key]).replace(".", "", 1).isdigit()
        }
        # 控え（trelab_state.ini）は PC 内の全 MT5 で1つ（FILE_COMMON）。
        # 別の MT5 に載せた EA が書いたものを「こちらの EA が生きている」と
        # 数えないよう、口座番号・EA 名・銘柄を突き合わせる。
        my_login = None
        try:
            info = mt5.account_info() if mt5 is not None else None
            my_login = int(getattr(info, "login", 0) or 0) or None
        except Exception:  # noqa: BLE001
            my_login = None
        try:
            ea_account = int(float(str(out.get("account", "")).strip() or 0)) or None
        except ValueError:
            ea_account = None
        ea_name = str(out.get("ea") or "").strip()
        ea_symbol = str(out.get("symbol") or "").strip()
        # EA は10秒ごとに書く。30秒以上古ければ、チャートから外れている
        fresh = age < 30
        same_account = (ea_account == my_login) if (ea_account and my_login) else None
        # 1 本目は「うちの EA か」（名前の後半が変わっても拾う）。追加口座は載せる EA が決まっている
        # （安定低月利ver）ので、名前そのもので見る。1 年版が載っていたら「安定低月利ver を載せてください」と出す
        if ea_name and SLOT:
            ours = (ea_name == EXPECTED_EA)
        else:
            ours = _is_our_ea(ea_name) if ea_name else None
        symbol_ok = _is_gold_symbol(ea_symbol) if ea_symbol else None
        alive = bool(fresh and same_account is not False and ours is not False)
        problem = None
        if fresh and same_account is False:
            problem = f"別の口座（{ea_account}）のMT5で動いています。いまつないでいるのは口座 {my_login} です。"
        elif fresh and ours is False:
            problem = f"「{ea_name}」が載っています。{EXPECTED_EA} を載せてください。"
        elif alive and symbol_ok is False:
            problem = f"{ea_symbol} のチャートに載っています。ゴールド（XAUUSD または GOLD）のチャートに載せてください。"
        return {
            "ea_state": out.get("state"),
            "ea_allowed": out.get("allowed"),
            "ea_state_at": out.get("at"),
            "ea_name": ea_name or None,
            "ea_expected": EXPECTED_EA,
            "ea_symbol": ea_symbol or None,
            # EA が自分の設定を書き出したもの。AI へ渡す戦略プロフィールの元になる
            "ea_profile_raw": out.get("profile"),
            "ea_skipped": skipped,
            "ea_alive": alive,
            "ea_ours": ours,
            "ea_symbol_ok": symbol_ok,
            # サイトの手順が「済み」になる条件。生きていて、ゴールドのチャートにある
            "ea_ready": bool(alive and symbol_ok is not False),
            "ea_problem": problem,
            # EA が見ているフォルダと、こちらが書いているフォルダが同じか
            "ea_same_folder": (
                str(out.get("common", "")).rstrip("\\/") == str(self._gate_path().parent.parent).rstrip("\\/")
                if out.get("common")
                else None
            ),
        }

    def _ea_probe_blocking(self) -> dict[str, Any]:
        term = mt5.terminal_info() if mt5 is not None else None
        data_path = getattr(term, "data_path", "") if term is not None else ""
        experts = Path(str(data_path)) / "MQL5" / "Experts"
        found: list[str] = []
        compiled: list[str] = []
        # 名前の後半（版など）は変わりうるので、Yumekku が入っているものを見る
        try:
            for path in sorted(experts.glob("*.ex5")):
                if _is_our_ea(path.stem):
                    compiled.append(path.stem)
                    found.append(path.stem)
            for path in sorted(experts.glob("*.mq5")):
                if _is_our_ea(path.stem) and path.stem not in found:
                    found.append(path.stem)
        except OSError:
            pass
        return {
            "ea_folder": str(experts),
            "ea_found": found,
            "ea_compiled": compiled,
            "ea_installed": len(found) > 0,
        }

    # ---------- AIリスク監督に渡す材料 ----------
    # 既定は EA の設定と同じ値。EA が状態ファイルに profile を書いていればそちらで上書きする。
    DEFAULT_PROFILE: dict[str, Any] = {
        "name": "Orbit GOLD 3軸（M1軸・M30軸・H1軸）",
        "entry": "上位トレンド方向へ、内部高値／安値のブレイク後のリテスト成立で入る",
        "ema_period": 200,
        "atr_period": 14,
        "retest_tolerance_atr": 0.12,
        "retest_bars": 6,
        "m1_sl_atr_mult": 7.0,
        "m1_tp_atr_mult": 4.5,
        "m1_min_atr_usd": 2.0,
        "m1_require_h1_align": True,
        "m1_nanpin_enabled": False,
        "m1_nanpin_step_atr": 1.0,
        "m1_nanpin_max_adds": 1,
        "m1_nanpin_sl_room": 7,
        "m30_sl_atr_mult": 5.0,
        "m30_tp_atr_mult": 4.5,
        "h1_sl_atr_mult": 7.0,
        "h1_tp_atr_mult": 4.5,
        "daily_loss_limit": 10000,
        "max_spread_usd": 0.60,
        "source": "defaults",
    }

    _TF_MAP = {"M1": "TIMEFRAME_M1", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1"}

    def _profile_from_ea(self) -> dict[str, Any]:
        """EA が書き出した設定（profile=key:value;...）を読む。無ければ既定値。"""
        profile = dict(self.DEFAULT_PROFILE)
        raw = self._ea_state_blocking().get("ea_profile_raw")
        if not raw:
            return profile
        got: dict[str, Any] = {}
        for part in str(raw).split(";"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            key, value = key.strip(), value.strip()
            if not key:
                continue
            try:
                num = float(value)
                got[key] = int(num) if num.is_integer() and "." not in value else num
            except ValueError:
                got[key] = value
        if got:
            profile.update(got)
            profile["source"] = "ea"
        return profile

    def _pick_symbol_blocking(self, wanted: str = "") -> str:
        """EA と同じ銘柄を選ぶ。EA が書き出していればそれ、無ければ XAUUSD 系を探す。"""
        if wanted:
            return wanted
        from_ea = self._ea_state_blocking().get("ea_symbol")
        if from_ea:
            return str(from_ea)
        try:
            for pos in mt5.positions_get() or ():
                name = str(getattr(pos, "symbol", ""))
                if "XAU" in name.upper() or "GOLD" in name.upper():
                    return name
        except Exception:  # noqa: BLE001
            pass
        # 業者によって金の名前が違う（XAUUSD / GOLD / GOLD# など）。名前だけで選ぶと
        # XAUEUR や XAUJPY を拾ってしまい、EA が売買している商品と別の値を
        # AI に見せることになる。ドル建ての金だけを採る。
        for pattern, wanted in (("*XAU*", "XAUUSD"), ("*GOLD*", "GOLD")):
            try:
                names = [str(getattr(c, "name", "")) for c in (mt5.symbols_get(pattern) or ())]
            except Exception:  # noqa: BLE001
                continue
            exact = [n for n in names if n.upper().startswith(wanted)]
            for name in (*exact, *[n for n in names if n not in exact]):
                if not self._is_gold_usd(name):
                    continue
                if mt5.symbol_info_tick(name) is not None:
                    log.info("AIリスク監督が見る銘柄: %s", name)
                    return name
        log.warning("金の銘柄を特定できませんでした（RISK_SYMBOL で指定できます）")
        return "XAUUSD"

    @staticmethod
    def _is_gold_usd(name: str) -> bool:
        """ドル建ての金かどうか。XAUEUR / XAUJPY を除くために通貨で確かめる。"""
        try:
            info = mt5.symbol_info(name)
        except Exception:  # noqa: BLE001
            return False
        if info is None:
            return False
        profit = str(getattr(info, "currency_profit", "") or "").upper()
        base = str(getattr(info, "currency_base", "") or "").upper()
        if profit and profit != "USD":
            return False
        # 基準通貨は業者によって書き方が違う（XM の GOLD は base も USD）。
        # XAUEUR / XAUJPY は利益通貨で弾けるので、base は利益通貨が
        # 取れないときの保険としてだけ使う。
        if not profit and base and base not in ("XAU", "GOLD", "USD"):
            return False
        # 通貨の情報を持たない業者もあるので、そのときは名前で判断する
        upper = name.upper()
        return bool(profit or base) or upper.startswith(("XAUUSD", "GOLD"))

    def _rates_blocking(self, symbol: str, tf_name: str, count: int) -> list[dict[str, Any]]:
        """確定した足だけを新しい順→古い順で返す（最後の形成中の足は落とす）。"""
        timeframe = getattr(mt5, self._TF_MAP[tf_name], None)
        if timeframe is None:
            return []
        try:
            info = mt5.symbol_info(symbol)
            if info is not None and not getattr(info, "visible", True):
                mt5.symbol_select(symbol, True)
            rows = mt5.copy_rates_from_pos(symbol, timeframe, 0, count + 1)
        except Exception as exc:  # noqa: BLE001
            log.debug("足を取れません %s %s: %s", symbol, tf_name, exc)
            return []
        if rows is None or len(rows) < 2:
            return []
        bars = [
            {
                "time": int(row["time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            for row in rows
        ]
        return bars[:-1]  # 最後は形成中

    def _risk_snapshot_blocking(self, symbol: str, bars_m1: int, bars_h1: int, bars_h4: int) -> dict[str, Any] | None:
        symbol = self._pick_symbol_blocking(symbol)
        tick = mt5.symbol_info_tick(symbol) if mt5 is not None else None
        if tick is None:
            return None
        bid, ask = float(getattr(tick, "bid", 0.0)), float(getattr(tick, "ask", 0.0))
        if not bid or not ask:
            return None
        m1 = self._rates_blocking(symbol, "M1", bars_m1)
        h1 = self._rates_blocking(symbol, "H1", bars_h1)
        if not m1 or not h1:
            return None
        account = mt5.account_info()
        offset = self._server_offset_blocking()
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "m1": m1,
            "h1": h1,
            "h4": self._rates_blocking(symbol, "H4", bars_h4),
            "d1": self._rates_blocking(symbol, "D1", 60),
            "w1": self._rates_blocking(symbol, "W1", 30),
            "profile": self._profile_from_ea(),
            "account": getattr(account, "login", None) if account is not None else None,
            "bar_time": m1[-1]["time"],
            "server_time": self._server_now().strftime("%Y-%m-%dT%H:%M:%S"),
            "server_epoch": int(time.time()) + offset,
        }

    def _account_mode_blocking(self) -> str:
        account = mt5.account_info() if mt5 is not None else None
        if account is None:
            return "unknown"
        mode = getattr(account, "trade_mode", None)
        demo = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        real = getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2)
        contest = getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", 1)
        if mode == demo:
            return "demo"
        if mode == real:
            return "real"
        if mode == contest:
            return "contest"
        return "unknown"

    async def risk_snapshot(self, *, symbol: str, bars_m1: int, bars_h1: int, bars_h4: int) -> dict[str, Any] | None:
        if not self.ready:
            return None
        return await self._call(self._risk_snapshot_blocking, symbol, bars_m1, bars_h1, bars_h4)

    async def account_mode(self) -> str:
        if not self.ready:
            return "unknown"
        return await self._call(self._account_mode_blocking)

    async def last_closed_m1(self, symbol: str) -> int:
        if not self.ready:
            return 0
        bars = await self._call(self._rates_blocking, self._pick_symbol_blocking(symbol) if symbol else symbol, "M1", 2)
        return int(bars[-1]["time"]) if bars else 0

    async def symbol_tick(self, symbol: str) -> dict[str, float] | None:
        if not self.ready:
            return None

        def _tick() -> dict[str, float] | None:
            t = mt5.symbol_info_tick(self._pick_symbol_blocking(symbol))
            if t is None:
                return None
            return {"bid": float(getattr(t, "bid", 0.0)), "ask": float(getattr(t, "ask", 0.0))}

        return await self._call(_tick)

    # ---------- 時刻 ----------
    # MT5 は約定やティックの時刻を「ブローカーのサーバー時計」で持っている。
    # Python の datetime.now() をそのまま渡すと、日本時間との差のぶんだけ
    # 窓がずれて、直近の取引が丸ごと抜け落ちる（手動の売買が出てこない原因）。
    def _server_offset_blocking(self) -> int:
        """サーバー時計と UTC の差（秒）。気配値の時刻から割り出す。"""
        now = time.time()
        if self._server_offset_at and now - self._server_offset_at < 600:
            return self._server_offset

        candidates: list[str] = []
        try:
            candidates += [str(getattr(p, "symbol", "")) for p in (mt5.positions_get() or ())]
        except Exception:  # noqa: BLE001
            pass
        candidates += ["USDJPY", "EURUSD", "GBPUSD", "XAUUSD"]

        for symbol in [c for c in candidates if c]:
            try:
                info = mt5.symbol_info(symbol)
                if info is None:
                    continue
                if not getattr(info, "visible", True):
                    mt5.symbol_select(symbol, True)
                tick = mt5.symbol_info_tick(symbol)
                stamp = int(getattr(tick, "time", 0) or 0)
                if not stamp:
                    continue
                offset = stamp - int(now)
                # 週末は最後のティックが古いので、常識的な時差の範囲だけ信じる
                if abs(offset) <= 14 * 3600:
                    learned = int(round(offset / 900.0) * 900)
                    if learned != self._server_offset:
                        log.info("サーバー時計との差: %+d 分 (%s)", learned // 60, symbol)
                        _save_clock_offset(learned)
                    self._server_offset = learned
                    self._server_offset_at = now
                    return self._server_offset
            except Exception:  # noqa: BLE001
                continue

        # 分からないときは UTC とみなす（前回の値があればそれを使う）
        self._server_offset_at = now
        return self._server_offset

    def _server_now(self) -> datetime:
        """ブローカーの時計でのいま。MT5 の履歴画面と同じ時刻。"""
        return datetime.fromtimestamp(time.time() + self._server_offset_blocking(), tz=timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _server_dt(stamp: int) -> datetime:
        """約定時刻（サーバー時計）を datetime にする"""
        return datetime.fromtimestamp(int(stamp), tz=timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _closing_entries() -> tuple[int, ...]:
        """損益が確定する約定の種別。

        DEAL_ENTRY_INOUT は「決済して、その場で反対に建てる」1件（ドテン）で、
        確定した損益はこの約定に載る。ここを数えないと、その取引の損益が
        まるごと画面に出ない。EA 側（TodayClosedProfit）は最初から数えている。
        """
        return (
            getattr(mt5, "DEAL_ENTRY_OUT", 1),
            getattr(mt5, "DEAL_ENTRY_OUT_BY", 3),
            getattr(mt5, "DEAL_ENTRY_INOUT", 2),
        )

    @staticmethod
    def _trade_types() -> tuple[int, ...]:
        """売買の約定だけ。入出金・振替はここに入らない。"""
        return (getattr(mt5, "DEAL_TYPE_BUY", 0), getattr(mt5, "DEAL_TYPE_SELL", 1))

    def _deals_between(self, start: datetime, end: datetime, *, open_end: bool = False) -> list[Any]:
        """サーバー時計の [start, end] に入る約定。

        MT5 に渡す窓は前後1日ぶん広げ、絞り込みは Python 側で行う。
        こうすると、時差の扱いが環境で違っても取りこぼさない。

        open_end=True は「start から、いまこの瞬間まで」。上限で切らない。
        サーバー時計との差は気配値から割り出していて、最大15分ぶん粗く、
        しかも10分間は取り直さない。その差のぶん end が実際より前になり、
        「たったいま決済したぶんが出てこない」ことがあった。
        約定が未来に出ることはないので、上限で切る意味がない。
        """
        try:
            rows = mt5.history_deals_get(start - timedelta(days=1), end + timedelta(days=1)) or ()
        except Exception as exc:  # noqa: BLE001
            log.warning("約定履歴を読めません: %s", exc)
            return []
        out = []
        for deal in rows:
            stamp = int(getattr(deal, "time", 0) or 0)
            if not stamp:
                continue
            when = self._server_dt(stamp)
            if when < start:
                continue
            if not open_end and when > end:
                continue
            out.append(deal)
        return out

    def _entry_deals_for(self, position_id: int) -> list[Any]:
        """その建玉を「建てた」ときの約定。窓の外で建てたものを取りに行く。

        180日ぶんを見ていても、200日前に建てて昨日決済した取引は
        建てた側の約定が窓の外に落ちる。組み直せず、その取引ごと
        画面から消えていた（損益も出ない）。建玉番号で名指しに取れば拾える。
        """
        try:
            rows = mt5.history_deals_get(position=int(position_id)) or ()
        except Exception as exc:  # noqa: BLE001
            log.debug("建玉 %s の約定を読めません: %s", position_id, exc)
            return []
        entry_in = getattr(mt5, "DEAL_ENTRY_IN", 0)
        types = self._trade_types()
        return [
            d
            for d in rows
            if getattr(d, "type", None) in types and getattr(d, "entry", None) == entry_in
        ]

    def _digits_blocking(self, symbol: str, cache: dict[str, int]) -> int:
        """小数点以下の桁数。銘柄ごとに一度だけ問い合わせる。"""
        if symbol in cache:
            return cache[symbol]
        digits = 5
        try:
            info = mt5.symbol_info(symbol)
            if info is not None:
                digits = int(getattr(info, "digits", 5) or 5)
        except Exception:  # noqa: BLE001
            pass
        cache[symbol] = digits
        return digits

    def _positions_blocking(self) -> list[dict[str, Any]]:
        """いま持っている建玉。価格は MT5 が返す現在値をそのまま渡す。"""
        try:
            positions = mt5.positions_get() or ()
        except Exception as exc:  # noqa: BLE001
            log.warning("建玉を読めません: %s", exc)
            return []
        type_buy = getattr(mt5, "POSITION_TYPE_BUY", 0)
        cache: dict[str, int] = {}
        rows: list[dict[str, Any]] = []
        for pos in positions:
            symbol = str(getattr(pos, "symbol", "") or "")
            opened = int(getattr(pos, "time", 0) or 0)
            rows.append(
                {
                    "ticket": int(getattr(pos, "ticket", 0) or 0),
                    "symbol": symbol,
                    "side": "buy" if getattr(pos, "type", type_buy) == type_buy else "sell",
                    "volume": float(getattr(pos, "volume", 0) or 0),
                    "price_open": float(getattr(pos, "price_open", 0) or 0),
                    "price_current": float(getattr(pos, "price_current", 0) or 0),
                    "sl": float(getattr(pos, "sl", 0) or 0),
                    "tp": float(getattr(pos, "tp", 0) or 0),
                    "profit": round(float(getattr(pos, "profit", 0) or 0), 2),
                    "swap": round(float(getattr(pos, "swap", 0) or 0), 2),
                    "digits": self._digits_blocking(symbol, cache),
                    "opened_at": self._server_dt(opened).isoformat(timespec="minutes") if opened else "",
                }
            )
        rows.sort(key=lambda r: r["opened_at"], reverse=True)
        return rows

    def _history_stats_blocking(self, days: int = 30) -> dict[str, Any]:
        """過去 N 日の決済実績。口座の履歴をそのまま集計する。"""
        try:
            span = max(1, min(int(days), 365))
        except (TypeError, ValueError):
            span = 30
        empty: dict[str, Any] = {
            "days": span,
            "closed": 0,
            "profit": 0.0,
            "wins": 0,
            "losses": 0,
            "best": 0.0,
            "worst": 0.0,
            "gross_win": 0.0,
            "gross_loss": 0.0,
            "daily": [],
        }
        try:
            now = self._server_now()
            start = (now - timedelta(days=span - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
            deals = self._deals_between(start, now, open_end=True)
            closing = self._closing_entries()
            trade_types = self._trade_types()
            closed = 0
            profit = 0.0
            wins = 0
            losses = 0
            gross_win = 0.0
            gross_loss = 0.0
            best = 0.0
            worst = 0.0
            per_day: dict[str, dict[str, Any]] = {}
            for deal in deals:
                if getattr(deal, "type", None) not in trade_types:
                    continue
                if getattr(deal, "entry", None) not in closing:
                    continue
                p = (
                    float(getattr(deal, "profit", 0) or 0)
                    + float(getattr(deal, "swap", 0) or 0)
                    + float(getattr(deal, "commission", 0) or 0)
                )
                closed += 1
                profit += p
                if p > 0:
                    wins += 1
                    gross_win += p
                elif p < 0:
                    losses += 1
                    gross_loss += -p
                best = max(best, p)
                worst = min(worst, p)
                stamp = int(getattr(deal, "time", 0) or 0)
                key = self._server_dt(stamp).strftime("%Y-%m-%d") if stamp else start.strftime("%Y-%m-%d")
                row = per_day.setdefault(key, {"date": key, "closed": 0, "profit": 0.0})
                row["closed"] += 1
                row["profit"] += p
            daily = [
                {"date": row["date"], "closed": row["closed"], "profit": round(row["profit"], 2)}
                for row in sorted(per_day.values(), key=lambda r: r["date"])
            ]
            return {
                "days": span,
                "from": start.strftime("%Y-%m-%d"),
                "to": now.strftime("%Y-%m-%d"),
                "closed": closed,
                "profit": round(profit, 2),
                "wins": wins,
                "losses": losses,
                "best": round(best, 2),
                "worst": round(worst, 2),
                "gross_win": round(gross_win, 2),
                "gross_loss": round(gross_loss, 2),
                "daily": daily,
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("過去の実績を読めません: %s", exc)
            return empty

    def _today_stats_blocking(self) -> dict[str, Any]:
        empty = {
            "today_closed": 0,
            "today_profit": 0.0,
            "today_wins": 0,
            "today_losses": 0,
            "open_positions": 0,
            "open_profit": 0.0,
        }
        try:
            now = self._server_now()
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            deals = self._deals_between(start, now, open_end=True)
            closing = self._closing_entries()
            trade_types = self._trade_types()
            closed = 0
            profit = 0.0
            wins = 0
            losses = 0
            for deal in deals:
                if getattr(deal, "type", None) not in trade_types:
                    continue
                if getattr(deal, "entry", None) not in closing:
                    continue
                p = (
                    float(getattr(deal, "profit", 0) or 0)
                    + float(getattr(deal, "swap", 0) or 0)
                    + float(getattr(deal, "commission", 0) or 0)
                )
                closed += 1
                profit += p
                if p > 0:
                    wins += 1
                elif p < 0:
                    losses += 1
            positions = mt5.positions_get() or ()
            floating = sum(float(getattr(pos, "profit", 0) or 0) for pos in positions)
            return {
                "today_closed": closed,
                "today_profit": round(profit, 2),
                "today_wins": wins,
                "today_losses": losses,
                "open_positions": len(positions),
                "open_profit": round(floating, 2),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("本日の実績を読めません: %s", exc)
            return empty

    async def positions(self) -> list[dict[str, Any]]:
        if not self.ready:
            return []
        return await self._call(self._positions_blocking)

    async def history(self, days: int = 30) -> dict[str, Any]:
        if not self.ready:
            return {}
        return await self._call(self._history_stats_blocking, days)

    async def trades(self, days: int = 180, limit: int = 500) -> dict[str, Any]:
        if not self.ready:
            return {}
        return await self._call(self._trades_blocking, days, limit)

    async def currency(self) -> str | None:
        info = await self._call(mt5.account_info) if self.ready else None
        return getattr(info, "currency", None)

    def _trades_blocking(self, days: int = 180, limit: int = 500) -> dict[str, Any]:
        """約定履歴を「1トレード」に組み直して返す。添削のもとになるデータ。

        MT5 の履歴は約定(deal)単位なので、position_id でまとめて
        「いつ建てて、いつ決済して、いくらになったか」の形にする。
        """
        try:
            span = max(1, min(int(days), 3650))
        except (TypeError, ValueError):
            span = 180
        try:
            cap = max(1, min(int(limit), 2000))
        except (TypeError, ValueError):
            cap = 500

        now = self._server_now()
        start = (now - timedelta(days=span)).replace(hour=0, minute=0, second=0, microsecond=0)
        deals = self._deals_between(start, now, open_end=True)

        entry_in = getattr(mt5, "DEAL_ENTRY_IN", 0)
        closing = self._closing_entries()
        trade_types = self._trade_types()
        type_buy = trade_types[0]

        groups: dict[int, dict[str, Any]] = {}
        for deal in deals:
            if getattr(deal, "type", None) not in trade_types:
                continue  # 入出金・振替は取引ではない
            pid = int(getattr(deal, "position_id", 0) or 0)
            if not pid:
                continue
            g = groups.setdefault(pid, {"in": [], "out": [], "symbol": "", "magic": 0})
            g["symbol"] = g["symbol"] or str(getattr(deal, "symbol", "") or "")
            g["magic"] = g["magic"] or int(getattr(deal, "magic", 0) or 0)
            entry = getattr(deal, "entry", None)
            if entry == entry_in:
                g["in"].append(deal)
            elif entry in closing:
                g["out"].append(deal)

        def weighted(rows: list[Any]) -> tuple[float, float]:
            volume = sum(float(getattr(d, "volume", 0) or 0) for d in rows)
            if volume <= 0:
                return 0.0, 0.0
            price = sum(float(getattr(d, "price", 0) or 0) * float(getattr(d, "volume", 0) or 0) for d in rows) / volume
            return round(volume, 2), price

        cache: dict[str, int] = {}
        trades: list[dict[str, Any]] = []
        for pid, g in groups.items():
            if not g["out"]:
                continue  # まだ決済していない建玉は positions 側で見る
            if not g["in"]:
                # 窓より前に建てて、窓の中で決済した取引。建てた側の約定を名指しで取る
                g["in"] = self._entry_deals_for(pid)
                g["symbol"] = g["symbol"] or (str(getattr(g["in"][0], "symbol", "") or "") if g["in"] else "")
                if g["in"] and not g["magic"]:
                    g["magic"] = int(getattr(g["in"][0], "magic", 0) or 0)
            first_in = min(g["in"], key=lambda d: getattr(d, "time", 0)) if g["in"] else None
            last_out = max(g["out"], key=lambda d: getattr(d, "time", 0))
            opened = int(getattr(first_in, "time", 0) or 0) if first_in is not None else 0
            closed = int(getattr(last_out, "time", 0) or 0)
            if g["in"]:
                volume, open_price = weighted(g["in"])
            else:
                # それでも建てた側が分からないとき。決済ぶんだけで出す。
                # 建値と保有時間は空にするが、損益は必ず載せる（消さない）。
                volume = weighted(g["out"])[0]
                open_price = 0.0
            _, close_price = weighted(g["out"])
            profit = 0.0
            for d in (*g["in"], *g["out"]):
                profit += (
                    float(getattr(d, "profit", 0) or 0)
                    + float(getattr(d, "swap", 0) or 0)
                    + float(getattr(d, "commission", 0) or 0)
                )
            symbol = g["symbol"] or str(getattr(last_out, "symbol", "") or "")
            # 決済の向きは建玉と逆。建てた側が分からないときはここから起こす
            if first_in is not None:
                side = "buy" if getattr(first_in, "type", type_buy) == type_buy else "sell"
            else:
                side = "sell" if getattr(last_out, "type", type_buy) == type_buy else "buy"
            trades.append(
                {
                    "id": pid,
                    "symbol": symbol,
                    "side": side,
                    "volume": volume,
                    "open_price": open_price,
                    "close_price": close_price,
                    "digits": self._digits_blocking(symbol, cache),
                    "profit": round(profit, 2),
                    "opened_at": self._server_dt(opened).isoformat(timespec="minutes") if opened else "",
                    "closed_at": self._server_dt(closed).isoformat(timespec="minutes") if closed else "",
                    "held_sec": max(0, closed - opened) if opened else 0,
                    "by_system": bool(g["magic"]),
                }
            )

        trades.sort(key=lambda t: t["closed_at"], reverse=True)
        total = len(trades)
        return {
            "days": span,
            "from": start.strftime("%Y-%m-%d"),
            "to": now.strftime("%Y-%m-%d"),
            "total": total,
            "truncated": total > cap,
            "trades": trades[:cap],
        }

    async def status(self, *, include_today: bool = False, include_probe: bool = True) -> dict[str, Any]:
        info = await self._call(mt5.account_info) if self.ready else None
        term = await self._call(mt5.terminal_info) if self.ready else None
        probe = await self._call(self._ea_probe_blocking) if (self.ready and include_probe) else {}
        gate = await self._call(self._load_gate) if self.ready else {}
        today = await self._call(self._today_stats_blocking) if (self.ready and include_today) else {}
        server_now = await self._call(self._server_now) if self.ready else None
        ea = await self._call(self._ea_state_blocking) if self.ready else {}
        return {
            "version": VERSION,
            "platform": _PLATFORM,
            "gate_path": str(await self._call(self._gate_path)) if self.ready else None,
            "intent_by": self.intent_by,
            "intent_at": self.intent_at,
            "intent": self.desired_value,
            **ea,
            "server_time": server_now.isoformat(timespec="seconds") if server_now else None,
            "mt5_ready": self.ready,
            "mt5_error": (self.mt5_error or None) if not self.ready else None,
            "variable": self.cfg.gv_name,
            "value": await self.get_variable(self.cfg.gv_name),
            "desired_value": self.desired_value,
            "account": getattr(info, "login", None),
            "server": getattr(info, "server", None),
            "balance": getattr(info, "balance", None),
            "equity": getattr(info, "equity", None),
            "currency": getattr(info, "currency", None),
            "terminal_connected": getattr(term, "connected", None),
            "terminal_trade_allowed": getattr(term, "trade_allowed", None),
            "build": getattr(term, "build", None),
            "terminal_name": getattr(term, "name", None),
            "gate": gate,
            "today": today,
            **probe,
        }


# ============================================================
# 再接続の待ち時間（指数バックオフ + ゆらぎ）
# ============================================================
class Backoff:
    def __init__(self, minimum: float, maximum: float) -> None:
        self.minimum = minimum
        self.maximum = maximum
        self._current = minimum

    def next(self) -> float:
        delay = min(self._current, self.maximum)
        self._current = min(self._current * 2, self.maximum)
        # 同時再接続が重ならないよう ±20% ゆらす
        return max(0.5, delay * random.uniform(0.8, 1.2))

    def reset(self) -> None:
        self._current = self.minimum


async def _sleep_or_stop(seconds: float, stop: asyncio.Event) -> None:
    """停止要求が来たら待ち時間を切り上げる sleep"""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


# ============================================================
# 指令の処理
# ============================================================
class CommandRouter:
    def __init__(self, cfg: Config, mt: MT5Controller) -> None:
        self.cfg = cfg
        self.mt = mt
        self.risk: Any | None = None

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command", "")).strip().lower()
        request_id = payload.get("id")

        if command == "stop_trading":
            reason = payload.get("reason", "")
            log.warning("指令: 売買停止  理由=%s", reason or "(指定なし)")
            ok, readback = await self.mt.set_trading(False)
            return self._ack(command, request_id, ok, value=readback)

        if command == "start_trading":
            log.info("指令: 売買再開")
            ok, readback = await self.mt.set_trading(True)
            return self._ack(command, request_id, ok, value=readback)

        if command in ("close_all", "stop_system"):
            # 一斉制御。
            #   close_all   … 全決済だけ（新規は止めない。EA は続けて入ることがある）
            #   stop_system … 新規を止めてから全決済（口座を空にして止める）
            reason = payload.get("reason", "")
            ok, readback = True, None
            if command == "stop_system":
                log.warning("指令: システム停止（新規停止＋全決済）  理由=%s", reason or "(指定なし)")
                # 先に止める。閉じた直後に EA が建て直すのを防ぐ
                ok, readback = await self.mt.set_trading(False)
            else:
                log.warning("指令: 全決済  理由=%s", reason or "(指定なし)")
            result = await self.mt.close_all()
            failed = result.get("failed") or []
            extra: dict[str, Any] = {
                "closed": result.get("closed", 0),
                "removed": result.get("removed", 0),
                "failed": failed,
                "error": result.get("error") or (f"{len(failed)} 件を閉じられませんでした" if failed else None),
            }
            if command == "stop_system":
                extra["value"] = readback  # 売買フラグの読み返し（全決済だけのときは混ぜない）
            return self._ack(command, request_id, ok and not failed and not result.get("error"), **extra)

        if command == "set_variable":
            name = str(payload.get("name", "")).strip()
            if not name:
                return self._ack(command, request_id, False, error="name が空です")
            # 書き換えてよい変数と、その値の範囲は、このお客様のPCの側でも必ず確かめる。
            # 画面（eaSettings.ts）にしか制限が無いと、中継に直接つないだ誰かが
            # ロット 100 のような値を書き込めてしまう。
            limits = ALLOWED_VARIABLES.get(name)
            if limits is None:
                log.warning("知らない変数への書き込みを断りました: %r", name[:40])
                return self._ack(command, request_id, False, error=f"{name} は変更できません")
            try:
                value = float(payload.get("value"))
            except (TypeError, ValueError):
                return self._ack(command, request_id, False, error="value が数値ではありません")
            if not (value == value and abs(value) != float("inf")):  # NaN / inf を弾く
                return self._ack(command, request_id, False, error="value が数値ではありません")
            low, high = limits
            if not (low <= value <= high):
                log.warning("範囲外の値を断りました: %s=%s（%s〜%s）", name, value, low, high)
                return self._ack(command, request_id, False, error=f"{name} は {low}〜{high} の範囲で指定してください")
            log.info("指令: グローバル変数 %s = %s", name, value)
            ok, readback = await self.mt.set_variable(name, value)
            if ok and name == self.cfg.gv_name:
                self.mt.desired_value = value
            return self._ack(command, request_id, ok, value=readback, name=name)

        if command in ("get_positions", "positions"):
            if not self.mt.ready:
                return self._ack(command, request_id, False, error="MT5に接続していません", positions=[])
            rows = await self.mt.positions()
            floating = round(sum(float(r.get("profit", 0) or 0) for r in rows), 2)
            log.debug("指令: 建玉要求 -> %d件", len(rows))
            return self._ack(
                command,
                request_id,
                True,
                positions=rows,
                open_positions=len(rows),
                open_profit=floating,
                currency=await self.mt.currency(),
            )

        if command in ("get_history", "history"):
            if not self.mt.ready:
                return self._ack(command, request_id, False, error="MT5に接続していません")
            days = payload.get("days", 30)
            stats = await self.mt.history(days)
            log.debug("指令: 過去実績要求 days=%s -> %s件", days, stats.get("closed"))
            return self._ack(command, request_id, True, history=stats, currency=await self.mt.currency())

        if command in ("get_trades", "trades"):
            if not self.mt.ready:
                return self._ack(command, request_id, False, error="MT5に接続していません")
            data = await self.mt.trades(payload.get("days", 180), payload.get("limit", 500))
            log.debug("指令: 履歴要求 days=%s -> %s件", payload.get("days"), data.get("total"))
            return self._ack(command, request_id, True, trades=data, currency=await self.mt.currency())

        if command in ("get_status", "status"):
            status = await self.mt.status(include_today=True)
            log.debug("指令: 状態要求 -> %s", status)
            return self._ack(command, request_id, True, **status)

        if command == "ping":
            return self._ack(command, request_id, True, pong=True)

        log.warning("未知の指令を受信しました: %r", command or payload)
        return self._ack(command or "(empty)", request_id, False, error="未知の指令です")

    def _ack(self, command: str, request_id: Any, ok: bool, **extra: Any) -> dict[str, Any]:
        msg = {
            "type": "ack",
            "bridge_id": self.cfg.bridge_id,
            "command": command,
            "ok": ok,
            "ts": time.time(),
        }
        if request_id is not None:
            msg["id"] = request_id
        msg.update(extra)
        return msg


# ============================================================
# 本体ループ
# ============================================================
class Bridge:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.mt = MT5Controller(cfg)
        self.router = CommandRouter(cfg, self.mt)
        self.stop = asyncio.Event()
        # 送信は3か所から同時に走る（指令への返事・5秒ごとの送信・30秒ごとの見張り）。
        # WebSocket の送信は同時に呼べないので、ここで順番に通す。
        # 重なると送信が例外になり、指令の返事を送っている側で起きたときは
        # そのまま接続が切れて、再接続からやり直しになっていた。
        self._send_lock = asyncio.Lock()
        self.connected_since: float | None = None
        self.disconnected_since: float = time.time()
        self._failsafe_fired = False
        self._active_ws: Any | None = None
        self._status_key: str = ""
        # いま画面が何枚開いているか（中継が教えてくれる）。
        # 0 のあいだは口座の数字を送らない。
        self.watchers: int = 0
        # AIリスク監督（AI による新規注文の見張り）は 2026-10-14 に廃止した。動かさない
        self.risk: Any | None = None

    # ---------- WebSocket ----------
    def _connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "ping_interval": self.cfg.ping_interval,
            "ping_timeout": self.cfg.ping_timeout,
            "open_timeout": self.cfg.open_timeout,
            "close_timeout": 5,
            "max_queue": 32,
        }
        headers = {"X-Bridge-Id": self.cfg.bridge_id}
        if self.cfg.token:
            headers["Authorization"] = f"Bearer {self.cfg.token}"
        kwargs[_HEADER_KW] = headers
        return kwargs

    async def _send(self, ws: Any, message: dict[str, Any]) -> None:
        body = json.dumps(message, ensure_ascii=False, allow_nan=False, default=str)
        async with self._send_lock:
            await ws.send(body)

    def _with_risk(self, status: dict[str, Any]) -> dict[str, Any]:
        """AIリスク監督は廃止したので、画面へ送る内容はそのまま。"""
        return status

    async def _on_connected(self, ws: Any) -> None:
        self.connected_since = time.time()
        self._failsafe_fired = False
        self._active_ws = ws
        # サイトとつながった合図を、見張り（30 秒後）を待たずに EA へ書く → パネルが「連携済み」になる
        await self.mt.touch_gate()
        status = self._with_risk(await self.mt.status(include_today=True))
        self._status_key = self._status_fingerprint(status)
        await self._send(
            ws,
            {
                "type": "hello",
                "bridge_id": self.cfg.bridge_id,
                "version": 1,
                "ts": time.time(),
                **status,
            },
        )
        log.info("トレラボに接続しました: %s", self.cfg.ws_url)

    @staticmethod
    def _status_fingerprint(status: dict[str, Any]) -> str:
        """画面に出る数字が動いたかどうかの目印"""
        today = status.get("today") or {}
        return "|".join(
            str(x)
            for x in (
                status.get("account"),
                status.get("server"),
                status.get("value"),
                status.get("balance"),
                status.get("equity"),
                today.get("today_closed"),
                today.get("today_profit"),
                today.get("open_positions"),
                today.get("open_profit"),
                # MT5 側の準備（チャートに載ったか・自動売買ボタンが押されたか）。
                # 初期設定でユイがここを見て、次の案内に進む。
                status.get("ea_alive"),
                status.get("ea_state"),
                status.get("terminal_trade_allowed"),
                status.get("terminal_connected"),
            )
        )

    async def _push_status_if_changed(self, *, force: bool = False) -> None:
        """口座の数字が動いたら画面へ送り直す。

        建玉や損益は、こちらから送らないと画面が古いままになる。
        手動の売買もここで拾われる（EA かどうかは関係ない）。
        """
        ws = self._active_ws
        if ws is None or not self.mt.ready:
            return
        status = self._with_risk(await self.mt.status(include_today=True, include_probe=False))
        # 画面が開いている間は、ズレを見つけたらその場で直す（見張りの30秒を待たない）
        value = status.get("value")
        if value is None or float(value) != float(self.mt.desired_value):
            log.warning(
                "MT5 側が指示と違います（MT5=%s / 指示=%s）。すぐ合わせ直します",
                value,
                self.mt.desired_value,
            )
            await self.mt.set_variable(self.cfg.gv_name, self.mt.desired_value)
            status["value"] = self.mt.desired_value
        status["positions"] = await self.mt.positions()
        key = self._status_fingerprint(status)
        if key == self._status_key and not force:
            return
        account_changed = self._status_key.split("|")[:2] != key.split("|")[:2]
        self._status_key = key
        if account_changed:
            log.info("MT5 口座が切り替わりました: %s / %s", status.get("account"), status.get("server"))
        await self._send(
            ws,
            {
                "type": "status_update",
                "bridge_id": self.cfg.bridge_id,
                "ts": time.time(),
                **status,
            },
        )

    async def _serve_connection(self, ws: Any) -> None:
        """このコネクションが切れるまで指令を待ち続ける。await中はCPUを使わない。"""
        await self._on_connected(ws)
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("JSONとして読めない受信データを無視します: %.120s", raw)
                    continue
                if not isinstance(payload, dict):
                    log.warning("辞書ではない受信データを無視します: %.120s", raw)
                    continue

                # 指令ではなく、中継からの知らせ（画面が何枚開いているか）
                if payload.get("type") == "apps":
                    before = self.watchers
                    try:
                        self.watchers = int(payload.get("count", 0))
                    except (TypeError, ValueError):
                        self.watchers = 0
                    log.debug("画面の枚数: %s", self.watchers)
                    # 開かれた瞬間は、待たずにいまの数字を送る
                    if before <= 0 and self.watchers > 0:
                        await self._push_status_if_changed(force=True)
                    continue

                try:
                    ack = await self.router.handle(payload)
                except Exception as exc:  # noqa: BLE001 - 1件の失敗で常駐を止めない
                    log.exception("指令の処理中に例外が発生しました: %s", exc)
                    ack = {
                        "type": "ack",
                        "bridge_id": self.cfg.bridge_id,
                        "command": payload.get("command"),
                        "ok": False,
                        "error": str(exc),
                        "ts": time.time(),
                    }
                await self._send(ws, ack)
        finally:
            if self._active_ws is ws:
                self._active_ws = None
            self.watchers = 0

    async def ws_loop(self) -> None:
        backoff = Backoff(self.cfg.reconnect_min, self.cfg.reconnect_max)
        while not self.stop.is_set():
            try:
                async with ws_connect(self.cfg.ws_url, **self._connect_kwargs()) as ws:
                    backoff.reset()
                    started = time.time()
                    await self._serve_connection(ws)
                    if getattr(ws, "close_code", None) == 4001:
                        log.warning("別の接続ツールが接続したため、このブリッジは終了します")
                        self.request_stop()
                        break
                    if getattr(ws, "close_code", None) == 4002:
                        log.warning(
                            "この会員には別の MT5 がすでにつながっています。%d 秒待ってから、もう一度だけ確かめます",
                            BUSY_WAIT_SEC,
                        )
                        await _sleep_or_stop(BUSY_WAIT_SEC, self.stop)
                        continue
                    if getattr(ws, "close_code", None) == 4003:
                        log.error("この会員は利用を止められています。ブリッジを終了します")
                        _hand_over_to_link_waiter()
                        self.request_stop()
                        break
                    # 切れた理由が後から分かるように、必ず番号と理由を残す。
                    # 1000/1001=中継からの正常な終了（再起動・入れ替え）、
                    # 1006=返事が無くなった（回線・PCのスリープ・中継の落ち）。
                    log.warning(
                        "サーバーから切断されました code=%s reason=%r 接続していた時間=%.0f秒",
                        getattr(ws, "close_code", None),
                        getattr(ws, "close_reason", ""),
                        time.time() - started,
                    )
            except asyncio.CancelledError:
                raise
            except (WebSocketException, OSError) as exc:
                code = getattr(exc, "code", None)
                if code is None:
                    code = getattr(getattr(exc, "rcvd", None), "code", None)
                if code == 4001:
                    log.warning("別の接続ツールが接続したため、このブリッジは終了します")
                    self.request_stop()
                    break
                if code == 4002:
                    log.warning(
                        "この会員には別の MT5 がすでにつながっています。%d 秒待ってから、もう一度だけ確かめます",
                        BUSY_WAIT_SEC,
                    )
                    await _sleep_or_stop(BUSY_WAIT_SEC, self.stop)
                    continue
                if code == 4003:
                    log.error("この会員は利用を止められています。ブリッジを終了します")
                    _hand_over_to_link_waiter()
                    self.request_stop()
                    break
                # 中継は、止めた会員のブリッジを最初の 1 回だけ 4003 で閉じ、そのあと 1 時間は HTTP 403 で
                # 黙って断る。403 を「つながらない」と読んで叩き直し続けると、会員が消えたことに
                # 気づけず、ロビーで登録し直しても紐づき直らない（実機で起きた）。403 も同じ扱いにする
                if "403" in str(exc):
                    log.error("中継に断られています（会員が消えた・止められた）。ブリッジを終了します")
                    _hand_over_to_link_waiter()
                    self.request_stop()
                    break
                log.warning("中継サーバーに接続できません (%s): %s", type(exc).__name__, exc)
                log.warning("→ server フォルダで npm start が動いているか確認（ポート 8080）")
            except Exception as exc:  # noqa: BLE001
                log.exception("想定外の例外: %s", exc)

            # 切断の起点は「つながっていた状態を失った瞬間」だけ更新する。
            # 再試行のたびに上書きすると、デッドマンスイッチが永久に発火しない。
            if self.connected_since is not None:
                self.disconnected_since = time.time()
                self.connected_since = None
            if self.stop.is_set():
                break
            delay = backoff.next()
            log.info("%.1f 秒後に再接続します", delay)
            await _sleep_or_stop(delay, self.stop)

    # ---------- 見張り ----------
    async def status_pusher(self) -> None:
        """口座の数字が動いていないか、数秒おきに見て、動いていたら画面へ送る。

        画面から聞かれるのを待たずに送るので、手動でエントリー／決済しても
        そのまま反映される。
        誰も画面を開いていない間は何もしない（お客様のPCも通信も使わない）。
        """
        interval = max(1.0, self.cfg.push_interval)
        while not self.stop.is_set():
            await _sleep_or_stop(interval, self.stop)
            if self.stop.is_set():
                break
            if self.watchers <= 0:
                continue
            try:
                await self._push_status_if_changed()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.debug("状態の送信で例外: %s", exc)

    async def _poll_other_claims(self) -> None:
        """同じ PC にある、自分以外の口座の MT5 あてに預けられた合図を取りに行く（exe 版だけ）。"""
        if not getattr(sys, "frozen", False) or os.name != "nt":
            return
        try:
            import mt5_detect  # 同梱

            mine = self.mt._login()
            accounts: list[str] = []
            for t in mt5_detect.list_terminals():
                m = re.search(r"口座\s*(\d+)", str(getattr(t, "label", "") or ""))
                if m and m.group(1) not in accounts:
                    accounts.append(m.group(1))
            if mine and mine not in accounts:
                accounts.append(mine)
            if not accounts:
                return
            origin = re.sub(r"^wss?://", lambda m: "https://" if m.group(0) == "wss://" else "http://", self.cfg.ws_url)
            origin = re.sub(r"/bridge.*$", "", origin)
            for acct in accounts:
                try:
                    with urllib.request.urlopen(f"{origin}/claim?account={acct}", timeout=6) as res:
                        data = json.loads(res.read().decode("utf-8", errors="replace"))
                except Exception:  # noqa: BLE001
                    continue
                token = str(data.get("token") or "") if isinstance(data, dict) and data.get("ok") else ""
                if re.fullmatch(r"[0-9a-fA-F]{64}", token):
                    slot = data.get("slot") if isinstance(data, dict) else None
                    extra = f"&slot={slot}" if str(slot) in ("1", "2") else ""
                    log.info("口座（…%s）あての合図を受け取りました。接続ツールに連携させます", acct[-4:])
                    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                    subprocess.Popen(
                        [sys.executable, f"aitrader://connect?token={token}&account={acct}{extra}"],
                        creationflags=flags,
                        close_fds=True,
                    )
        except Exception as exc:  # noqa: BLE001
            log.debug("追加口座の合図の確認で例外: %s", exc)

    async def watchdog(self) -> None:
        """
        定期的に
          1. MT5が生きているか（落ちていたら再初期化）
          2. 売買フラグが指示どおりか（ズレていたら書き戻す）
          3. 切断が長引いていないか（デッドマンスイッチ）
        を確認する。間隔は30秒程度なので負荷は無視できる。
        """
        while not self.stop.is_set():
            await _sleep_or_stop(self.cfg.watchdog_interval, self.stop)
            if self.stop.is_set():
                break
            try:
                boot = getattr(self, "_mt5_boot", None)
                if boot is not None and not boot.done():
                    continue   # 起動直後の MT5 接続はまだ進行中。二重に初期化しない
                term = await self.mt._call(mt5.terminal_info) if self.mt.ready else None
                if term is None:
                    log.error("MT5 との接続が失われました。再初期化します")
                    self.mt.ready = False
                    await self.mt.connect_with_retry(self.stop)
                    if self.mt.ready:
                        # 再接続後も、記録してある指示に合わせるだけ
                        await self.mt.adopt_current_state()
                    continue

                # 1 本目だけ：同じ PC の別の MT5（追加口座）あてにサイトが預けた合図を取りに行く。
                # 来ていれば接続ツールを token 付きで起こし、その口座専用のブリッジを立てさせる
                if not SLOT and self._active_ws is not None:
                    await self._poll_other_claims()

                # 30 秒ごとの合図（EA のパネルが「ユメックAIと連携済み／未接続」を出す材料）。
                # サイト（中継）とつながっているときだけ書く。中継に断られている・届いていないのに
                # 「連携済み」と出すと、一斉制御もロビーも効かないのに正常に見えてしまう（実機で起きた）
                if self._active_ws is not None:
                    await self.mt.touch_gate()

                if self.cfg.reassert:
                    # サイトでの指示だけが正。MT5 側がそれと違っていたら、
                    # 誰が書き換えたのであれ指示どおりに戻す（＝画面と必ず一致する）。
                    current = await self.mt.get_variable(self.cfg.gv_name)
                    if current is None or float(current) != float(self.mt.desired_value):
                        log.warning(
                            "MT5 側が指示と違います（MT5=%s / 指示=%s。指示したのは %s %s）。合わせ直します",
                            current,
                            self.mt.desired_value,
                            self.mt.intent_at or "不明",
                            self.mt.intent_by or "不明",
                        )
                        await self.mt.set_variable(self.cfg.gv_name, self.mt.desired_value)

                await self._push_status_if_changed()

                if self.cfg.failsafe_sec > 0 and self.connected_since is None and not self._failsafe_fired:
                    offline = time.time() - self.disconnected_since
                    if offline >= self.cfg.failsafe_sec:
                        log.error(
                            "サーバーと %.0f 秒つながりません。安全のため売買を停止します（デッドマンスイッチ）",
                            offline,
                        )
                        await self.mt.set_trading(False, by="安全装置（サーバーと切断）")
                        self._failsafe_fired = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("見張り処理で例外: %s", exc)

    # ---------- 起動 ----------
    async def run(self) -> None:
        log.info("=" * 62)
        log.info("トレラボ MT5 ブリッジ起動  bridge_id=%s  版=%s", self.cfg.bridge_id, VERSION)
        log.info("接続先        : %s", self.cfg.ws_url)
        log.info("制御する変数  : %s (初期値 %s)", self.cfg.gv_name, self.cfg.gv_default)
        if self.cfg.failsafe_sec > 0:
            log.info("デッドマンSW  : %.0f 秒切断で自動停止", self.cfg.failsafe_sec)
        log.info("=" * 62)

        # MT5 につながるのを待たずに、先に中継へ名乗る。
        # 以前は MT5 につながるまで中継に出なかったので、MT5 側でこけると
        # サイトからは「パスポートが来ない」としか見えず、理由が分からなかった（実機で起きた）。
        # いまは中継に出て mt5_ready=false と理由（mt5_error）を報告し、MT5 は裏で待つ。
        async def bring_up_mt5() -> None:
            await self.mt.connect_with_retry(self.stop)
            if self.stop.is_set() or not self.mt.ready:
                return
            # 起動直後は、MT5 側にある値をそのまま引き継ぐ。
            # 勝手に稼働中へ戻さないための要。記録が無いときだけ初期値を書く。
            try:
                restored = await self.mt.restore_settings()
                if restored:
                    log.warning("指令ファイルから消えていた設定を書き戻しました: %s", "、".join(restored))
            except Exception as exc:  # noqa: BLE001
                log.warning("設定の書き戻しに失敗しました: %s", exc)
            try:
                await self.mt.adopt_current_state()
            except Exception as exc:  # noqa: BLE001
                log.exception("起動時の状態引き継ぎに失敗しました（中継への接続は続けます）: %s", exc)
            if self._active_ws is not None:
                await self.mt.touch_gate()
                try:
                    await self._push_status_if_changed(force=True)
                except Exception as exc:  # noqa: BLE001
                    log.debug("MT5 につながった直後の状態送信で例外: %s", exc)

        self._mt5_boot = asyncio.create_task(bring_up_mt5(), name="mt5")
        watchdog = asyncio.create_task(self.watchdog(), name="watchdog")
        pusher = asyncio.create_task(self.status_pusher(), name="pusher")
        tasks = [self._mt5_boot, watchdog, pusher]
        try:
            await self.ws_loop()
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            await self.mt.shutdown()
            log.info("ブリッジを終了しました")

    def request_stop(self) -> None:
        if not self.stop.is_set():
            log.info("終了要求を受け取りました。片付けます…")
            self.stop.set()


# ============================================================
# エントリポイント
# ============================================================
async def _amain(cfg: Config) -> int:
    bridge = Bridge(cfg)
    loop = asyncio.get_running_loop()

    # WindowsのProactorLoopは add_signal_handler 未対応なので try で包む
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bridge.request_stop)
        except (NotImplementedError, AttributeError, ValueError):
            pass

    try:
        await bridge.run()
    except KeyboardInterrupt:
        bridge.request_stop()
    return 0


async def _acheck(cfg: Config) -> int:
    """MT5への接続確認だけ行う（VPSの初期設定用）"""
    mt = MT5Controller(cfg)
    if not await mt.connect():
        log.error("MT5 に接続できませんでした")
        return 1
    status = await mt.status(include_today=True)
    log.info("現在の状態: %s", json.dumps(status, ensure_ascii=False, indent=2, default=str))
    await mt.shutdown()
    return 0


def _use_bundled_certs() -> None:
    """同梱した certifi の証明書を使う。古い Windows Server はルート証明書が古く、中継（wss）につなげない。"""
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
        os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    except ImportError:
        pass


def main() -> int:
    _use_bundled_certs()
    parser = argparse.ArgumentParser(description="トレラボ MT5 ブリッジ")
    parser.add_argument("--check", action="store_true", help="MT5への接続と現在値を確認して終了する")
    # 追加口座の目印（口座番号）。値そのものは環境変数 BRIDGE_SLOT で受け取る。
    # 命令行に残しておくのは、プロセス一覧で「どの枠のブリッジか」を見分けるため
    parser.add_argument("--slot", default="", help="追加口座の口座番号（目印）")
    args = parser.parse_args()

    cfg = Config()
    setup_logging(cfg)

    if mt5 is None:
        log.error("MetaTrader5 パッケージを読み込めません。Windows + 64bit Python で実行してください")
        return 1

    if not args.check:
        acquire_instance_lock()

    runner = _acheck(cfg) if args.check else _amain(cfg)
    try:
        return asyncio.run(runner)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
