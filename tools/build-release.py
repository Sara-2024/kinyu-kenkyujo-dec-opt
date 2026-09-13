#!/usr/bin/env python3
"""配るもの一式を、まとめて作る（Windows で実行）。

  tools\\リリースする.bat  を押すだけ。

やること:
  1. EA をコンパイルする     （MetaEditor を自動で探して呼ぶ。手で開かなくてよい）
  2. 版と中身の控えを作る    （ea_manifest.json）
  3. 接続ツールをビルドする  （AITrader.exe）
  4. インストーラーを作る    （Inno Setup。入っていなければ飛ばす）
  5. 配布用の置き場へコピー  （public\\download\\AITrader.exe）

途中で失敗したら、そこで止めて「何をすればいいか」を出す。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "bridge"
EA_NAME = "OrbitGoldEA_v6"
VERSION_RE = re.compile(r'#property\s+version\s+"([^"]+)"')

STEP = 0


def step(title: str) -> None:
    global STEP
    STEP += 1
    print()
    print(f"[{STEP}/5] {title}")


def die(message: str, *hints: str) -> None:
    print()
    print(f"  ✕ {message}")
    for hint in hints:
        print(f"    {hint}")
    print()
    sys.exit(1)


def ok(message: str) -> None:
    print(f"  ✓ {message}")


# ────────────────────────────────
# 1. EA をコンパイルする
# ────────────────────────────────
def find_metaeditor() -> Path | None:
    """MetaEditor を探す。MT5 のデータフォルダ（origin.txt）→ Program Files の順。"""
    seen: list[Path] = []
    base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    if base.is_dir():
        for entry in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
            origin = entry / "origin.txt"
            if not origin.is_file():
                continue
            for encoding in ("utf-16", "utf-8"):
                try:
                    line = origin.read_text(encoding=encoding, errors="ignore").strip().splitlines()[0]
                except (OSError, UnicodeError, IndexError):
                    continue
                folder = Path(line.strip().strip('"'))
                if (folder / "metaeditor64.exe").is_file():
                    seen.append(folder / "metaeditor64.exe")
                break
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = Path(os.environ.get(key, ""))
        if not root.is_dir():
            continue
        try:
            seen.extend(root.glob("*/metaeditor64.exe"))
        except OSError:
            pass
    return seen[0] if seen else None


def compile_ea() -> Path:
    mq5 = BRIDGE / f"{EA_NAME}.mq5"
    ex5 = BRIDGE / f"{EA_NAME}.ex5"
    if not mq5.is_file():
        die(f"{mq5} がありません")

    editor = find_metaeditor()
    if editor is None:
        if ex5.is_file():
            ok(f"MetaEditor は見つからないが、{ex5.name} はすでにある（そのまま使う）")
            return ex5
        die(
            "MetaEditor（metaeditor64.exe）が見つかりません",
            "MT5 を一度起動してから、もう一度お試しください。",
            "それでも見つからなければ、MT5 の F4 で MetaEditor を開き、",
            f"  bridge\\{EA_NAME}.mq5 を F7 でコンパイルしてから、また実行してください。",
        )
    ok(f"MetaEditor: {editor}")

    before = ex5.stat().st_mtime_ns if ex5.is_file() else 0
    # Include も同じフォルダから読ませる
    log = BRIDGE / "compile.log"
    cmd = [str(editor), f"/compile:{mq5}", f"/inc:{BRIDGE}", f"/log:{log}"]
    print(f"  … コンパイル中（{mq5.name}）")
    try:
        subprocess.run(cmd, timeout=180, capture_output=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        die(f"コンパイルを実行できませんでした: {exc}")

    if not ex5.is_file() or ex5.stat().st_mtime_ns == before:
        tail = ""
        if log.is_file():
            for encoding in ("utf-16", "utf-8", "cp932"):
                try:
                    tail = "\n      ".join(log.read_text(encoding=encoding, errors="ignore").strip().splitlines()[-8:])
                    break
                except (OSError, UnicodeError):
                    continue
        die("コンパイルできませんでした", f"MetaEditor の記録:\n      {tail}" if tail else "")
    if log.is_file():
        log.unlink(missing_ok=True)
    ok(f"{ex5.name} を作りました（{ex5.stat().st_size:,} バイト）")
    return ex5


# ────────────────────────────────
# 2. 控えを作る
# ────────────────────────────────
def make_manifest(ex5: Path) -> dict:
    mq5 = BRIDGE / f"{EA_NAME}.mq5"
    version = ""
    if mq5.is_file():
        found = VERSION_RE.search(mq5.read_text(encoding="utf-8", errors="ignore")[:4000])
        if found:
            version = found.group(1)
    if not version:
        die("EA の版（#property version）を読めませんでした")

    digest = hashlib.sha256(ex5.read_bytes()).hexdigest()
    manifest = {
        "ea": EA_NAME,
        "file": ex5.name,
        "version": version,
        "sha256": digest,
        "size": ex5.stat().st_size,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (BRIDGE / "ea_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    ok(f"版 {version} ／ SHA-256 {digest[:16]}…")
    return manifest


# ────────────────────────────────
# 3. 接続ツール
# ────────────────────────────────
def build_exe() -> Path:
    bat = ROOT / "tools" / "build-windows.bat"
    if not bat.is_file():
        die(f"{bat} がありません")
    print("  … ビルド中（数分かかります）")
    result = subprocess.run([str(bat)], cwd=str(ROOT), shell=True)
    exe = ROOT / "dist" / "AITrader.exe"
    if result.returncode != 0 or not exe.is_file():
        die("接続ツールを作れませんでした", "上に出ている PyInstaller の記録を見てください。")
    ok(f"AITrader.exe（{exe.stat().st_size:,} バイト）")
    return exe


# ────────────────────────────────
# 4. インストーラー
# ────────────────────────────────
def find_iscc() -> Path | None:
    for key in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        root = Path(os.environ.get(key, ""))
        for name in ("Inno Setup 6", "Inno Setup 5"):
            candidate = root / name / "ISCC.exe"
            if candidate.is_file():
                return candidate
    return None


def build_installer() -> Path | None:
    iscc = find_iscc()
    iss = ROOT / "tools" / "AITraderConnect.iss"
    if iscc is None:
        print("  － Inno Setup が入っていないので飛ばします")
        print("     https://jrsoftware.org/isdl.php から入れると、次からここも自動になります")
        return None
    print(f"  … {iscc.name} で作成中")
    result = subprocess.run([str(iscc), str(iss)], cwd=str(ROOT / "tools"), capture_output=True, text=True)
    out = ROOT / "tools" / "installer" / "AITraderConnect-Setup.exe"
    if result.returncode != 0 or not out.is_file():
        tail = "\n      ".join((result.stdout or result.stderr or "").strip().splitlines()[-8:])
        die("インストーラーを作れませんでした", f"記録:\n      {tail}" if tail else "")
    ok(f"{out.name}（{out.stat().st_size:,} バイト）")
    return out


# ────────────────────────────────
# 5. 配る場所へ
# ────────────────────────────────
def place(exe: Path) -> None:
    target = ROOT / "public" / "download" / "AITrader.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.stat().st_size if target.is_file() else 0
    target.write_bytes(exe.read_bytes())
    ok(f"public\\download\\AITrader.exe を置き換えました（{before:,} → {target.stat().st_size:,} バイト）")


def main() -> int:
    print("=" * 62)
    print("  AI Trader Connect を作る")
    print("=" * 62)

    step("EA をコンパイルする")
    ex5 = compile_ea()

    step("版と中身の控えを作る")
    manifest = make_manifest(ex5)

    step("接続ツールをビルドする")
    exe = build_exe()

    step("インストーラーを作る")
    installer = build_installer()

    step("配る場所へ置く")
    place(exe)

    print()
    print("=" * 62)
    print("  できました")
    print("=" * 62)
    print(f"  EA          : bridge\\{EA_NAME}.ex5（版 {manifest['version']}）")
    print("  接続ツール  : dist\\AITrader.exe")
    if installer:
        print(f"  インストーラー: {installer}")
    print()
    print("  次にやること:")
    print("    1. tools\\確認する.bat で、このPCの状態を見る")
    print("    2. リリース手順.md の実機テスト A〜E を行う")
    print("    3. 問題なければ、下の3つをコミットして push する")
    print(f"         bridge\\{EA_NAME}.ex5")
    print("         bridge\\ea_manifest.json")
    print("         public\\download\\AITrader.exe")
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
