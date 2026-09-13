#!/usr/bin/env python3
"""このPCがいまどうなっているかを、まとめて見る（実機テスト用）。

  tools\\確認する.bat  を押すだけ。

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
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge"))

RELAY_HEALTH = "https://kinyu-relay.onrender.com/health?room=vps-01"
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


def bridge_processes() -> list[str]:
    """裏で動いているブリッジ。Windows は wmic、他は ps で見る。"""
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["wmic", "process", "get", "ProcessId,CommandLine"],
                capture_output=True, text=True, timeout=20,
            ).stdout
        else:
            out = subprocess.run(["ps", "-ax", "-o", "pid,command"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    hits = []
    for line in out.splitlines():
        low = line.lower()
        if ("bridge.py" in low or "--run-bridge" in low) and "check-install" not in low:
            hits.append(line.strip()[:110])
    return hits


def relay_state() -> str:
    try:
        with urllib.request.urlopen(RELAY_HEALTH, timeout=15) as res:
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
    procs = bridge_processes()
    row("動いているか", f"{len(procs)} 個" if procs else "動いていない", "✓" if bool(procs) == connected else "✕")
    for line in procs[:3]:
        print(f"      {line}")
    row("既定の部屋 vps-01", relay_state(), "")
    print("      ※ 未連携なのに「いる」なら ✕（報告してください）")

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
        ex5 = t.data_path / "MQL5" / "Experts" / "OrbitGoldEA_v6.ex5"
        mq5 = t.data_path / "MQL5" / "Experts" / "OrbitGoldEA_v6.mq5"
        inc = t.data_path / "MQL5" / "Include" / "TradingGate.mqh"
        row("  .ex5", "ある" if ex5.is_file() else "無い", "✓" if ex5.is_file() else "✕")
        row("  .mq5（配らない）", "残っている" if mq5.is_file() else "無い", "△" if mq5.is_file() else "✓")
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
            here = str(ROOT).lower() in value.lower() or "aitraderconnect" in value.lower()
            row(f"自動起動［{name}］", value[:70], "✓" if here else "✕")
            if not here:
                print("      ※ 古い exe を指しています。インストーラーを入れ直してください")
        proto = protocol_command()
        row("aitrader://", proto[:70] if proto else "登録なし", "✓" if proto else "✕")

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
