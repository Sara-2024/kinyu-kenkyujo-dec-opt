"""接続ツールの状態。INSTALL_ONLY と CONNECTED の2つだけ。

  INSTALL_ONLY … MT5 を探して EA を置くところまで。サイトとは一切通信しない。
                 配布直後はここから始まる。
  CONNECTED    … サイトから正式に連携された後。これまでどおりブリッジを動かし、
                 口座の情報をサイトへ送る。

置き場は %LOCALAPPDATA%\\AITrader\\state.json（intent.json や clock.json と同じ）。

すでにサイトと連携して使っているお客様の PC には state.json がまだ無い。
その場合は bridge.env の BRIDGE_ID を見て CONNECTED とみなす（下の adopt_legacy）。
これをしないと、次の更新でいきなり「EA を置くだけ」に戻ってしまう。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INSTALL_ONLY = "INSTALL_ONLY"
CONNECTED = "CONNECTED"

STATE_FILE = "state.json"

# サイトの会員ID（UUID）。既定の部屋 vps-01 はこれに当たらない
MEMBER_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def config_dir() -> Path:
    """設定の置き場。connect.py の log_dir() と同じ場所を指す。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TMPDIR") or "/tmp"
    path = Path(base) / "AITrader"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def state_path() -> Path:
    return config_dir() / STATE_FILE


def read() -> dict[str, Any]:
    """いまの状態。読めなければ INSTALL_ONLY として扱う（勝手に繋がないため）。"""
    try:
        raw = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": INSTALL_ONLY}
    if not isinstance(raw, dict):
        return {"state": INSTALL_ONLY}
    if raw.get("state") not in (INSTALL_ONLY, CONNECTED):
        raw["state"] = INSTALL_ONLY
    return raw


def write(state: str, **extra: Any) -> dict[str, Any]:
    if state not in (INSTALL_ONLY, CONNECTED):
        raise ValueError(f"知らない状態: {state}")
    data = read()
    data.update(extra)
    data["state"] = state
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        state_path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return data


def current() -> str:
    return str(read().get("state") or INSTALL_ONLY)


def is_connected() -> bool:
    return current() == CONNECTED


def adopt_legacy(bridge_id: str) -> bool:
    """state.json がまだ無い PC を、これまでの設定から引き継ぐ。

    bridge.env の BRIDGE_ID が会員ID なら、すでにサイトと連携して使っている PC。
    記録を CONNECTED にして、今までどおり動くようにする。
    戻り値は「引き継いだか」。
    """
    if state_path().is_file():
        return False
    if not MEMBER_ID_RE.match((bridge_id or "").strip()):
        return False
    write(CONNECTED, room=bridge_id.strip(), adopted_from="bridge.env")
    return True


def mark_connected(room: str, *, account: Any = None, server: str = "") -> dict[str, Any]:
    """サイトから正式に連携されたとき。ここでだけ CONNECTED になる。"""
    extra: dict[str, Any] = {"room": room}
    if account is not None:
        extra["account"] = account
    if server:
        extra["server"] = server
    return write(CONNECTED, **extra)


def mark_install_only(reason: str = "") -> dict[str, Any]:
    """連携を解除したとき。サイトとの通信をやめ、EA はそのまま残す。"""
    return write(INSTALL_ONLY, reason=reason)
