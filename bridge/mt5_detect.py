"""PC の中の MetaTrader 5 を、起動もログインもさせずに全部見つける。

既存の mt5_terminal.py は「いまログイン済みの1台」を MetaTrader5 パッケージ越しに
探すためのもの。こちらは EA を置くためだけに使うので、

  ・MT5 が起動していなくてよい
  ・ログインしていなくてよい
  ・MetaTrader5 パッケージが無くてよい（インターネットも要らない）

AppData のデータフォルダ（origin.txt があるところ）を数えるだけで済む。
EA の置き場は MQL5/Experts なので、口座に入らなくてもファイルは置ける。

ブローカー名は、インストール先フォルダの名前から起こす。
（"C:\\Program Files\\HFM MetaTrader 5" → "HFM"）
口座番号やサーバー名は、ログインしないと取れないのでここでは扱わない。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # connect.py からも bridge.py からも使えるようにする
    from mt5_terminal import iter_terminal_data_dirs, origin_folder, terminal_dir_from_data_path
except ImportError:  # pragma: no cover - パッケージとして読まれたとき
    from .mt5_terminal import iter_terminal_data_dirs, origin_folder, terminal_dir_from_data_path  # type: ignore

# インストール先フォルダ名から外す言葉。残りをブローカー名として見せる
_NOISE = ("metatrader 5", "metatrader5", "metatrader", "terminal", "mt5", "platform", "(x86)")


@dataclass
class Terminal:
    """1台の MT5。EA を置くのに要る情報だけ持つ。"""

    data_path: Path
    install_dir: Path | None = None
    label: str = ""
    last_used: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def exe(self) -> Path | None:
        if self.install_dir is None:
            return None
        exe = self.install_dir / "terminal64.exe"
        return exe if exe.is_file() else None

    @property
    def experts_dir(self) -> Path:
        return self.data_path / "MQL5" / "Experts"

    @property
    def include_dir(self) -> Path:
        return self.data_path / "MQL5" / "Include"

    def as_dict(self) -> dict[str, Any]:
        return {
            "data_path": str(self.data_path),
            "install_dir": str(self.install_dir) if self.install_dir else "",
            "label": self.label,
            "last_used": self.last_used,
            **self.extra,
        }


# MT5 のログに出る「口座とサーバー」の行
#   'Network  '235147473': authorized on HFMarketsGlobal-Demo4 through ...'
_LOGIN_RE = re.compile(r"'(\d{4,})':\s*(?:authorized on|login to|connected to)\s+([A-Za-z0-9._\- ]+?)(?:\s+through|\s*\(|$)", re.M)
# 口座番号だけでも拾えるようにする（サーバー名の書き方はビルドで変わる）
_ACCOUNT_RE = re.compile(r"'(\d{6,})'")


def _read_log(path: Path) -> str:
    """MT5 のログを読む。文字コードは環境（ビルド）で変わる。"""
    try:
        raw = path.read_bytes()[:4_000_000]
    except OSError:
        return ""
    first = ""
    for encoding in ("utf-8", "utf-16-le", "utf-16", "cp932"):
        try:
            text = raw.decode(encoding, errors="ignore")
        except (LookupError, UnicodeError):
            continue
        first = first or text
        # 当たりの文字コードなら、ログにしかない語がそのまま読める。
        # UTF-16 を utf-8 で読むと文字の間に NUL が入り、この語が現れない
        if "Network" in text or "Terminal" in text or "authorized" in text:
            return text
    return first


def account_hint(data_path: Path) -> tuple[str, str]:
    """その MT5 が最後に入った口座とサーバー。分からなければ空。

    お客様はフォルダ名では区別できない（「4」「2」では選べない）。
    口座番号とブローカー名なら、MT5 の画面と同じなので選べる。
    ログイン情報そのものは読まない。番号とサーバー名だけ。

    ログイン行はその日のログの**先頭近く**に出るので、末尾だけ読むと見つからない。
    文字コードもビルドによって変わる。
    """
    folders = [data_path / "logs"]
    install = terminal_dir_from_data_path(data_path)
    if install is not None:
        folders.append(install / "logs")

    files: list[Path] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            files.extend(sorted(folder.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:5])
        except OSError:
            continue
    if not files:
        return "", ""

    account = server = ""
    for path in files:
        text = _read_log(path)
        if not text:
            continue
        found = _LOGIN_RE.findall(text)
        if found:
            got_account, got_server = found[-1]
            return got_account.strip(), got_server.strip()
        if not account:
            numbers = _ACCOUNT_RE.findall(text)
            if numbers:
                account = numbers[-1]
    return account, server


def broker_label(install_dir: Path | None, data_path: Path) -> str:
    """お客様に見せる名前。MT5 の画面で見えるものに合わせる。"""
    account, server = account_hint(data_path)
    if account and server:
        return f"{server}（口座 {account}）"
    if account:
        return f"口座 {account}"
    if server:
        return server

    name = install_dir.name if install_dir else ""
    out = " ".join(_strip_noise(name).split())
    # 「4」「2」のような、削った残りが数字だけのものは使わない
    if out and not out.isdigit():
        return out
    if name:
        return name
    return f"MetaTrader 5（{data_path.name[:8]}）"


def _strip_noise(name: str) -> str:
    out = name
    for word in _NOISE:
        # 大文字小文字を無視して取り除く
        low = out.lower()
        start = low.find(word)
        while start >= 0:
            out = out[:start] + " " + out[start + len(word) :]
            low = out.lower()
            start = low.find(word)
    return out


def _last_used(data_path: Path) -> float:
    """最後に使われた時刻。新しいものを既定に選ぶために使う。"""
    best = 0.0
    for name in ("origin.txt", "config", "logs", "MQL5"):
        target = data_path / name
        try:
            best = max(best, target.stat().st_mtime)
        except OSError:
            continue
    return best


def is_mt5(data_path: Path) -> bool:
    """MT5 のデータフォルダか。

    %APPDATA%\\MetaQuotes\\Terminal には MT4 のフォルダも並んでいる。
    MT4 は MQL4、MT5 は MQL5 を持つ。MT5 の EA は MT4 では動かないので、
    MQL5 があるものだけを相手にする（これをしないと、お客様の選択画面に
    MT4 まで並んで、どれを選べばいいか分からなくなる）。
    """
    try:
        if (data_path / "MQL4").is_dir() and not (data_path / "MQL5").is_dir():
            return False
        return (data_path / "MQL5").is_dir()
    except OSError:
        return False


def is_ghost(data_path: Path) -> bool:
    """本体（terminal64.exe）がもう無いデータフォルダか。

    origin.txt が指す場所に MT5 が無ければ、その MT5 は消されている。
    origin.txt が読めないときは、消されたとは言い切れないので残す。
    """
    folder = origin_folder(data_path)
    if folder is None:
        return False
    return not (folder / "terminal64.exe").is_file() and not (folder / "terminal.exe").is_file()


def list_terminals() -> list[Terminal]:
    """見つかった MT5 を、最後に使った順に並べて返す。MT4 は入れない。"""
    out: list[Terminal] = []
    for data_dir in iter_terminal_data_dirs():
        if not is_mt5(data_dir):
            continue
        if is_ghost(data_dir):
            # MT5 を消した／別の場所に入れ直したあとに残る抜け殻。
            # ここに EA を置いても、どの MT5 からも見えない
            continue
        install = terminal_dir_from_data_path(data_dir)
        out.append(
            Terminal(
                data_path=data_dir,
                install_dir=install,
                label=broker_label(install, data_dir),
                last_used=_last_used(data_dir),
            )
        )
    out.sort(key=lambda t: t.last_used, reverse=True)
    return out


def pick_default(terminals: list[Terminal]) -> Terminal | None:
    """1台しか無ければそれ。複数あるときは呼び出し側で選んでもらう。"""
    if not terminals:
        return None
    return terminals[0]


def describe(terminals: list[Terminal]) -> str:
    """記録用の1行。お客様には見せない。"""
    if not terminals:
        return "MT5 なし"
    return " / ".join(f"{t.label}[{t.data_path.name[:8]}]" for t in terminals)


def mt5_is_installed() -> bool:
    """データフォルダが1つでもあれば、MT5 を使ったことがあるとみなす。"""
    return bool(list_terminals())


def program_files_candidates() -> list[Path]:
    """データフォルダがまだ無い PC 向け。インストール先だけでも探す。"""
    out: list[Path] = []
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(key)
        if not base:
            continue
        root = Path(base)
        if not root.is_dir():
            continue
        try:
            for exe in root.glob("*/terminal64.exe"):
                out.append(exe.parent)
        except OSError:
            continue
    return out
