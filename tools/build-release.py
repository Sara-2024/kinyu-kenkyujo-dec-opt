#!/usr/bin/env python3
"""配るもの一式を、まとめて作る（Windows で実行）。

  tools\\3_リリースする.bat  を押すだけ。

やること:
  1. EA を用意する           （bridge に .ex5 があればそのまま使う。
                              無いときだけ MetaEditor を探してコンパイルする）
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
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "bridge"
EA_NAME = "OrbitGoldEA_v11"
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


def find_mt5_data_dir() -> Path | None:
    """MT5 のデータフォルダ（MQL5 があるところ）。最後に使ったものを選ぶ。"""
    base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    if not base.is_dir():
        return None
    found = [p for p in base.iterdir() if p.is_dir() and (p / "origin.txt").is_file()]
    if not found:
        return None
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0]


def looks_like_placeholder(ex5: Path) -> str:
    """本物のコンパイル結果かどうかを、ざっくり見る。

    差し替え忘れたまま配ると、お客様の MT5 で EA が動かない。
    形式まで検めることはできないので、「明らかに違うもの」だけ弾く。
    戻り値は理由（空なら、少なくとも見た目は本物）。
    """
    size = ex5.stat().st_size
    if size < 10_000:
        return f"小さすぎる（{size:,} バイト）。本物は数十KB以上ある"
    head = ex5.read_bytes()[:4096]
    try:
        text = head.decode("ascii")
    except UnicodeDecodeError:
        return ""
    if text.isprintable() or "PLACEHOLDER" in text.upper():
        return "中身がただの文字（コンパイル結果ではない）"
    return ""


def read_compile_log(mq5: Path) -> str:
    """MetaEditor が残した記録。文字コードは環境で変わる。"""
    for path in (mq5.with_suffix(".log"), mq5.parent / f"{mq5.stem}.log"):
        if not path.is_file():
            continue
        for encoding in ("utf-16", "utf-8", "cp932"):
            try:
                return path.read_text(encoding=encoding, errors="ignore")
            except (OSError, UnicodeError):
                continue
    return ""


def compile_ea() -> Path:
    r"""MT5 のフォルダを借りてコンパイルし、できた .ex5 を bridge へ持ち帰る。

    EA は `#include <TradingGate.mqh>` と書いてある。山かっこの include は
    MT5 の Include フォルダを見に行くので、bridge の中だけではコンパイルできない。
    お客様の PC に配るときと同じ置き方（MQL5\Experts と MQL5\Include）にしてから
    コンパイルする。これは以前から動いていたやり方。
    """
    mq5_src = BRIDGE / f"{EA_NAME}.mq5"
    mqh_src = BRIDGE / "TradingGate.mqh"
    ex5_out = BRIDGE / f"{EA_NAME}.ex5"

    # すでに .ex5 があるなら、それを配る。コンパイルはしない。
    # 自分でコンパイルしたものを bridge に置いたときは、そのまま使われる。
    # 作り直したいときだけ、--compile を付けて実行する。
    if ex5_out.is_file() and "--compile" not in sys.argv:
        ok(f"{ex5_out.name} をそのまま使います（{ex5_out.stat().st_size:,} バイト）")
        print("     作り直したいときは tools\\3_リリースする.bat --compile")
        return ex5_out

    # ここへ来たのは .ex5 が無いとき。ソース（.mq5）は配らないので、
    # ふつうは手元にも無い。その場合は入れ替えの道具へ案内する。
    if not mq5_src.is_file():
        die(
            "配る EA がありません",
            "  2_EAを入れ替える.bat を押して、コンパイル済みの .ex5 を入れてください。",
            "  （.ex5 をそのファイルにドラッグしても入ります）",
        )
    if not mqh_src.is_file():
        die(f"{mqh_src.name} がありません", "リポジトリを取り直してください。")

    editor = find_metaeditor()
    if editor is None:
        die(
            "MetaEditor（metaeditor64.exe）が見つかりません",
            f"  MT5 で bridge\\{EA_NAME}.mq5 を開いてコンパイルし、",
            "  できた .ex5 を 2_EAを入れ替える.bat に入れてください。",
        )
    ok(f"MetaEditor: {editor}")

    data = find_mt5_data_dir()
    if data is None:
        die(
            "MT5 のデータフォルダが見つかりません",
            "MT5 を一度起動してログインしてから、もう一度お試しください。",
        )
    ok(f"MT5 のフォルダ: {data}")

    experts = data / "MQL5" / "Experts"
    include = data / "MQL5" / "Include"
    experts.mkdir(parents=True, exist_ok=True)
    include.mkdir(parents=True, exist_ok=True)

    mq5 = experts / mq5_src.name
    ex5 = experts / f"{EA_NAME}.ex5"
    shutil.copy2(mqh_src, include / mqh_src.name)
    shutil.copy2(mq5_src, mq5)
    if ex5.is_file():
        try:
            ex5.unlink()  # 消してから作る（できたかどうかで成否が分かる）
        except OSError:
            die(f"{ex5} を消せません", "MT5 のチャートから EA を外してから、もう一度お試しください。")

    print(f"  … コンパイル中（{mq5.name}）")
    try:
        subprocess.run([str(editor), f"/compile:{mq5}", "/log"], timeout=240, capture_output=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        die(f"コンパイルを実行できませんでした: {exc}")

    for _ in range(120):
        if ex5.is_file():
            break
        time.sleep(0.25)

    if not ex5.is_file():
        tail = read_compile_log(mq5)
        lines = [ln for ln in tail.splitlines() if ln.strip()][-12:]
        die(
            "コンパイルできませんでした",
            "MetaEditor の記録:",
            *[f"  | {ln}" for ln in lines] or ["  （記録が読めませんでした）"],
        )

    shutil.copy2(ex5, ex5_out)
    ok(f"{ex5_out.name} を作りました（{ex5_out.stat().st_size:,} バイト）")
    return ex5_out


# ────────────────────────────────
# 2. 控えを作る
# ────────────────────────────────
def make_manifest(ex5: Path) -> dict:
    digest = hashlib.sha256(ex5.read_bytes()).hexdigest()
    version = ""

    # ① ソースがあれば、そこから読む
    mq5 = BRIDGE / f"{EA_NAME}.mq5"
    if mq5.is_file():
        found = VERSION_RE.search(mq5.read_text(encoding="utf-8", errors="ignore")[:4000])
        if found:
            version = found.group(1)

    # ② 無ければ、前の控えを使う（いまの .ex5 と同じものなら、版も同じ）
    #    配るのは .ex5 だけで、ソースは手元に無いのがふつう
    if not version:
        old = BRIDGE / "ea_manifest.json"
        if old.is_file():
            try:
                raw = json.loads(old.read_text(encoding="utf-8"))
                if str(raw.get("sha256", "")).lower() == digest:
                    version = str(raw.get("version") or "")
            except (OSError, ValueError):
                pass

    # ③ それでも分からなければ聞く
    if not version:
        print("  EA の版が分かりません（ソースが無く、控えとも中身が違います）")
        version = input("  版を入れてください（例 11.00）: ").strip()
        if not version:
            die("版が入っていません", "  もう一度実行して、版を入れてください。")
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
def stop_running() -> None:
    """裏で動いているブリッジを止める。

    動いたままだと dist\\AITrader.exe を掴んでいて、作り直せない
    （PermissionError: アクセスが拒否されました）。
    """
    exe = ROOT / "dist" / "AITrader.exe"
    if not exe.is_file():
        return
    try:
        subprocess.run([str(exe), "--stop"], timeout=60, capture_output=True)
        print("  … 動いていたものを止めました")
    except (OSError, subprocess.TimeoutExpired):
        pass
    time.sleep(2)


def build_exe() -> Path:
    bat = ROOT / "tools" / "build-windows.bat"
    if not bat.is_file():
        die(f"{bat} がありません")
    stop_running()
    print("  … ビルド中（数分かかります）")
    result = subprocess.run([str(bat), "--from-release"], cwd=str(ROOT), shell=True)
    exe = ROOT / "dist" / "AITrader.exe"
    if result.returncode != 0 or not exe.is_file():
        die(
            "接続ツールを作れませんでした",
            "  「アクセスが拒否されました」と出ていたら、まだ動いています。",
            "  tools\\停止する.bat を押してから、もう一度実行してください。",
            "  それ以外なら、上に出ている PyInstaller の記録を見てください。",
        )
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


def install_iscc() -> Path | None:
    """Inno Setup を winget で入れる。英語の画面は出ない。"""
    print("  … Inno Setup を入れています（数分かかります）")
    cmd = [
        "winget", "install", "JRSoftware.InnoSetup", "-e",
        "--accept-package-agreements", "--accept-source-agreements",
    ]
    try:
        subprocess.run(cmd, timeout=900, shell=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  － 入れられませんでした（{exc}）")
        return None
    return find_iscc()


def build_installer() -> Path | None:
    iscc = find_iscc()
    iss = ROOT / "tools" / "AITraderConnect.iss"
    if iscc is None:
        print("  － Inno Setup が入っていません（お客様に渡すインストーラーを作る道具）")
        answer = input("     いま入れますか？ (Y/n): ").strip().lower()
        if answer in ("", "y", "yes"):
            iscc = install_iscc()
        if iscc is None:
            print("  － 飛ばします。手で入れるときは:")
            print("       winget install JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements")
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
def place(exe: Path, placeholder: str) -> None:
    if placeholder:
        print(f"  ！ 配る場所へは置きません（{placeholder}）")
        print("     本物の .ex5 に差し替えてから、もう一度実行してください。")
        print("     ここまでの exe とインストーラーは、配線の確認には使えます。")
        return
    target = ROOT / "public" / "download" / "AITrader.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.stat().st_size if target.is_file() else 0
    target.write_bytes(exe.read_bytes())
    ok(f"public\\download\\AITrader.exe を置き換えました（{before:,} → {target.stat().st_size:,} バイト）")


def main() -> int:
    print("=" * 62)
    print("  AI Trader Connect を作る")
    print("=" * 62)

    step("EA を用意する")
    ex5 = compile_ea()
    placeholder = looks_like_placeholder(ex5)
    if placeholder:
        print()
        print("  " + "!" * 56)
        print(f"  ！ この .ex5 は本物ではありません: {placeholder}")
        print("  ！ 配線の確認にだけ使えます。お客様には配らないでください。")
        print("  " + "!" * 56)

    step("版と中身の控えを作る")
    manifest = make_manifest(ex5)

    step("接続ツールをビルドする")
    exe = build_exe()

    step("インストーラーを作る")
    installer = build_installer()

    step("配る場所へ置く")
    place(exe, placeholder)

    print()
    print("=" * 62)
    print("  できました")
    print("=" * 62)
    print(f"  EA          : bridge\\{EA_NAME}.ex5（版 {manifest['version']}）")
    print("  接続ツール  : dist\\AITrader.exe")
    if installer:
        print(f"  インストーラー: {installer}")
    print()
    if placeholder:
        print("  ！ いまの .ex5 は本物ではありません。配る前に必ず差し替えること。")
        print()
    print("  次にやること:")
    print("    1. tools\\4_確認する.bat で、このPCの状態を見る")
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
