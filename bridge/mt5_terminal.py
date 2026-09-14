"""MT5 のデータフォルダと terminal64.exe を特定する（connect / bridge 共通）。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import MetaTrader5 as mt5

    MT5_IMPORT_ERROR = ""
except ImportError as exc:  # DLL が読めない等もここに来る。理由はログに出す
    mt5 = None  # type: ignore[assignment]
    MT5_IMPORT_ERROR = str(exc)

# お客様の MT5 に置くシステム。connect.py が配り、bridge.py が有無を報告する
EA_NAMES = ("OrbitGoldEA_v11",)


def terminal_dir_from_data_path(data_path: str | Path) -> Path | None:
    """data_path/origin.txt から、この口座が使っている terminal64.exe のフォルダを取る。"""
    origin = Path(data_path) / "origin.txt"
    if not origin.is_file():
        return None
    text = ""
    for encoding in ("utf-16", "utf-8"):
        try:
            text = origin.read_text(encoding=encoding, errors="ignore").strip()
        except (OSError, UnicodeError):
            # MT5 は UTF-16 で書くが、そうでないものを渡されても落ちないようにする
            # （ここで落ちると MT5 の検出そのものが止まる）
            continue
        if text:
            break
    if not text:
        return None
    line = text.splitlines()[0].strip().strip('"')
    folder = Path(line)
    if (folder / "terminal64.exe").is_file() or (folder / "metaeditor64.exe").is_file():
        return folder
    return folder if folder.is_dir() else None


def iter_terminal_data_dirs() -> list[Path]:
    """AppData 配下の MT5 データフォルダ（origin.txt があるもの）。"""
    base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    if not base.is_dir():
        return []
    out: list[Path] = []
    for entry in base.iterdir():
        if entry.is_dir() and (entry / "origin.txt").is_file():
            out.append(entry)
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def _session_from_initialize(terminal_exe: Path | None) -> dict[str, Any] | None:
    if mt5 is None:
        return None
    mt5.shutdown()
    kwargs: dict[str, Any] = {}
    if terminal_exe is not None:
        kwargs["path"] = str(terminal_exe)
    if not mt5.initialize(**kwargs):
        return None
    info = mt5.account_info()
    term = mt5.terminal_info()
    if info is None or not getattr(info, "login", None):
        mt5.shutdown()
        return None
    data_path = getattr(term, "data_path", "") if term else ""
    exe = terminal_exe
    if exe is None and data_path:
        exe = terminal_dir_from_data_path(str(data_path))
        if exe is not None:
            exe = exe / "terminal64.exe"
    return {
        "account": info.login,
        "server": getattr(info, "server", ""),
        "data_path": str(data_path),
        "terminal_exe": exe,
        "terminal_name": getattr(term, "name", "") if term else "",
        "build": getattr(term, "build", "") if term else "",
    }


def find_logged_in_terminal() -> dict[str, Any] | None:
    """
    ログイン済みの MT5 を探す。
    複数ターミナルがあるとき、path 未指定の initialize だけだと別口座に繋がることがある。
    """
    if mt5 is None:
        return None

    tried: set[str] = set()
    candidates: list[Path | None] = [None]

    for data_dir in iter_terminal_data_dirs():
        origin = terminal_dir_from_data_path(data_dir)
        if origin is None:
            continue
        exe = origin / "terminal64.exe"
        if exe.is_file():
            candidates.append(exe)

    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    if pf.is_dir():
        for exe in pf.glob("**/terminal64.exe"):
            candidates.append(exe)

    for exe in candidates:
        key = str(exe) if exe else "<default>"
        if key in tried:
            continue
        tried.add(key)
        session = _session_from_initialize(exe)
        if session:
            return session

    mt5.shutdown()
    return None


def find_metaeditor(data_path: str, terminal_exe: Path | None) -> Path | None:
    """接続中ターミナル専用の MetaEditor だけを使う（別ブローカーの Editor は使わない）。"""
    origin = terminal_dir_from_data_path(data_path)
    if origin:
        editor = origin / "metaeditor64.exe"
        if editor.is_file():
            return editor
    if terminal_exe is not None and (terminal_exe.parent / "metaeditor64.exe").is_file():
        return terminal_exe.parent / "metaeditor64.exe"
    return None


def probe_ea_files(data_path: str) -> dict[str, Any]:
    experts = Path(data_path) / "MQL5" / "Experts"
    include = Path(data_path) / "MQL5" / "Include"
    found: list[str] = []
    compiled: list[str] = []
    for name in EA_NAMES:
        # 配るのはコンパイル済み(.ex5)。以前の方式で置いた .mq5 が残っていることもある
        if (experts / f"{name}.ex5").is_file():
            compiled.append(name)
            found.append(name)
        elif (experts / f"{name}.mq5").is_file():
            found.append(name)
    return {
        "experts_dir": str(experts),
        "include_dir": str(include),
        "include_ok": (include / "TradingGate.mqh").is_file(),
        "ea_found": found,
        "ea_compiled": compiled,
        "ea_installed": len(found) > 0,
    }


def resolve_terminal_exe(session: dict[str, Any]) -> Path | None:
    exe = session.get("terminal_exe")
    if isinstance(exe, Path) and exe.is_file():
        return exe
    data_path = session.get("data_path", "")
    if data_path:
        origin = terminal_dir_from_data_path(str(data_path))
        if origin and (origin / "terminal64.exe").is_file():
            return origin / "terminal64.exe"
    return None
