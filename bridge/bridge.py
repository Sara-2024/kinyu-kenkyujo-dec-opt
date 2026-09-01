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
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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


def acquire_instance_lock() -> None:
    """同じPCで bridge.py を二重起動すると、中継が切断と再接続を繰り返す。"""
    global _LOCK_FH
    path = Path(os.environ.get("TEMP", ".")) / "trelab-bridge.lock"
    _LOCK_FH = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            _LOCK_FH.seek(0)
            if _LOCK_FH.read(1) == b"":
                _LOCK_FH.write(b"0")
                _LOCK_FH.flush()
            _LOCK_FH.seek(0)
            msvcrt.locking(_LOCK_FH.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_LOCK_FH.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("別のブリッジがすでに動いています。")
        log.error("start-connect.bat と start-windows.bat を同時に開いていないか、黒い窓が複数ないか確認してください。")
        raise SystemExit(2)
    _LOCK_FH.seek(0)
    _LOCK_FH.truncate()
    _LOCK_FH.write(str(os.getpid()).encode("ascii", "replace"))
    _LOCK_FH.flush()


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
        # 「サーバーから最後に指示された状態」。再接続や再起動のあとで復元する
        self.desired_value: float = cfg.gv_default

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

    async def set_trading(self, allowed: bool) -> tuple[bool, float | None]:
        value = 1.0 if allowed else 0.0
        self.desired_value = value
        ok, readback = await self.set_variable(self.cfg.gv_name, value)
        if ok:
            log.info(
                "売買フラグを更新: %s = %s (%s)",
                self.cfg.gv_name,
                value,
                "許可" if allowed else "停止",
            )
        return ok, readback

    def _ea_probe_blocking(self) -> dict[str, Any]:
        term = mt5.terminal_info() if mt5 is not None else None
        data_path = getattr(term, "data_path", "") if term is not None else ""
        experts = Path(str(data_path)) / "MQL5" / "Experts"
        found: list[str] = []
        compiled: list[str] = []
        for name in ("SiteTestEA", "TrelabEA"):
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
                    "opened_at": datetime.fromtimestamp(opened).isoformat(timespec="minutes") if opened else "",
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
            now = datetime.now()
            start = (now - timedelta(days=span - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
            deals = mt5.history_deals_get(start, now) or ()
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
                key = datetime.fromtimestamp(stamp).strftime("%Y-%m-%d") if stamp else start.strftime("%Y-%m-%d")
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
            now = datetime.now()
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            deals = mt5.history_deals_get(start, now) or ()
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

    async def positions(self) -> list[dict[str, Any]]:
        if not self.ready:
            return []
        return await self._call(self._positions_blocking)

    async def history(self, days: int = 30) -> dict[str, Any]:
        if not self.ready:
            return {}
        return await self._call(self._history_stats_blocking, days)

    async def currency(self) -> str | None:
        info = await self._call(mt5.account_info) if self.ready else None
        return getattr(info, "currency", None)

    async def status(self, *, include_today: bool = False) -> dict[str, Any]:
        info = await self._call(mt5.account_info) if self.ready else None
        term = await self._call(mt5.terminal_info) if self.ready else None
        probe = await self._call(self._ea_probe_blocking) if self.ready else {}
        gate = await self._call(self._load_gate) if self.ready else {}
        today = await self._call(self._today_stats_blocking) if (self.ready and include_today) else {}
        return {
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
        status = await self.mt.status()
        self._status_key = f"{status.get('account')}:{status.get('server')}"
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

    async def _push_status_if_changed(self) -> None:
        ws = self._active_ws
        if ws is None or not self.mt.ready:
            return
        status = await self.mt.status()
        key = f"{status.get('account')}:{status.get('server')}"
        if key == self._status_key:
            return
        self._status_key = key
        log.info("MT5 口座が切り替わりました: %s", key)
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
                        await self.mt.set_variable(self.cfg.gv_name, self.mt.desired_value)
                    continue

                if self.cfg.reassert:
                    current = await self.mt.get_variable(self.cfg.gv_name)
                    if current is None or float(current) != float(self.mt.desired_value):
                        log.warning(
                            "売買フラグがズレています (現在=%s / あるべき=%s)。書き戻します",
                            current,
                            self.mt.desired_value,
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
                        await self.mt.set_trading(False)
                        self._failsafe_fired = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("見張り処理で例外: %s", exc)

    # ---------- 起動 ----------
    async def run(self) -> None:
        log.info("=" * 62)
        log.info("トレラボ MT5 ブリッジ起動  bridge_id=%s", self.cfg.bridge_id)
        log.info("接続先        : %s", self.cfg.ws_url)
        log.info("制御する変数  : %s (初期値 %s)", self.cfg.gv_name, self.cfg.gv_default)
        if self.cfg.failsafe_sec > 0:
            log.info("デッドマンSW  : %.0f 秒切断で自動停止", self.cfg.failsafe_sec)
        log.info("=" * 62)

        await self.mt.connect_with_retry(self.stop)
        if self.stop.is_set():
            return
        # 起動直後の状態を確定させておく（EAが不定値を読まないように）
        try:
            await self.mt.set_variable(self.cfg.gv_name, self.mt.desired_value)
        except Exception as exc:  # noqa: BLE001
            log.exception("起動時の指令書き込みに失敗しました（中継への接続は続けます）: %s", exc)

        watchdog = asyncio.create_task(self.watchdog(), name="watchdog")
        try:
            await self.ws_loop()
        finally:
            watchdog.cancel()
            try:
                await watchdog
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
