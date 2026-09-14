#!/usr/bin/env python3
"""配る EA（.ex5）を入れ替える。

  tools\\2_EAを入れ替える.bat  を押す（または .ex5 をこの bat にドラッグする）

やること:
  1. 入れ替える .ex5 を選ぶ（ドラッグしていればそれを使う）
  2. bridge\\3YumekkuEA_win.ex5 に置く
  3. 控え（ea_manifest.json）を作り直す

名前は 3YumekkuEA_win.ex5 に揃える。選んだファイルの名前が違っていても構わない。
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
EA_NAME = "3YumekkuEA_win"
TARGET = BRIDGE / f"{EA_NAME}.ex5"
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


def describe(path: Path) -> str:
    if not path.is_file():
        return "（無い）"
    size = path.stat().st_size
    note = "  ← 本物ではありません" if size < 10_000 else ""
    return f"{size:,} バイト / {sha256_of(path)[:12]}…{note}"


def main() -> int:
    print("=" * 62)
    print("  EA を入れ替える")
    print("=" * 62)
    print()
    print(f"  いま入っているもの: {describe(TARGET)}")
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
    if src.resolve() == TARGET.resolve():
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
    shutil.copy2(src, TARGET)

    # 控えを作り直す（版は .mq5 から読む。.ex5 からは読めない）
    mq5 = BRIDGE / f"{EA_NAME}.mq5"
    version = ""
    if mq5.is_file():
        found = VERSION_RE.search(mq5.read_text(encoding="utf-8", errors="ignore")[:4000])
        if found:
            version = found.group(1)
    if not version:
        version = input("  EA の版を入れてください（例 6.10）: ").strip() or "0"

    manifest = {
        "ea": EA_NAME,
        "file": TARGET.name,
        "version": version,
        "sha256": sha256_of(TARGET),
        "size": TARGET.stat().st_size,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (BRIDGE / "ea_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    print()
    print(f"  ✓ 入れ替えました: {src.name}")
    print(f"    {describe(TARGET)}")
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
