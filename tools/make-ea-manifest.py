#!/usr/bin/env python3
"""配る EA（コンパイル済み .ex5）の控えを作る。

Windows で MetaEditor を使って YumekkuEA_win.mq5 をコンパイルしたあと、
できた .ex5 を bridge/ に置いてから、これを一度実行する。

    py -3 tools\\make-ea-manifest.py

やること:
  1. bridge/YumekkuEA_win.ex5 の SHA-256 を取る
  2. bridge/YumekkuEA_win.mq5 から版（#property version）を読む
  3. bridge/ea_manifest.json に書く

この manifest は exe に同梱され、お客様の PC で
  ・配布物が途中で壊れていないか
  ・すでに入っている EA と中身が違うか（＝更新が要るか）
  ・入っている版は何か
を確かめるのに使う。

.ex5 は毎回コンパイルすると中身が変わることがある。中身が変われば
「更新あり」と判定されて置き直されるだけなので、動作上の問題はない。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "bridge"
sys.path.insert(0, str(BRIDGE))
from ea_manager import version_from_ex5  # noqa: E402  .ex5 から版を読む

EA_NAME = "YumekkuEA_win"
VERSION_RE = re.compile(r'#property\s+version\s+"([^"]+)"')


def find_ex5() -> Path | None:
    """同梱の EA を探す。名前の後半は変わりうるので Yumekku で探す。"""
    found = [p for p in BRIDGE.glob("*.ex5") if "yumekku" in p.stem.lower()]
    if not found:
        return None
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0]


def main() -> int:
    ex5 = find_ex5() or (BRIDGE / f"{EA_NAME}.ex5")
    mq5 = ex5.with_suffix(".mq5")

    if not ex5.is_file():
        print(f"[ERROR] {ex5} がありません。")
        print("        MetaEditor で F7（コンパイル）を押してできた .ex5 を")
        print("        bridge\\ に置いてから、もう一度実行してください。")
        return 1

    digest = hashlib.sha256(ex5.read_bytes()).hexdigest()

    # 版は .ex5 そのものから読む（ソースは配らないので、普通は .mq5 が無い）
    version = version_from_ex5(ex5)
    if not version and mq5.is_file():
        found = VERSION_RE.search(mq5.read_text(encoding="utf-8", errors="ignore")[:4000])
        if found:
            version = found.group(1)
    if not version:
        print(f"[WARN] 版が読めませんでした（{ex5.name}）。")
        version = input("      版を手で入力してください（例 6.10）: ").strip() or "0"

    manifest = {
        "ea": ex5.stem,
        "file": ex5.name,
        "version": version,
        "sha256": digest,
        "size": ex5.stat().st_size,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    out = BRIDGE / "ea_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"  EA      : {ex5.name}（{manifest['size']:,} バイト）")
    print(f"  版      : {version}")
    print(f"  SHA-256 : {digest}")
    print(f"  書いた  : {out}")
    print()
    print("  この .ex5 と ea_manifest.json をコミットしてから、")
    print("  tools\\build-windows.bat で exe を作り直してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
