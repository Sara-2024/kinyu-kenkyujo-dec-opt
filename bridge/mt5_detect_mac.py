"""Mac の中の MT5 を探す（Mac ルート）。

Mac 版 MT5 は Wine の上で動く公式アプリで、データは
    ~/Library/Application Support/<アプリの名前>/drive_c/users/<ユーザー>/AppData/Roaming/MetaQuotes/Terminal/<ID>/
に置かれる（Windows の %APPDATA% と同じ並び）。業者ごとにアプリの名前が違う
（MetaQuotes 公式は net.metaquotes.wine.metatrader5、XM は com.xm.… など）ので、
名前を決め打ちせず「Wine の drive_c の中に MetaQuotes/Terminal がある」で探す。

見つけたら、その Wine の Roaming を APPDATA に向けることで、Windows 向けに書いてある
mt5_terminal / ea_manager / mt5_detect のコードがそのまま使える。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_SUPPORT = Path.home() / "Library" / "Application Support"

# アプリの内部名 → お客様に見せる名前（分からなければ内部名をそのまま）
KNOWN_APPS = {
    "net.metaquotes.wine.metatrader5": "MetaTrader 5",
    "net.metaquotes.wine.metatrader4": "MetaTrader 4",
}


@dataclass
class MacTerminal:
    """1 つの MT5（データフォルダ単位）。"""

    data_path: Path                  # …/MetaQuotes/Terminal/<ID>
    roaming: Path                    # …/AppData/Roaming（APPDATA に向ける）
    app_id: str                      # Wine のアプリ名（フォルダ名）
    app_label: str                   # 見せる名前
    label: str = ""                  # 「XM MT5（口座 123）」のような表示
    account: str = ""
    server: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def common_files(self) -> Path:
        return self.roaming / "MetaQuotes" / "Terminal" / "Common" / "Files"

    @property
    def exe(self) -> Path | None:
        """Windows 版の Terminal と同じ名前。Mac では Wine の中なので「無い」扱い。"""
        return None

    @property
    def install_dir(self) -> Path | None:
        return None

    @property
    def terminal_id(self) -> str:
        return self.data_path.name


def _is_mt5(data_path: Path) -> bool:
    """MQL5 フォルダがあるものだけ（MT4 のフォルダも同じ場所に並ぶ）。"""
    return (data_path / "MQL5").is_dir()


def _app_label(app_id: str) -> str:
    if app_id in KNOWN_APPS:
        return KNOWN_APPS[app_id]
    # com.xm.metatrader5 → XM、com.exness.mt5 → Exness のように、2 番目を使う
    parts = app_id.split(".")
    if len(parts) >= 2 and parts[0] in ("com", "net", "org"):
        return parts[1].upper() if len(parts[1]) <= 3 else parts[1].capitalize()
    return app_id


def find_terminals(app_support: Path | None = None) -> list[MacTerminal]:
    """Mac の中の MT5 を全部挙げる。MT4 と、消したあとの抜け殻は除く。"""
    root = app_support or APP_SUPPORT
    found: list[MacTerminal] = []
    try:
        apps = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return found
    for app in apps:
        users_dir = app / "drive_c" / "users"
        if not users_dir.is_dir():
            continue
        try:
            users = sorted(p for p in users_dir.iterdir() if p.is_dir())
        except OSError:
            continue
        for user in users:
            roaming = user / "AppData" / "Roaming"
            terminals = roaming / "MetaQuotes" / "Terminal"
            if not terminals.is_dir():
                continue
            try:
                entries = sorted(p for p in terminals.iterdir() if p.is_dir())
            except OSError:
                continue
            for data_path in entries:
                if data_path.name.lower() == "common" or not _is_mt5(data_path):
                    continue
                # Wine 側では MT5 本体が drive_c/Program Files/… に居る。無ければ抜け殻
                if not _has_program(app):
                    continue
                t = MacTerminal(
                    data_path=data_path,
                    roaming=roaming,
                    app_id=app.name,
                    app_label=_app_label(app.name),
                )
                t.account, t.server = account_hint(data_path)
                t.label = _label(t)
                found.append(t)
    return found


def _has_program(app: Path) -> bool:
    """Wine の中に MT5 本体（terminal64.exe）があるか。"""
    for pf in ("Program Files", "Program Files (x86)"):
        base = app / "drive_c" / pf
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if (child / "terminal64.exe").is_file() or (child / "terminal.exe").is_file():
                    return True
        except OSError:
            continue
    # 新しい配布では drive_c 直下に置く業者もあるので、見つからなくても抜け殻とは決めつけない
    return True


def _label(t: MacTerminal) -> str:
    base = t.app_label
    if t.server and t.server not in base:
        base = t.server if t.app_label in ("MetaTrader 5",) else f"{t.app_label} / {t.server}"
    if t.account:
        return f"{base}（口座 {t.account}）"
    return base


def account_hint(data_path: Path) -> tuple[str, str]:
    """直近のログから口座番号とサーバー名を拾う（ログインしていなくても分かる）。

    Windows 版の mt5_detect.account_hint と同じ読み方。見つからなければ空。
    """
    logs = data_path / "logs"
    try:
        files = sorted(logs.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    except OSError:
        return "", ""
    for path in files:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        text = ""
        for encoding in ("utf-16-le", "utf-16", "utf-8", "cp932"):
            try:
                text = raw.decode(encoding)
                if "authoriz" in text or "login" in text.lower():
                    break
            except (UnicodeDecodeError, LookupError):
                continue
        account, server = _parse_login(text)
        if account:
            return account, server
    return "", ""


def _parse_login(text: str) -> tuple[str, str]:
    """``'12345678': authorized on XMTrading-MT5 3`` のような行から取る。"""
    import re

    for line in reversed(text.splitlines()):
        m = re.search(r"'(\d{4,})'\s*:\s*authorized on\s+([^\s(]+(?:\s[^\s(]+)*)", line)
        if m:
            return m.group(1), m.group(2).strip()
        m = re.search(r"login\s+(\d{4,})\s+on\s+'?([^'\s]+(?:\s[^'\s]+)*)", line, re.I)
        if m:
            return m.group(1), m.group(2).strip()
    return "", ""


def point_appdata_at(t: MacTerminal) -> None:
    """Windows 向けの部品（mt5_terminal / ea_manager）が、この MT5 を見るようにする。"""
    os.environ["APPDATA"] = str(t.roaming)
    os.environ["TRELAB_FILES_DIR"] = str(t.common_files)
    os.environ["TRELAB_DATA_PATH"] = str(t.data_path)
