"""EA の状態を見て、必要なときだけ置き直す。

置く場所も EA の名前も、これまでと同じ（MQL5/Experts/OrbitGoldEA_v6.mq5）。
すでに使っているお客様のチャート設定を動かさないため、今回は変えない。

状態は5つ:
  NOT_INSTALLED     … まだ置かれていない
  LATEST            … 置かれていて、中身も配布物と同じ
  UPDATE_AVAILABLE  … 置かれているが中身が古い
  INSTALLED         … 置かれているが、配布物と比べられない（同梱物が無い等）
  ERROR             … フォルダが読めない等

いまは .mq5 を配って現地の MetaEditor でコンパイルしている。
将来 .ex5（コンパイル済み）に切り替えるときは、

  ・EA_SOURCE_SUFFIX を ".ex5" にする
  ・ea_manifest.json に版を書く（.ex5 からは #property version を読めないため）

の2点で済むようにしてある。判定も設置もここだけを見ている。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from mt5_terminal import EA_NAMES
except ImportError:  # pragma: no cover
    from .mt5_terminal import EA_NAMES  # type: ignore

NOT_INSTALLED = "NOT_INSTALLED"
INSTALLED = "INSTALLED"
UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
LATEST = "LATEST"
ERROR = "ERROR"

EA_NAME = EA_NAMES[0]
# いま配っている形式。コンパイル済みに切り替えるときはここを ".ex5" にする
EA_SOURCE_SUFFIX = ".mq5"
INCLUDE_FILES = ("TradingGate.mqh",)
# 版と中身の照合表。.ex5 を配るようになったら同梱する（無くても動く）
MANIFEST_NAME = "ea_manifest.json"

_VERSION_RE = re.compile(r'#property\s+version\s+"([^"]+)"')


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_from_source(path: Path) -> str:
    """.mq5 なら #property version を読む。.ex5 では読めないので空を返す。"""
    if path.suffix.lower() != ".mq5":
        return ""
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError:
        return ""
    found = _VERSION_RE.search(head)
    return found.group(1) if found else ""


@dataclass
class Source:
    """配布物側（exe に同梱している EA）。"""

    ea_path: Path
    version: str
    sha256: str
    includes: tuple[Path, ...]

    @property
    def file_name(self) -> str:
        return self.ea_path.name


def load_source(assets_dir: Path) -> Source | None:
    """同梱している EA を読む。無ければ None（置くものが無い）。"""
    ea = assets_dir / f"{EA_NAME}{EA_SOURCE_SUFFIX}"
    if not ea.is_file():
        return None
    manifest: dict[str, Any] = {}
    path = assets_dir / MANIFEST_NAME
    if path.is_file():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    version = str(manifest.get("version") or "") or _version_from_source(ea)
    includes = tuple(assets_dir / name for name in INCLUDE_FILES if (assets_dir / name).is_file())
    return Source(ea_path=ea, version=version, sha256=sha256_of(ea), includes=includes)


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


def status(data_path: Path, source: Source | None) -> Status:
    """その MT5 に置かれている EA の状態。MT5 を起動しなくても分かる。"""
    experts = Path(data_path) / "MQL5" / "Experts"
    target = experts / f"{EA_NAME}{EA_SOURCE_SUFFIX}"
    src_version = source.version if source else ""
    try:
        exists = target.is_file()
    except OSError as exc:  # noqa: BLE001
        return Status(ERROR, detail=str(exc))

    if not exists:
        return Status(NOT_INSTALLED, source_version=src_version)
    if source is None:
        return Status(INSTALLED, installed_version=_version_from_source(target), detail="配布物が読めない")

    try:
        same = sha256_of(target) == source.sha256
    except OSError as exc:  # noqa: BLE001
        return Status(ERROR, detail=str(exc))

    installed_version = _version_from_source(target)
    if same and _includes_are_current(Path(data_path), source):
        return Status(LATEST, installed_version=installed_version, source_version=src_version)
    return Status(UPDATE_AVAILABLE, installed_version=installed_version, source_version=src_version)


def _includes_are_current(data_path: Path, source: Source) -> bool:
    """EA が読む TradingGate.mqh も揃っているか。片方だけ古いと動かない。"""
    include_dir = data_path / "MQL5" / "Include"
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


def install(
    data_path: Path,
    source: Source,
    *,
    old_names: tuple[str, ...] = (),
    log: Callable[[str], None] = lambda _m: None,
) -> Status:
    """EA と Include を置く。すでに入っていても、中身が同じなら触らない。

    無条件の削除・上書きはしない。古い版の EA だけ、名前で指定されたものを片づける。
    """
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
            if target.is_file() and sha256_of(target) == sha256_of(src):
                continue
            shutil.copy2(src, target)
            log(f"置いた Include/{src.name}")

        target = experts / source.file_name
        if not (target.is_file() and sha256_of(target) == source.sha256):
            shutil.copy2(source.ea_path, target)
            log(f"置いた Experts/{source.file_name}")
        else:
            log(f"そのまま Experts/{source.file_name}（中身が同じ）")
    except OSError as exc:  # noqa: BLE001
        return Status(ERROR, detail=str(exc))

    cleanup_old(experts, old_names, log=log)
    return status(data_root, source)


def cleanup_old(
    experts: Path,
    old_names: tuple[str, ...],
    *,
    log: Callable[[str], None] = lambda _m: None,
) -> list[str]:
    """以前配っていた EA を片づける。チャートに載っていると消せないことがある。"""
    removed: list[str] = []
    for name in old_names:
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


def compiled_exists(data_path: Path) -> bool:
    """コンパイル済み（.ex5）が置かれているか。MT5 が実際に動かすのはこちら。"""
    return (Path(data_path) / "MQL5" / "Experts" / f"{EA_NAME}.ex5").is_file()


def needs_compile() -> bool:
    """いま配っているのが .mq5 なら、現地でコンパイルが要る。"""
    return EA_SOURCE_SUFFIX == ".mq5"
