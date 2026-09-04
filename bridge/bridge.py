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
    from mt5_terminal import find_logged_in_terminal, resolve_terminal_exe
except ImportError:
    find_logged_in_terminal = None  # type: ignore[assignment,misc]
    resolve_terminal_exe = None  # type: ignore[assignment,misc]


log = logging.getLogger("bridge")
_LOCK_FH = None

# どの版のブリッジが動いているかを画面とログで確認できるようにする。
# 「直したのに直っていない」ときは、たいてい古いブリッジが残っている。
VERSION = "2026-09-04.1"


# 以前の版が使っていたロック名。名前が変わったせいで、
# 古いブリッジと新しいブリッジが同時に動けてしまっていた。
LOCK_NAMES = ("aitrader-bridge.lock", "trelab-bridge.lock")
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
    return "python" in image or image == Path(sys.executable).name.lower()


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
    if os.name == "nt":
        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -and "
            "($_.CommandLine -like '*bridge.py*' -or $_.CommandLine -like '*--run-bridge*') } | "
            "ForEach-Object { \"$($_.ProcessId)|$($_.Name)\" }"
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
        pid_s, image = line.strip().split("|", 1)
        if not pid_s.isdigit():
            continue
        pid = int(pid_s)
        image = image.lower()
        if pid == me:
            continue
        if "python" in image or image == own_exe:
            pids.append(pid)
    return pids


