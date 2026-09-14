#!/usr/bin/env python3
"""MT5 のログに何が書いてあるかを、そのまま見せる（原因調べ用）。

    tools\\開発用\\ログを見る.bat

口座番号が選択画面に出ないとき、ログの場所と中身を確かめるために使う。
出た内容をそのまま送ってもらう。ログイン情報（パスワード）は出さない。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge"))

import mt5_detect  # noqa: E402

print("=" * 62)
print("  MT5 のログを見る")
print("=" * 62)

for t in mt5_detect.list_terminals():
    print()
    print(f"── {t.label}")
    print(f"   データ: {t.data_path}")
    print(f"   入れ先: {t.install_dir}")
    for folder in (t.data_path / "logs", (t.install_dir / "logs") if t.install_dir else None):
        if folder is None:
            continue
        if not folder.is_dir():
            print(f"   {folder} … 無い")
            continue
        try:
            files = sorted(folder.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError as exc:
            print(f"   {folder} … 読めない（{exc}）")
            continue
        print(f"   {folder} … {len(files)} 個")
        for path in files[:1]:
            raw = path.read_bytes()[:4000]
            print(f"     新しいもの: {path.name}（{path.stat().st_size:,} バイト）")
            print(f"     先頭のバイト: {raw[:24]!r}")
            for enc in ("utf-8", "utf-16-le", "utf-16", "cp932"):
                try:
                    text = raw.decode(enc, errors="ignore")
                except Exception:  # noqa: BLE001
                    continue
                lines = [ln for ln in text.splitlines() if ln.strip()][:4]
                marker = "★" if ("Network" in text or "authorized" in text) else "  "
                print(f"     {marker} {enc}:")
                for ln in lines:
                    print(f"         {ln[:110]}")
    print(f"   いまの判定: {mt5_detect.account_hint(t.data_path)}")

print()
print("=" * 62)
print("  この画面をそのまま送ってください")
print("=" * 62)
