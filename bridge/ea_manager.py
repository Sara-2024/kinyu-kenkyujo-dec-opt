"""EA の状態を見て、必要なときだけ置き直す。

配るのは**コンパイル済みの `YumekkuEA-1年版.ex5`**。お客様の PC では
MetaEditor を起動しないし、コンパイルもしない。ソース（.mq5）も配らない。

  ・MetaEditor が無い PC でも確実に置ける
  ・コンパイルの失敗が起きない
  ・置く処理は「ファイルを1つ置く」だけになる

置く場所と名前はこれまでどおり（MQL5/Experts/YumekkuEA-1年版.ex5）。
すでに使っているお客様のチャート設定を動かさないため、今回は変えない。

状態は5つ:
  NOT_INSTALLED     … まだ置かれていない
  LATEST            … 置かれていて、中身も配布物と同じ
  UPDATE_AVAILABLE  … 置かれているが中身が違う（古い）
  INSTALLED         … 置かれているが、配布物と比べられない（同梱物が無い等）
  ERROR             … フォルダが読めない／配布物が壊れている

版（6.10 など）は .ex5 からは読めないので、同梱の ea_manifest.json に書く。
manifest は tools/make-ea-manifest.py が作る（Windows でコンパイルした後）。

**3つを混同しないこと。**

  ea_manifest.json … 正式な配布物はどれか（版と SHA-256）
  ea_installed.json … Connect が最後に置いたのはどれか（あくまで控え）
  実ファイルの SHA-256 … いま本当に入っているのはどれか

状態を決めるのは**必ず実ファイルの SHA-256**。控えは「入っている版の名前」を
言うためだけに使い、控えと実ファイルが食い違っていたら控えの方を捨てる。
そうしないと、お客様が手で .ex5 を差し替えたときに「最新です」と嘘をつく。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time

try:
    from mt5_terminal import is_gold_symbol as _is_gold_symbol, is_our_ea as _is_our_ea
except ImportError:  # pragma: no cover - 単体で読み込まれたとき

    def _is_our_ea(stem: str) -> bool:
        return "yumekku" in str(stem).lower()

    def _is_gold_symbol(name: str) -> bool:
        upper = str(name or "").upper()
        return "XAUUSD" in upper or "GOLD" in upper
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from mt5_terminal import EA_MATCH, EA_NAMES, is_our_ea
except ImportError:  # pragma: no cover
    from .mt5_terminal import EA_MATCH, EA_NAMES, is_our_ea  # type: ignore

NOT_INSTALLED = "NOT_INSTALLED"
INSTALLED = "INSTALLED"
UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
LATEST = "LATEST"
ERROR = "ERROR"

EA_NAME = EA_NAMES[0]  # 同梱の .ex5 が見つかれば、そちらの名前で上書きされる
# 配る形式。コンパイル済みだけを配る（ソースは配らない）
EA_SOURCE_SUFFIX = ".ex5"
# EA が読む共通部品。これも一緒に置く
INCLUDE_FILES = ("TradingGate.mqh",)
MANIFEST_NAME = "ea_manifest.json"
RECORD_NAME = "ea_installed.json"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TMPDIR") or "/tmp"
    path = Path(base) / "AITrader"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


# ────────────────────────────────
# 配布物（exe に同梱している EA）
# ────────────────────────────────
@dataclass
class Source:
    ea_path: Path
    version: str
    sha256: str
    includes: tuple[Path, ...]
    #: manifest と中身が食い違っていたら、その理由。空なら健全
    broken: str = ""

    @property
    def file_name(self) -> str:
        return self.ea_path.name

    @property
    def ok(self) -> bool:
        return not self.broken


def find_source_file(assets_dir: Path) -> Path | None:
    """同梱している EA（.ex5）を探す。

    名前の後半（版など）は変わるので、決め打ちにしない。
    Yumekku が入っている .ex5 を拾い、新しいものを使う。
    """
    try:
        found = [p for p in Path(assets_dir).glob(f"*{EA_SOURCE_SUFFIX}") if is_our_ea(p.stem)]
    except OSError:
        return None
    if not found:
        return None
    # 前の名前のものが残っていることがある。いま配る名前のものを最優先にする
    for path in found:
        if path.stem == EA_NAMES[0]:
            return path
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0]


def load_source(assets_dir: Path, include_dir: Path | None = None) -> Source | None:
    """同梱している EA を読む。

    manifest に SHA-256 が書いてあれば、同梱物が途中で壊れていないかをここで確かめる。
    食い違っていたら broken を立てる。壊れたものは置かない。

    include_dir … EA が読む Include（TradingGate.mqh）の置き場。省略すると assets_dir。
    追加口座用の EA（bridge/growth/）は Include を 1 本目と共有するので、ここで bridge/ を渡す。
    """
    global EA_NAME
    ea = find_source_file(assets_dir)
    if ea is None:
        return None
    # 配る名前は、同梱している .ex5 の名前に合わせる
    EA_NAME = ea.stem

    manifest: dict[str, Any] = {}
    path = Path(assets_dir) / MANIFEST_NAME
    if path.is_file():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}

    try:
        digest = sha256_of(ea)
    except OSError as exc:  # noqa: BLE001
        return Source(ea_path=ea, version="", sha256="", includes=(), broken=f"読めない: {exc}")

    broken = ""
    expected = str(manifest.get("sha256") or "").strip().lower()
    if expected and expected != digest:
        broken = "同梱の EA が manifest と違う（壊れている可能性）"

    inc_dir = Path(include_dir) if include_dir is not None else Path(assets_dir)
    includes = tuple(inc_dir / name for name in INCLUDE_FILES if (inc_dir / name).is_file())
    missing = [name for name in INCLUDE_FILES if not (inc_dir / name).is_file()]
    if missing and not broken:
        broken = f"同梱物が足りない: {'・'.join(missing)}"

    return Source(
        ea_path=ea,
        version=str(manifest.get("version") or ""),
        sha256=digest,
        includes=includes,
        broken=broken,
    )


# ────────────────────────────────
# 置いたときの控え（.ex5 からは版を読めないため）
# ────────────────────────────────
def _record_path() -> Path:
    return _config_dir() / RECORD_NAME


def read_record(data_path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(_record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    got = raw.get(str(data_path))
    return got if isinstance(got, dict) else {}


def write_record(data_path: Path, *, version: str, digest: str) -> None:
    try:
        raw = json.loads(_record_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}
    raw[str(data_path)] = {
        "version": version,
        "sha256": digest,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        _record_path().write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


# ────────────────────────────────
# いま置かれているものの状態
# ────────────────────────────────
@dataclass
class Status:
    state: str
    installed_version: str = ""
    source_version: str = ""
    detail: str = ""

    @property
    def needs_install(self) -> bool:
        return self.state in (NOT_INSTALLED, UPDATE_AVAILABLE)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "installed_version": self.installed_version,
            "source_version": self.source_version,
            "detail": self.detail,
        }


def installed_path(data_path: Path, source: "Source | None" = None) -> Path:
    name = source.file_name if source else f"{EA_NAME}{EA_SOURCE_SUFFIX}"
    return Path(data_path) / "MQL5" / "Experts" / name


def status(data_path: Path, source: Source | None) -> Status:
    """その MT5 に置かれている EA の状態。MT5 を起動しなくても分かる。"""
    target = installed_path(data_path, source)
    src_version = source.version if source else ""
    try:
        exists = target.is_file()
    except OSError as exc:  # noqa: BLE001
        return Status(ERROR, detail=str(exc))

    if not exists:
        return Status(NOT_INSTALLED, source_version=src_version)
    if source is None:
        return Status(INSTALLED, detail="配布物が読めない")
    if not source.ok:
        return Status(ERROR, source_version=src_version, detail=source.broken)

    try:
        digest = sha256_of(target)
    except OSError as exc:  # noqa: BLE001
        return Status(ERROR, detail=str(exc))

    # 版の名前だけは控えから取る。ただし控えが「いま入っているファイル」の
    # ものであるときに限る。食い違っていれば、控えは当てにしない。
    record = read_record(Path(data_path))
    record_matches_file = record.get("sha256") == digest
    installed_version = str(record.get("version") or "") if record_matches_file else ""

    # 最新かどうかは、控えではなく実ファイルの中身で決める
    if digest == source.sha256 and _includes_are_current(Path(data_path), source):
        return Status(LATEST, installed_version=installed_version or src_version, source_version=src_version)

    detail = ""
    if not record_matches_file and record.get("sha256"):
        # Connect が置いたものと、いま入っているものが違う
        detail = "置いたあとに入れ替えられている"
    return Status(
        UPDATE_AVAILABLE, installed_version=installed_version, source_version=src_version, detail=detail
    )


def _includes_are_current(data_path: Path, source: Source) -> bool:
    """EA が読む TradingGate.mqh も揃っているか。片方だけ古いと動かない。"""
    include_dir = Path(data_path) / "MQL5" / "Include"
    for src in source.includes:
        target = include_dir / src.name
        if not target.is_file():
            return False
        try:
            if sha256_of(target) != sha256_of(src):
                return False
        except OSError:
            return False
    return True


# ────────────────────────────────
# 置く
# ────────────────────────────────
def install(
    data_path: Path,
    source: Source,
    *,
    old_names: tuple[str, ...] = (),
    force: bool = False,
    log: Callable[[str], None] = lambda _m: None,
) -> Status:
    """EA と Include を置く。中身が同じなら触らない。

    無条件の削除・上書きはしない。壊れた配布物は置かない。
    置いたあとは、もう一度ハッシュを取り直して正しく置けたかを確かめる。

    force=True のときだけ、中身が同じでも置き直す。
    お客様が「設置しなおす」を選んだときに使う（触っていないのに
    「何もしませんでした」と言われると、直っていないように見える）。
    """
    if not source.ok:
        log(f"配布物が使えないので置かない: {source.broken}")
        return Status(ERROR, source_version=source.version, detail=source.broken)

    data_root = Path(data_path)
    experts = data_root / "MQL5" / "Experts"
    include = data_root / "MQL5" / "Include"
    try:
        experts.mkdir(parents=True, exist_ok=True)
        include.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # noqa: BLE001
        return Status(ERROR, detail=str(exc))

    try:
        for src in source.includes:
            target = include / src.name
            if not force and target.is_file() and sha256_of(target) == sha256_of(src):
                continue
            shutil.copy2(src, target)
            log(f"置いた Include/{src.name}")

        target = experts / source.file_name
        if not force and target.is_file() and sha256_of(target) == source.sha256:
            log(f"そのまま Experts/{source.file_name}（中身が同じ）")
        else:
            shutil.copy2(source.ea_path, target)
            log(f"置いた Experts/{source.file_name}")
    except OSError as exc:  # noqa: BLE001
        return Status(ERROR, detail=str(exc))

    # 正しく置けたかを、置いたファイルそのものから確かめる
    try:
        placed = sha256_of(experts / source.file_name)
    except OSError as exc:  # noqa: BLE001
        return Status(ERROR, detail=str(exc))
    if placed != source.sha256:
        log("置いた EA の中身が配布物と違う")
        return Status(ERROR, source_version=source.version, detail="置いたファイルが配布物と違う")

    write_record(data_root, version=source.version, digest=placed)
    cleanup_old(experts, old_names, log=log)
    cleanup_other_versions(experts, source.file_name, log=log)
    return status(data_root, source)


def cleanup_other_versions(
    experts: Path,
    keep: str,
    *,
    log: Callable[[str], None] = lambda _m: None,
) -> list[str]:
    """いま置いたもの以外の「うちのシステム」を片づける。

    名前の後半（版）が変わると、古い版が別名で残る。
    2つ並んでいると、お客様がどちらを載せればいいか分からない。

    消すのはコンパイル済み（.ex5）だけ。ソース（.mq5）はナビゲーターに並ばないし、
    人が手で置いた作業中のものかもしれないので触らない（Mac の実機で消してしまった）。
    """
    removed: list[str] = []
    try:
        candidates = [p for p in experts.iterdir() if p.suffix.lower() == ".ex5"]
    except OSError:
        return removed
    for path in candidates:
        if path.name == keep or not is_our_ea(path.stem):
            continue
        try:
            path.unlink()
            removed.append(path.name)
            log(f"前の版を片づけ {path.name}")
        except OSError:
            log(f"片づけられない {path.name}（チャートから外してから開き直す）")
    return removed


def cleanup_old(
    experts: Path,
    old_names: tuple[str, ...],
    *,
    log: Callable[[str], None] = lambda _m: None,
) -> list[str]:
    """以前配っていた EA を片づける。チャートに載っていると消せないことがある。

    いま使っている EA（EA_NAME）は、ここには渡さないこと。
    """
    removed: list[str] = []
    for name in old_names:
        if name == EA_NAME:
            continue  # 取り違えても今の EA は消さない
        for suffix in (".mq5", ".ex5"):
            stale = experts / f"{name}{suffix}"
            if not stale.is_file():
                continue
            try:
                stale.unlink()
                removed.append(stale.name)
                log(f"片づけ {stale.name}")
            except OSError:
                log(f"片づけられない {stale.name}（チャートから外してから開き直す）")
    return removed


# MT5 が最初から入れてくるサンプルのフォルダ。ここだけを片づける。
# お客様が自分で入れた EA は、たいてい Experts の直下か、自分で作った
# フォルダに入っている。ここを触らないかぎり消えない。
SAMPLE_FOLDERS = ("Advisors", "Free Robots", "Examples")


def tidy_samples(
    data_path: Path,
    *,
    log: Callable[[str], None] = lambda _m: None,
) -> list[str]:
    """MT5 に最初から入っているサンプル EA を片づける。

    ナビゲーターにサンプルが十数個並んでいると、お客様はうちのシステムを
    見つけられない。最初から入っているものだけを消す。

    消すのは SAMPLE_FOLDERS の中だけ。Experts の直下や、それ以外の
    フォルダには触らない（お客様が別に買った EA を消さないため）。
    MT5 を入れ直すか更新すると、また入ってくることがある。
    """
    experts = Path(data_path) / "MQL5" / "Experts"
    removed: list[str] = []
    for folder_name in SAMPLE_FOLDERS:
        folder = experts / folder_name
        if not folder.is_dir():
            continue
        try:
            files = [p for p in folder.rglob("*") if p.is_file()]
        except OSError:
            continue
        # うちのシステムが紛れていたら、そのフォルダは触らない
        if any(is_our_ea(p.stem) for p in files):
            log(f"{folder_name} にうちのシステムがあるので、触りません")
            continue
        for path in files:
            try:
                path.unlink()
                removed.append(f"{folder_name}/{path.name}")
            except OSError:
                log(f"片づけられない {folder_name}/{path.name}")
        try:
            shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass
    if removed:
        log(f"最初から入っていたサンプルを {len(removed)} 個片づけました")
    return removed


def stale_source_exists(data_path: Path) -> bool:
    """以前の方式で置いた .mq5 が残っているか（コンパイル済みに移行したあとの掃除用）。"""
    experts = Path(data_path) / "MQL5" / "Experts"
    try:
        return any(is_our_ea(p.stem) for p in experts.glob("*.mq5"))
    except OSError:
        return False


def needs_compile() -> bool:
    """お客様の PC でコンパイルが要るか。コンパイル済みを配るので常に False。"""
    return EA_SOURCE_SUFFIX == ".mq5"


# ────────────────────────────────────────────────
# コンパイル済み（.ex5）から版を読む
#   MetaEditor は #property version の文字列を .ex5 の中に UTF-16 で残す。
#   ソース（.mq5）は配らないので、版はここから読むしかない。
#   読めなくても止めない（版は表示に使うだけで、更新の判定は SHA-256 で行う）。
# ────────────────────────────────────────────────
_VERSION_IN_EX5 = re.compile(r"(?<![0-9.])([0-9]{1,3}\.[0-9]{1,3})(?![0-9.])")


def version_from_ex5(path: Path) -> str:
    """.ex5 に焼き込まれている版。読めなければ空。"""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return ""
    text = raw.decode("utf-16-le", errors="ignore")
    found = _VERSION_IN_EX5.findall(text)
    return found[0] if found else ""


# ────────────────────────────────────────────────
# EA がチャートで動いているか
#   TradingGate を積んだ EA は、チャートに載っているあいだ、この控えを
#   書き直し続ける。ファイルの新しさを見るだけで「載っているか」が分かる
#   （MT5 を外から覗く手立ては無いので、これが唯一の確かめ方）。
#   置き場は Terminal/Common/Files。MT5 が何台あっても1か所に集まる。
# ────────────────────────────────────────────────
HEARTBEAT_FILE = "trelab_state.ini"
# EA は1秒ごとに書く。MT5 が忙しいときのために、少し余裕をみる
HEARTBEAT_FRESH_SEC = 90


def heartbeat_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / "MetaQuotes" / "Terminal" / "Common" / "Files" / HEARTBEAT_FILE


def heartbeat(fresh_sec: int = HEARTBEAT_FRESH_SEC, account: int | str | None = None) -> dict[str, Any]:
    """EA がいまチャートで動いているか。

    seen          … 控えがあるか（一度でも動いたか）
    fresh         … いま動いているか（account を渡したときは、その口座の EA が）
    ea / symbol   … 動いている EA の名前と、載っているチャートの銘柄
    ours / gold   … それがうちの EA か／ゴールドのチャートか（分からなければ None）
    other_account … 控えを書いたのが別の口座の MT5（控えは PC 内で1つしかない）
    """
    info: dict[str, Any] = {
        "seen": False, "fresh": False, "age": None, "ea": "", "symbol": "",
        "account": "", "ours": None, "gold": None, "other_account": False,
    }
    path = heartbeat_path()
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return info
    info["seen"] = True
    info["age"] = int(age)
    info["fresh"] = age < fresh_sec
    try:
        raw = path.read_bytes()
    except OSError:
        return info
    # MQL5 の書き出しは環境によって文字コードが変わる。読めるもので読む
    for encoding in ("utf-8", "utf-16", "cp932"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if "state=" not in text:
            continue
        for line in text.splitlines():
            key, _, value = line.partition("=")
            if key.strip() in ("ea", "symbol", "account"):
                info[key.strip()] = value.strip()
        break
    if info["ea"]:
        info["ours"] = _is_our_ea(info["ea"])
    if info["symbol"]:
        info["gold"] = _is_gold_symbol(info["symbol"])
    if account and info["account"] and str(info["account"]).strip() != str(account).strip():
        # 別の MT5 に載せた EA が書いたもの。この MT5 では動いていない
        info["other_account"] = True
        info["fresh"] = False
    return info