def takeover_old_bridges() -> None:
    """自分より古い版のブリッジが残っていたら終わらせる。

    二重に動くと、両方が売買フラグを書きにいって取り合いになる。
    「触っていないのに稼働中と停止中が入れ替わる」のはこれが原因だった。
    """
    me = os.getpid()
    same_version: set[int] = set()
    targets: dict[int, str] = {}
    for name in LOCK_NAMES:
        path = _lock_dir() / name
        if not path.is_file():
            continue
        pid, version = _read_lock(path)
        if pid is None or pid == me:
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
    path = _lock_dir() / LOCK_NAMES[0]
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
    ping_timeout: float = field(default_factory=lambda: _env_float("PING_TIMEOUT_SEC", 20.0))
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
class MT5Controller:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")
        self._lock = asyncio.Lock()
        self.ready = False
        # 「サーバーから最後に指示された状態」。再接続や再起動のあとで復元する。
        # 起動時は adopt_current_state() で MT5 側の実際の値を引き継ぐので、
        # ここでの初期値は「MT5 側にも記録が無かったとき」だけ使われる。
        self.desired_value: float = cfg.gv_default
        # ブローカーのサーバー時刻と UTC の差（秒）。履歴の日付はこれで判断する
        self._server_offset: int = 0
        self._server_offset_at: float = 0.0
        # 気配値ウィンドウの銘柄（並べ替え済み）と、それを読んだ時刻
        self._market_symbols_cache: list[str] = []
        self._market_symbols_at: float = 0.0

    async def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """ブロッキングなMT5呼び出しを専用スレッドで実行する"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, functools.partial(fn, *args, **kwargs))

    # ---------- 初期化 ----------
    def _initialize_blocking(self) -> bool:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 パッケージが見つかりません（Windows + 64bit Python が必要です）")

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
            return False
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
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
        folder = Path(base) / "AITrader"
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

    def _gate_path(self) -> Path:
        term = mt5.terminal_info() if mt5 is not None else None
        common = getattr(term, "commondata_path", None) if term is not None else None
        if not common:
            common = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", "Common")
        folder = Path(str(common)) / "Files"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / self.GATE_FILE

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
        body = "".join(f"{k}={v}\n" for k, v in sorted(values.items()))
        tmp = path.with_suffix(".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
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

    STATE_FILE = "trelab_state.ini"

    def _ea_state_blocking(self) -> dict[str, Any]:
        """MT5 のチャートに出ている状態（EA が書き出したもの）。

        サイトの表示と突き合わせるために読む。ここが食い違っていたら、
        EA とブリッジが別のフォルダを見ている（または EA が止まっている）。
        """
        path = self._gate_path().with_name(self.STATE_FILE)
        out: dict[str, Any] = {}
        try:
            if not path.is_file():
                return {"ea_state": None}
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" not in line:
                    continue
                key, raw = line.split("=", 1)
                out[key.strip()] = raw.strip()
            age = time.time() - path.stat().st_mtime
        except OSError:
            return {"ea_state": None}
        return {
            "ea_state": out.get("state"),
            "ea_allowed": out.get("allowed"),
            "ea_state_at": out.get("at"),
            "ea_name": out.get("ea"),
            # EA は10秒ごとに書く。30秒以上古ければ、チャートから外れている
            "ea_alive": age < 30,
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
        for name in ("SiteTestEA",):
            if (experts / f"{name}.mq5").is_file():
                found.append(name)
            if (experts / f"{name}.ex5").is_file():
                compiled.append(name)
                if name not in found:
                    found.append(name)
        return {
            "ea_folder": str(experts),
            "ea_found": found,
            "ea_compiled": compiled,
            "ea_installed": len(found) > 0,
        }

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
                    self._server_offset = int(round(offset / 900.0) * 900)
                    self._server_offset_at = now
                    log.debug("サーバー時計との差: %+d 分 (%s)", self._server_offset // 60, symbol)
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

    def _deals_between(self, start: datetime, end: datetime) -> list[Any]:
        """サーバー時計の [start, end] に入る約定。

        MT5 に渡す窓は前後1日ぶん広げ、絞り込みは Python 側で行う。
        こうすると、時差の扱いが環境で違っても取りこぼさない。
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
            if start <= when <= end:
                out.append(deal)
        return out

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
            deals = self._deals_between(start, now)
            entry_out = getattr(mt5, "DEAL_ENTRY_OUT", 1)
            entry_out_by = getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)
            type_buy = getattr(mt5, "DEAL_TYPE_BUY", 0)
            type_sell = getattr(mt5, "DEAL_TYPE_SELL", 1)
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
                if getattr(deal, "type", None) not in (type_buy, type_sell):
                    continue
                if getattr(deal, "entry", None) not in (entry_out, entry_out_by):
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
            deals = self._deals_between(start, now)
            entry_out = getattr(mt5, "DEAL_ENTRY_OUT", 1)
            entry_out_by = getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)
            type_buy = getattr(mt5, "DEAL_TYPE_BUY", 0)
            type_sell = getattr(mt5, "DEAL_TYPE_SELL", 1)
            closed = 0
            profit = 0.0
            wins = 0
            losses = 0
            for deal in deals:
                if getattr(deal, "type", None) not in (type_buy, type_sell):
                    continue
                if getattr(deal, "entry", None) not in (entry_out, entry_out_by):
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

    # ---------- 相場（気配値・ローソク足） ----------
    # 画面のチャートとティッカーは、連携中はここから取る。
    # 出すのは MT5 の「気配値」ウィンドウにある銘柄だけで、順番は
    # よく見る通貨ペアを先にし、あとは気配値の並びどおり。
    MARKET_PREFERRED = (
        "USDJPY", "XAUUSD", "GOLD", "EURUSD", "EURJPY", "GBPUSD", "GBPJPY",
        "AUDJPY", "AUDUSD", "USDCHF", "NZDUSD", "BTCUSD", "US30", "NAS100", "JP225",
    )

    def _market_symbols_blocking(self) -> list[str]:
        # 銘柄一覧は業者によっては数千件あるので、1分に1回だけ読み直す
        now = time.time()
        if self._market_symbols_cache and now - self._market_symbols_at < 60:
            return self._market_symbols_cache
        ranked = self._market_symbols_scan()
        if ranked:
            self._market_symbols_cache = ranked
            self._market_symbols_at = now
        return ranked

    def _market_symbols_scan(self) -> list[str]:
        try:
            rows = mt5.symbols_get() or ()
        except Exception as exc:  # noqa: BLE001
            log.warning("銘柄一覧を読めません: %s", exc)
            return []
        visible = [getattr(r, "name", "") for r in rows if getattr(r, "visible", False)]
        visible = [v for v in visible if v]

        def base(name: str) -> str:
            # "USDJPY.m" / "USDJPYm" / "USDJPY-raw" などの業者ごとの飾りを落とす
            head = name.split(".")[0].split("-")[0].split("_")[0].upper()
            return head[:6] if len(head) > 6 and head[:6].isalpha() else head

        ranked: list[str] = []
        for want in self.MARKET_PREFERRED:
            for name in visible:
                if name in ranked:
                    continue
                if base(name) == want:
                    ranked.append(name)
                    break
        ranked += [n for n in visible if n not in ranked]
        return ranked

    def _rates(self, symbol: str, timeframe: int, count: int) -> list[Any]:
        try:
            rows = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        except Exception as exc:  # noqa: BLE001
            log.debug("ローソク足を読めません %s: %s", symbol, exc)
            return []
        return list(rows) if rows is not None else []

    def _market_blocking(self, chart_symbol: str | None, interval: str, count: int) -> dict[str, Any]:
        symbols = self._market_symbols_blocking()
        offset = self._server_offset_blocking()
        tf_map = {
            "5m": getattr(mt5, "TIMEFRAME_M5", 5),
            "15m": getattr(mt5, "TIMEFRAME_M15", 15),
            "1h": getattr(mt5, "TIMEFRAME_H1", 16385),
        }
        if interval not in tf_map:
            interval = "15m"
        tf_d1 = getattr(mt5, "TIMEFRAME_D1", 16408)

        quotes: list[dict[str, Any]] = []
        for name in symbols[:12]:
            try:
                info = mt5.symbol_info(name)
                tick = mt5.symbol_info_tick(name)
            except Exception:  # noqa: BLE001
                continue
            if info is None or tick is None:
                continue
            price = float(getattr(tick, "bid", 0) or 0)
            if price <= 0:
                continue
            days = self._rates(name, tf_d1, 2)
            # 前日の終値。今日の足しか無ければ、その始値で代用する
            prev = float(days[-2]["close"]) if len(days) >= 2 else (float(days[-1]["open"]) if days else price)
            quotes.append(
                {
                    "symbol": name,
                    "price": price,
                    "prevClose": prev,
                    "changePct": ((price - prev) / prev * 100.0) if prev else 0.0,
                    "digits": int(getattr(info, "digits", 2) or 2),
                    "at": int(time.time()),
                }
            )

        chart: dict[str, Any] | None = None
        target = chart_symbol if chart_symbol in symbols else (symbols[0] if symbols else None)
        if target:
            info = mt5.symbol_info(target)
            rows = self._rates(target, tf_map[interval], max(20, min(int(count), 300)))
            days = self._rates(target, tf_d1, 2)
            tick = mt5.symbol_info_tick(target)
            price = float(getattr(tick, "bid", 0) or 0) if tick else 0.0
            if rows:
                if price <= 0:
                    price = float(rows[-1]["close"])
                prev = float(days[-2]["close"]) if len(days) >= 2 else float(rows[0]["open"])
                chart = {
                    "symbol": target,
                    "interval": interval,
                    "digits": int(getattr(info, "digits", 2) or 2) if info else 2,
                    "price": price,
                    "prevClose": prev,
                    # 足の時刻はサーバー時計なので、UTC に直してから渡す（画面は日本時間で出す）
                    "candles": [
                        {
                            "t": int(r["time"]) - offset,
                            "o": float(r["open"]),
                            "h": float(r["high"]),
                            "l": float(r["low"]),
                            "c": float(r["close"]),
                        }
                        for r in rows
                    ],
                }
        return {"symbols": symbols[:12], "quotes": quotes, "chart": chart}

    async def market(self, chart_symbol: str | None, interval: str = "15m", count: int = 120) -> dict[str, Any]:
        if not self.ready:
            return {"symbols": [], "quotes": [], "chart": None}
        return await self._call(self._market_blocking, chart_symbol, interval, count)

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
        deals = self._deals_between(start, now)

        entry_in = getattr(mt5, "DEAL_ENTRY_IN", 0)
        entry_out = getattr(mt5, "DEAL_ENTRY_OUT", 1)
        entry_out_by = getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)
        type_buy = getattr(mt5, "DEAL_TYPE_BUY", 0)
        type_sell = getattr(mt5, "DEAL_TYPE_SELL", 1)

        groups: dict[int, dict[str, Any]] = {}
        for deal in deals:
            if getattr(deal, "type", None) not in (type_buy, type_sell):
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
            elif entry in (entry_out, entry_out_by):
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
            if not g["in"] or not g["out"]:
                continue  # まだ決済していない建玉は positions 側で見る
            first_in = min(g["in"], key=lambda d: getattr(d, "time", 0))
            last_out = max(g["out"], key=lambda d: getattr(d, "time", 0))
            opened = int(getattr(first_in, "time", 0) or 0)
            closed = int(getattr(last_out, "time", 0) or 0)
            volume, open_price = weighted(g["in"])
            _, close_price = weighted(g["out"])
            profit = 0.0
            for d in (*g["in"], *g["out"]):
                profit += (
                    float(getattr(d, "profit", 0) or 0)
                    + float(getattr(d, "swap", 0) or 0)
                    + float(getattr(d, "commission", 0) or 0)
                )
            symbol = g["symbol"]
            trades.append(
                {
                    "id": pid,
                    "symbol": symbol,
                    "side": "buy" if getattr(first_in, "type", type_buy) == type_buy else "sell",
                    "volume": volume,
                    "open_price": open_price,
                    "close_price": close_price,
                    "digits": self._digits_blocking(symbol, cache),
                    "profit": round(profit, 2),
                    "opened_at": self._server_dt(opened).isoformat(timespec="minutes") if opened else "",
                    "closed_at": self._server_dt(closed).isoformat(timespec="minutes") if closed else "",
                    "held_sec": max(0, closed - opened),
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
            "gate_path": str(await self._call(self._gate_path)) if self.ready else None,
            "intent_by": self.intent_by,
            "intent_at": self.intent_at,
            "intent": self.desired_value,
            **ea,
            "server_time": server_now.isoformat(timespec="seconds") if server_now else None,
            "mt5_ready": self.ready,
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

        if command == "set_variable":
            name = str(payload.get("name", "")).strip()
            if not name:
                return self._ack(command, request_id, False, error="name が空です")
            try:
                value = float(payload.get("value"))
            except (TypeError, ValueError):
                return self._ack(command, request_id, False, error="value が数値ではありません")
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

        if command in ("get_market", "market"):
            if not self.mt.ready:
                return self._ack(command, request_id, False, error="MT5に接続していません")
            symbol = payload.get("symbol")
            data = await self.mt.market(
                str(symbol) if symbol else None,
                str(payload.get("interval", "15m")),
                int(payload.get("count", 120) or 120),
            )
            return self._ack(command, request_id, True, **data)

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
        self.connected_since: float | None = None
        self.disconnected_since: float = time.time()
        self._failsafe_fired = False
        self._active_ws: Any | None = None
        self._status_key: str = ""
        # いま画面が何枚開いているか（中継が教えてくれる）。
        # 0 のあいだは口座の数字を送らない。
        self.watchers: int = 0

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
        await ws.send(json.dumps(message, ensure_ascii=False, allow_nan=False, default=str))

    async def _on_connected(self, ws: Any) -> None:
        self.connected_since = time.time()
        self._failsafe_fired = False
        self._active_ws = ws
        status = await self.mt.status(include_today=True)
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
        status = await self.mt.status(include_today=True, include_probe=False)
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
                    await self._serve_connection(ws)
                    if getattr(ws, "close_code", None) == 4001:
                        log.warning("別の接続ツールが接続したため、このブリッジは終了します")
                        self.request_stop()
                        break
                log.warning("サーバーから切断されました")
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
                term = await self.mt._call(mt5.terminal_info) if self.mt.ready else None
                if term is None:
                    log.error("MT5 との接続が失われました。再初期化します")
                    self.mt.ready = False
                    await self.mt.connect_with_retry(self.stop)
                    if self.mt.ready:
                        # 再接続後も、記録してある指示に合わせるだけ
                        await self.mt.adopt_current_state()
                    continue

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

        await self.mt.connect_with_retry(self.stop)
        if self.stop.is_set():
            return
        # 起動直後は、MT5 側にある値をそのまま引き継ぐ。
        # 勝手に稼働中へ戻さないための要。記録が無いときだけ初期値を書く。
        try:
            await self.mt.adopt_current_state()
        except Exception as exc:  # noqa: BLE001
            log.exception("起動時の状態引き継ぎに失敗しました（中継への接続は続けます）: %s", exc)

        watchdog = asyncio.create_task(self.watchdog(), name="watchdog")
        pusher = asyncio.create_task(self.status_pusher(), name="pusher")
        try:
            await self.ws_loop()
        finally:
            for task in (watchdog, pusher):
                task.cancel()
            for task in (watchdog, pusher):
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


def main() -> int:
    parser = argparse.ArgumentParser(description="トレラボ MT5 ブリッジ")
    parser.add_argument("--check", action="store_true", help="MT5への接続と現在値を確認して終了する")
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
