"""Mac の中の MT5 を探す（Mac ルート）。

Mac 版 MT5 は Wine の上で動く公式アプリで、データは
    ~/Library/Application Support/<アプリの名前>/drive_c/users/<ユーザー>/AppData/Roaming/MetaQuotes/Terminal/<ID>/
に置かれる（Windows の %APPDATA% と同じ並び）。業者ごとにアプリの名前が違う
（MetaQuotes 公式は net.metaquotes.wine.metatrader5、XM は com.xm.… など）ので、
名前を決め打ちせず「Wine の drive_c の中に MetaQuotes/Terminal がある」で探す。

見つけたら、その Wine の Roaming を APPDATA に向けることで、Windows 向けに書いてある
mt5_terminal / ea_manager / mt5_detect のコードがそのまま使える。

ただし Mac 公式の MT5 は「ポータブルモード」で動く（データフォルダに portable.txt がある）。
このとき AppData 側のフォルダには origin.txt と config しか無く、MQL5（EA の置き場）も
logs（口座番号を拾う元）も、origin.txt が指す本体フォルダ（C:\\Program Files\\MetaTrader 5 や
C:\\MT5-Test = drive_c の下）にある。AppData 側だけ見て「MQL5 が無いから MT5 ではない」と
捨てると、Mac では 1 台も見つからない（実際に起きた）。origin.txt を drive_c に読み替えて、
MQL5 がある側を data_path にする（`resolve_data_dir`）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:  # connect_mac.py からも試験からも使えるようにする
    from mt5_terminal import origin_folder
except ImportError:  # pragma: no cover - パッケージとして読まれたとき
    from .mt5_terminal import origin_folder  # type: ignore

APP_SUPPORT = Path.home() / "Library" / "Application Support"

# アプリの内部名 → お客様に見せる名前（分からなければ内部名をそのまま）
KNOWN_APPS = {
    "net.metaquotes.wine.metatrader5": "MetaTrader 5",
    "net.metaquotes.wine.metatrader4": "MetaTrader 4",
}


@dataclass
class MacTerminal:
    """1 つの MT5（データフォルダ単位）。"""

    data_path: Path                  # MQL5 と logs があるフォルダ（普通は …/Terminal/<ID>、ポータブルなら本体フォルダ）
    roaming: Path                    # …/AppData/Roaming（APPDATA に向ける。Common/Files はここの下）
    app_id: str                      # Wine のアプリ名（フォルダ名）
    app_label: str                   # 見せる名前
    label: str = ""                  # 「XM MT5（口座 123）」のような表示
    account: str = ""
    server: str = ""
    appdata_path: Path | None = None  # …/MetaQuotes/Terminal/<ID>（ID を取る元。data_path と同じこともある）
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
        return (self.appdata_path or self.data_path).name

    @property
    def portable(self) -> bool:
        """本体フォルダをデータフォルダとして使っている（Mac 公式の MT5 はこれ）。"""
        return self.appdata_path is not None and self.appdata_path != self.data_path


def _wine_path(app: Path, win_path: Path | str) -> Path | None:
    """``C:\\MT5-Test`` のような Windows の書き方を、この Wine の drive_c の下に読み替える。

    C: 以外（Z: は Mac のルートに当たる）は相手にしない。
    """
    text = str(win_path).strip().strip('"')
    m = re.match(r"^([A-Za-z]):[\\/]?(.*)$", text)
    if not m or m.group(1).lower() != "c":
        return None
    parts = [p for p in re.split(r"[\\/]+", m.group(2)) if p and p != "."]
    return app.joinpath("drive_c", *parts)


def resolve_data_dir(app: Path, appdata_dir: Path) -> Path | None:
    """AppData 側のフォルダから、MQL5 と logs が本当にあるフォルダを決める。

    普通のモードなら AppData 側そのもの。ポータブルモード（portable.txt がある）では
    origin.txt が指す本体フォルダ。本体が消えていれば抜け殻なので None。
    MT4（MQL4 だけ）も、どちらにも MQL5 が無いので None になる。
    """
    if (appdata_dir / "MQL5").is_dir():
        return appdata_dir
    origin = origin_folder(appdata_dir)
    if origin is None:
        return None
    real = _wine_path(app, origin)
    if real is not None and (real / "MQL5").is_dir():
        return real
    return None


def _common_mtime(roaming: Path) -> float:
    """その Roaming の Common/Files がいつ最後に書かれたか（無ければ 0）。"""
    try:
        return (roaming / "MetaQuotes" / "Terminal" / "Common" / "Files").stat().st_mtime
    except OSError:
        return 0.0


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
    # 同じ本体フォルダを、Wine の別ユーザー（users/mao と users/user など）からも見ることがある。
    # 本体 1 つにつき 1 台として数え、Roaming は Common/Files が新しいほう（＝MT5 が実際に
    # 使っているほう）を採る
    seen: dict[str, MacTerminal] = {}
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
            for appdata_dir in entries:
                if appdata_dir.name.lower() == "common":
                    continue
                data_path = resolve_data_dir(app, appdata_dir)
                if data_path is None:
                    continue
                # Wine 側では MT5 本体が drive_c/Program Files/… に居る。無ければ抜け殻
                if not _has_program(app):
                    continue
                key = str(data_path)
                prev = seen.get(key)
                if prev is not None:
                    if _common_mtime(roaming) > _common_mtime(prev.roaming):
                        prev.roaming = roaming
                    continue
                t = MacTerminal(
                    data_path=data_path,
                    roaming=roaming,
                    app_id=app.name,
                    app_label=_app_label(app.name),
                    appdata_path=appdata_dir,
                )
                t.account, t.server = account_hint(data_path)
                t.label = _label(t)
                seen[key] = t
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
    # ポータブルで Program Files 以外に置いた MT5 は、フォルダ名でも見分けられるようにする
    #（同じ業者の MT5 が何台もあるとき、口座番号が拾えないと区別がつかない）
    if t.portable and t.data_path.parent.name not in ("Program Files", "Program Files (x86)"):
        base = f"{base} / {t.data_path.name}"
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
            # 「HFMarketsGlobal-Demo4 through Access Server 1」の後ろ半分は経路の話なので落とす
            server = re.split(r"\s+through\s+", m.group(2).strip(), maxsplit=1)[0]
            return m.group(1), server
        m = re.search(r"login\s+(\d{4,})\s+on\s+'?([^'\s]+(?:\s[^'\s]+)*)", line, re.I)
        if m:
            return m.group(1), m.group(2).strip()
    return "", ""


def point_appdata_at(t: MacTerminal) -> None:
    """Windows 向けの部品（mt5_terminal / ea_manager）が、この MT5 を見るようにする。"""
    os.environ["APPDATA"] = str(t.roaming)
    os.environ["TRELAB_FILES_DIR"] = str(t.common_files)
    os.environ["TRELAB_DATA_PATH"] = str(t.data_path)
