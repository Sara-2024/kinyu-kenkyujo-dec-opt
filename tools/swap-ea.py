#!/usr/bin/env python3
"""配る EA（.ex5）を入れ替える。

  tools\\2_EAを入れ替える.bat  を押す（または .ex5 をこの bat にドラッグする）

やること:
  1. 入れ替える .ex5 を選ぶ（ドラッグしていればそれを使う）
  2. bridge\\ に置く（名前はそのまま）
  3. 控え（ea_manifest.json）を作り直す

選んだファイルの名前をそのまま使う（MT5 の一覧に出る名前になる）。
前に入れていたものは片づけるので、2つ並ぶことはない。
入れ替えたら 3_リリースする.bat を押す。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "bridge"
sys.path.insert(0, str(BRIDGE))
from ea_manager import version_from_ex5  # noqa: E402  .ex5 から版を読む


def current_ex5() -> Path | None:
    """いま同梱している EA。名前は変わりうるので Yumekku で探す。"""
    found = [p for p in BRIDGE.glob("*.ex5") if "yumekku" in p.stem.lower()]
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None
VERSION_RE = re.compile(r'#property\s+version\s+"([^"]+)"')


def die(message: str, *hints: str) -> None:
    print()
    print(f"  ✕ {message}")
    for hint in hints:
        print(f"    {hint}")
    print()
    input("  閉じるには Enter を押してください...")
    sys.exit(1)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pick_file() -> Path | None:
    """ファイルを選ぶ窓を出す。出せない環境では None。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:  # noqa: BLE001
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        chosen = filedialog.askopenfilename(
            title="入れ替える EA（.ex5）を選んでください",
            filetypes=[("EA ファイル", "*.ex5"), ("すべて", "*.*")],
            initialdir=str(Path.home() / "Downloads"),
        )
        root.destroy()
    except Exception:  # noqa: BLE001
        return None
    return Path(chosen) if chosen else None


def describe(path: Path | None) -> str:
    if path is None or not path.is_file():
        return "（無い）"
    size = path.stat().st_size
    note = "  ← 本物ではありません" if size < 10_000 else ""
    return f"{size:,} バイト / {sha256_of(path)[:12]}…{note}"


def main() -> int:
    print("=" * 62)
    print("  EA を入れ替える")
    print("=" * 62)
    print()
    before = current_ex5()
    print(f"  いま入っているもの: {before.name if before else '（無い）'} {describe(before) if before else ''}")
    print()

    args = [a for a in sys.argv[1:] if a.strip()]
    src = Path(args[0]) if args else pick_file()
    if src is None:
        die("ファイルを選べませんでした", f"入れ替えたい .ex5 を、この bat にドラッグしても構いません。")
    if not src.is_file():
        die(f"そのファイルが見つかりません: {src}")
    if src.suffix.lower() != ".ex5":
        die(
            f"これは .ex5 ではありません: {src.name}",
            "MetaEditor で F7 を押してできる .ex5 を選んでください。",
        )
    if before is not None and src.resolve() == before.resolve():
        die("いま入っているものと同じファイルです")

    size = src.stat().st_size
    if size < 10_000:
        print(f"  ！ 選んだファイルは {size:,} バイトしかありません。")
        print("     本物のコンパイル結果ではない可能性があります（配線の確認用なら、このまま進めて構いません）")
        if input("     このまま入れ替えますか？ (y/N): ").strip().lower() != "y":
            print("  やめました")
            input("  閉じるには Enter を押してください...")
            return 1

    BRIDGE.mkdir(parents=True, exist_ok=True)
    target = BRIDGE / src.name
    shutil.copy2(src, target)

    # 前の版は片づける。2つ並んでいると、どちらを配るのか分からなくなる
    for old in BRIDGE.glob("*.ex5"):
        if "yumekku" in old.stem.lower() and old.resolve() != target.resolve():
            old.unlink()
            print(f"  前の版を片づけました: {old.name}")

    # 版は .ex5 そのものから読む（ソースは配らないので .mq5 は無い）
    version = version_from_ex5(target)
    if not version:
        version = input("  EA の版を入れてください（例 6.10）: ").strip() or "0"

    manifest = {
        "ea": target.stem,
        "file": target.name,
        "version": version,
        "sha256": sha256_of(target),
        "size": target.stat().st_size,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (BRIDGE / "ea_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    print()
    print(f"  ✓ 入れ替えました: {target.name}")
    print(f"    {describe(target)}")
    print(f"    版 {version}")
    print()
    print("  次は  3_リリースする.bat  を押してください。")
    print()
    input("  閉じるには Enter を押してください...")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
