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

# お客様の MT5 に置くシステム。connect.py が配り、bridge.py が有無を報告する。
#
# 名前の後半（版など）は変わることがあるので、見つけるときは EA_MATCH で探す。
# EA_NAMES は「いま配っているもの」で、同梱の .ex5 から決まる（無ければこの既定値）。
EA_MATCH = "Yumekku"
EA_NAMES = ("YumekkuEA-1年版",)   # Windows・Mac とも同じ名前
# ロイヤルファーストクラスの「2 つ目の口座」（connect.py の connect_slot。Windows だけ）に置く EA。
# 安定低月利ver（育てる運用。複利ロット・1取引のリスク上限・月次ストップ）。配布物は bridge/growth/ に分けて同梱する
# （bridge/ 直下に置くと 1 本目の配布物として拾われる）。名前に Yumekku を含むので is_our_ea は通る。
GROWTH_EA_NAME = "YumekkuEA1年版｜安定低月利ver"
GROWTH_EA_DIRNAME = "growth"
# Yumekku【サブスク版】（運営が承認しているあいだだけ新規エントリーする EA）。サブスクの会員の口座に置く。
# 配布物は bridge/subscription/ に分けて同梱する。名前に Yumekku を含むので is_our_ea は通る
SUB_EA_NAME = "Yumekku【サブスク版】"
SUB_EA_DIRNAME = "subscription"


def is_our_ea(stem: str) -> bool:
    """その名前は、うちのシステムか。後半が変わっても拾えるようにする。"""
    return EA_MATCH.lower() in str(stem).lower()


def is_gold_symbol(name: str) -> bool:
    """EA を載せてよい銘柄か（ドル建ての金）。

    業者によって XAUUSD / GOLD / GOLD# / XAUUSD.r などと名前が違うので、
    「XAUUSD か GOLD を含む」で見る。XAUEUR / XAUJPY はどちらも含まないので弾ける。
    """
    upper = str(name or "").upper()
    return "XAUUSD" in upper or "GOLD" in upper


def origin_folder(data_path: str | Path) -> Path | None:
    """origin.txt に書かれたインストール先。存在するかは見ない（読めなければ None）。"""
    origin = Path(data_path) / "origin.txt"
    if not origin.is_file():
        return None
    text = ""
    for encoding in ("utf-16", "utf-8"):
        try:
            text = origin.read_text(encoding=encoding, errors="ignore").strip()
        except (OSError, UnicodeError):
            continue
        if text:
            break
    if not text:
        return None
    line = text.splitlines()[0].strip().strip('"')
    return Path(line) if line else None


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


def _norm_exe(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def running_terminal_exes() -> list[Path] | None:
    """いま動いている MT5（terminal64.exe）の実行ファイル。調べられなければ None。

    mt5.initialize() は、相手の MT5 が動いていなければ**自分で起動してしまう**
    （path を渡さなければ、最後に使った MT5 を起こす）。お客様が閉じた MT5 を
    パスポートが開き直し続ける事故（2026-11）の原因だったので、initialize の前に
    必ずここで「動いているか」を確かめる。Windows 以外（Mac は mt5_files で、起動しない）は None。
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32FirstW.restype = wintypes.BOOL
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32NextW.restype = wintypes.BOOL
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        # 名前の一覧（プロセスを開かずに取れる。管理者で動いている MT5 も漏れない）
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)   # TH32CS_SNAPPROCESS
        if not snap or snap == wintypes.HANDLE(-1).value:
            return None
        pids: list[int] = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == "terminal64.exe":
                    pids.append(int(entry.th32ProcessID))
                ok = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)

        # 場所（どの MT5 か）。読めないものが 1 つでもあれば「分からない」（None）にして、これまでどおり動かす
        out: list[Path] = []
        buf = ctypes.create_unicode_buffer(1024)
        for pid in pids:
            handle = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                length = wintypes.DWORD(len(buf))
                if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(length)):
                    return None
                out.append(Path(buf.value))
            finally:
                k32.CloseHandle(handle)
        return out
    except Exception:  # noqa: BLE001
        return None


def terminal_is_running(exe: str | Path | None) -> bool:
    """その MT5 が動いているか。Windows 以外と、調べられないときは True（これまでどおり）。

    exe が None（どれでもよい）なら「どれか 1 つでも動いているか」。
    """
    running = running_terminal_exes()
    if running is None:
        return True
    if exe is None:
        return bool(running)
    want = _norm_exe(exe)
    return any(_norm_exe(p) == want for p in running)


def _session_from_initialize(terminal_exe: Path | None) -> dict[str, Any] | None:
    if mt5 is None:
        return None
    # 動いていない MT5 には繋ぎに行かない（initialize が起動してしまう）
    if not terminal_is_running(terminal_exe):
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


def find_logged_in_terminal(prefer_data_path: str | Path | None = None) -> dict[str, Any] | None:
    """
    ログイン済みの MT5 を探す。
    複数ターミナルがあるとき、path 未指定の initialize だけだと別口座に繋がることがある。

    prefer_data_path に「初回に選んだ MT5」を渡すと、そこから先に試す。
    これが無いと、MT5 が何台もあるお客様の PC で、思っていないほうに
    EA が入ってしまう（どれに入ったのかも分からない）。
    """
    if mt5 is None:
        return None

    tried: set[str] = set()
    candidates: list[Path | None] = []

    # 初回に選んだ MT5 を最優先にする
    if prefer_data_path:
        origin = terminal_dir_from_data_path(prefer_data_path)
        if origin is not None and (origin / "terminal64.exe").is_file():
            candidates.append(origin / "terminal64.exe")

    running = running_terminal_exes()
    if running is not None:
        # Windows：いま動いている MT5 だけを試す。閉じている MT5 は起こさない
        # （以前は Program Files の MT5 まで片っ端から initialize し、閉じた MT5 が開き直していた）
        if not running:
            return None
        live = {_norm_exe(p) for p in running}
        candidates = [c for c in candidates if c is not None and _norm_exe(c) in live]
        candidates.extend(running)
        for exe in candidates:
            key = _norm_exe(exe) if exe else "<default>"
            if key in tried:
                continue
            tried.add(key)
            session = _session_from_initialize(exe)
            if session:
                return session
        mt5.shutdown()
        return None

    candidates.append(None)  # 指定なし（いま前面にある MT5）

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
    # 名前の後半は変わりうるので、Yumekku が入っているものを全部見る
    try:
        for path in sorted(experts.glob("*.ex5")):
            if is_our_ea(path.stem):
                compiled.append(path.stem)
                found.append(path.stem)
        for path in sorted(experts.glob("*.mq5")):
            if is_our_ea(path.stem) and path.stem not in found:
                found.append(path.stem)
    except OSError:
        pass
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
