#!/usr/bin/env python3
"""このPCがいまどうなっているかを、まとめて見る（実機テスト用）。

  tools\\4_確認する.bat  を押すだけ。

リリース手順.md の A・B・D・E で「見るところ」と書いてあるもののうち、
機械で見られるものを全部出す。judge の欄に ✓ か ✕ が出るので、
✕ があればそこを報告する。

何も書き換えない。読むだけ。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge"))

RELAY = "https://kinyu-relay.onrender.com/health"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAMES = ("AIトレーダー", "TrelabConnect")


def config_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / "AITrader"


def head(title: str) -> None:
    print()
    print(f"── {title} " + "─" * max(0, 46 - len(title)))


def row(label: str, value: str, judge: str = "") -> None:
    mark = f"  {judge}" if judge else ""
    print(f"  {label:<26} {value}{mark}")


def read_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def startup_entries() -> list[tuple[str, str]]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    out: list[tuple[str, str]] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            for name in RUN_NAMES:
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                    out.append((name, str(value)))
                except OSError:
                    continue
    except OSError:
        pass
    return out


def protocol_command() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\aitrader\shell\open\command") as key:
            value, _ = winreg.QueryValueEx(key, None)
            return str(value)
    except OSError:
        return ""


def exe_of(command: str) -> Path | None:
    """レジストリのコマンドから、実行ファイルの場所だけ取り出す。"""
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        path = command[1:end] if end > 0 else command.strip('"')
    else:
        path = command.split(" ")[0]
    try:
        return Path(path)
    except (OSError, ValueError):
        return None


def points_here(command: str) -> tuple[bool, str]:
    """その登録が、いま使っているアプリを指しているか。

    フォルダ名の一部が一致するだけでは駄目（kinyu-kenkyujo-dec-opt は
    kinyu-kenkyujo-dec-opt-main の一部でもある）。実行ファイルの場所が、
    インストール先か、このリポジトリの中にあるかで見る。
    """
    exe = exe_of(command)
    if exe is None:
        return False, "読めません"

    def norm(path: Path | str) -> str:
        return os.path.normcase(os.path.normpath(str(path)))

    target = norm(exe)
    installed = Path(os.environ.get("LOCALAPPDATA", "")) / "AITraderConnect"
    for base, label in ((installed, "インストール先"), (ROOT, "このフォルダ")):
        head = norm(base)
        # 「〜の中にあるか」。前方一致だけで見ないこと。
        # kinyu-kenkyujo-dec-opt は kinyu-kenkyujo-dec-opt-main の前方一致でもある
        if target == head or target.startswith(head + os.sep):
            return True, f"{label}（{exe.name}）"
    return False, f"別の場所（{exe.parent.name}\\{exe.name}）"


def _process_lines() -> list[str]:
    """動いているプログラムの一覧（コマンドライン付き）。

    wmic は最近の Windows 11 から消えているので、PowerShell を先に使う。
    どちらも駄目なら tasklist（コマンドラインは出ないが、名前だけは分かる）。
    """
    attempts: list[list[str]] = []
    if os.name == "nt":
        attempts = [
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }"],
            ["wmic", "process", "get", "ProcessId,CommandLine"],
            ["tasklist"],
        ]
    else:
        attempts = [["ps", "-ax", "-o", "pid,command"]]
    for cmd in attempts:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out and out.strip():
            return out.splitlines()
    return []


def bridge_processes() -> list[str]:
    """裏で動いているブリッジ。exe 版は「AITrader.exe --run-bridge」で動く。"""
    hits = []
    for line in _process_lines():
        low = line.lower()
        if "check-install" in low or "get-ciminstance" in low:
            continue
        if "bridge.py" in low or "--run-bridge" in low:
            hits.append(line.strip()[:110])
    return hits


def relay_state(room_id: str) -> str:
    """中継に「その部屋にブリッジが居るか」を聞く。これがいちばん確かな答え。"""
    try:
        url = f"{RELAY}?room={urllib.parse.quote(room_id)}"
        with urllib.request.urlopen(url, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"見られません（{type(exc).__name__}）"
    room = data.get("room") or {}
    return "いる" if room.get("bridge") else "いない"


def main() -> int:
    print("=" * 62)
    print("  このPCの状態")
    print("=" * 62)

    cfg = config_dir()

    # ── 連携の状態 ──
    head("連携")
    state = read_json(cfg / "state.json")
    now = str(state.get("state") or "（記録なし）")
    row("state.json", now, "✓" if now in ("INSTALL_ONLY", "CONNECTED") else "－")
    if state.get("room"):
        row("部屋（会員ID）", str(state["room"]))
    env = cfg / "bridge.env"
    bridge_id = ""
    if env.is_file():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("BRIDGE_ID="):
                bridge_id = line.split("=", 1)[1].strip()
    row("bridge.env", f"あり（BRIDGE_ID={bridge_id or '未設定'}）" if env.is_file() else "無い")

    connected = now == "CONNECTED"
    print()
    print(f"  → {'連携済み。ブリッジが動いていてよい' if connected else '未連携。ブリッジは動いていてはいけない'}")

    # ── ブリッジ ──
    head("ブリッジ（外との通信）")
    # ① 中継に聞く（確実）
    my_room = str(state.get("room") or bridge_id or "")
    if connected and my_room:
        here = relay_state(my_room)
        row("自分の部屋につながっているか", here, "✓" if here == "いる" else "✕")
        if here != "いる":
            print("      ※ AITrader.exe を開き直してください")
    # ② 既定の部屋に居座っていないか（未連携のまま繋いでいたら問題）
    default_room = relay_state("vps-01")
    row("既定の部屋 vps-01", default_room, "✕" if default_room == "いる" and not connected else "✓")
    if default_room == "いる" and not connected:
        print("      ※ 未連携なのにつながっています。報告してください")
    # ③ このPCで動いているか（参考）
    #    1ファイルにまとめた exe は、親（展開する側）と子（本体）の2つに見える。
    #    コマンドラインが同じなので数では区別できない。2つでも普通。
    procs = bridge_processes()
    if procs:
        row("このPCで動いているか", "動いている", "")
        for line in procs[:4]:
            print(f"      {line}")
        if len(procs) > 2:
            print("      ※ 3つ以上あります。停止する.bat で一度止めてください")
        elif len(procs) == 2:
            print("      ※ 2つ見えるのは普通です（exe の展開用と本体）")
    else:
        row("このPCで動いているか", "見つからない", "")
        print("      ※ 上の「自分の部屋」が『いる』なら、動いています（見えないだけ）")

    # ── EA ──
    head("MT5 と EA")
    try:
        import ea_manager
        import mt5_detect
    except ImportError as exc:
        row("読み込み", f"できません（{exc}）", "✕")
        return 1

    source = ea_manager.load_source(ROOT / "bridge")
    if source is None:
        row("配布物", "bridge に .ex5 がありません", "✕")
    else:
        row("配布物の版", f"{source.version or '不明'}（{source.sha256[:12]}…）", "✓" if source.ok else "✕")
        if not source.ok:
            print(f"      {source.broken}")
        if source.ea_path.stat().st_size < 10_000:
            row("！ 本物の EA か", f"本物ではありません（{source.ea_path.stat().st_size:,} バイト）", "✕")
            print("      配線の確認用の差し替え品です。お客様には配らないでください")

    terminals = mt5_detect.list_terminals()
    if not terminals:
        row("MT5", "見つかりません", "✕")
    for t in terminals:
        st = ea_manager.status(t.data_path, source)
        good = st.state in (ea_manager.LATEST, ea_manager.NOT_INSTALLED)
        row(f"{t.label}", f"{st.state}（入っている版 {st.installed_version or '不明'}）", "✓" if good else "△")
        ex5 = t.data_path / "MQL5" / "Experts" / "OrbitGoldEA_v11.ex5"
        mq5 = t.data_path / "MQL5" / "Experts" / "OrbitGoldEA_v11.mq5"
        inc = t.data_path / "MQL5" / "Include" / "TradingGate.mqh"
        row("  .ex5", "ある" if ex5.is_file() else "無い", "✓" if ex5.is_file() else "✕")
        # 前は .mq5 を配って現地でコンパイルさせていた。その残りがあれば知らせる
        # （動きには影響しないが、MT5 のナビゲーターに同じ名前が2つ出て紛らわしい）
        row("  前の方式の残り", "あり（消してよい）" if mq5.is_file() else "なし", "△" if mq5.is_file() else "✓")
        row("  TradingGate.mqh", "ある" if inc.is_file() else "無い", "✓" if inc.is_file() else "✕")
        if st.detail:
            print(f"      {st.detail}")

    # ── Windows の登録 ──
    head("Windows の登録")
    if os.name != "nt":
        row("（Windows ではないので省略）", "")
    else:
        entries = startup_entries()
        if not entries:
            row("自動起動", "登録なし", "✓" if not connected else "△")
            if connected:
                print("      ※ 連携済みなら、アプリを一度開くと登録されます")
        for name, value in entries:
            ok_, where = points_here(value)
            row(f"自動起動［{name}］", where, "✓" if ok_ else "✕")
            if not ok_:
                print(f"      ※ 別の場所を指しています: {value[:90]}")
                print("      ※ インストーラーを入れ直してください")
        proto = protocol_command()
        if proto:
            ok_, where = points_here(proto)
            row("aitrader://", where, "✓" if ok_ else "✕")
            if not ok_:
                print(f"      ※ 別の場所を指しています: {proto[:90]}")
        else:
            row("aitrader://", "登録なし", "✕")

    # ── 記録 ──
    head("記録（困ったときはここ）")
    for name in ("connect.log", "state.json", "ea_installed.json", "bridge.env", "intent.json"):
        path = cfg / name
        row(name, f"{path}" if path.is_file() else "（無い）")

    print()
    print("=" * 62)
    print("  ✕ があれば、その行をそのまま報告してください")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
