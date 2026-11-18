"""
Windows の実機で「閉じた MT5 を勝手に開かない／開いたらつながる」を確かめる。

GitHub の Windows マシンで走らせる（.github/workflows/test-windows.yml）。Windows 以外では何もしない。

  第 1 部（いつも走る）: 偽の MT5（名前を terminal64.exe にした ping.exe）を起こしたり止めたりして、
     ・プロセス一覧から MT5 を見つけられるか（mt5_terminal.running_terminal_exes。本物の Windows の仕組みで）
     ・MT5 が閉じているあいだ、ブリッジは initialize を呼ばずに待つか
     ・MT5 が開いたら、そのときにつながるか
  第 2 部（REAL_MT5 に本物の terminal64.exe があるときだけ）: 本物の MetaTrader5 パッケージで
     ・素の mt5.initialize(path) は、閉じた MT5 を起動してしまう（＝直す前の不具合が本当に起きる）
     ・ブリッジの繋ぎ方（_initialize_any_blocking）は、閉じた MT5 を起動しない（＝直ったこと）

実行: python bridge/tests/windows_mt5_test.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BRIDGE = ROOT / "bridge"
sys.path.insert(0, str(BRIDGE))

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  NG   {name} {extra}")


if os.name != "nt":
    print("  （Windows ではないので省きます。GitHub の Windows マシンで走ります）")
    print("\n0 ok / 0 NG")
    sys.exit(0)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def all_terminal_pids() -> list[int]:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, errors="replace").stdout
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith("terminal64"):
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def kill_all_terminals() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "terminal64.exe"], capture_output=True)
    for _ in range(40):
        if not all_terminal_pids():
            return
        time.sleep(0.25)


import mt5_terminal  # noqa: E402

# ══════════ 第 1 部：偽の MT5 ══════════
print("── 第 1 部：偽の MT5（プロセスの見つけ方とブリッジの待ち方）")
kill_all_terminals()
work = pathlib.Path(tempfile.mkdtemp(prefix="mt5fake-"))
fake_dir = work / "MetaTrader 5 Fake"
fake_dir.mkdir()
fake_exe = fake_dir / "terminal64.exe"
shutil.copy2(pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE", fake_exe)
other_exe = work / "Other MT5" / "terminal64.exe"


def start_fake() -> subprocess.Popen:
    p = subprocess.Popen([str(fake_exe), "-n", "600", "127.0.0.1"], creationflags=NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if p.pid in all_terminal_pids():
            break
        time.sleep(0.25)
    return p


check("はじめは MT5 が 1 つも動いていない", mt5_terminal.running_terminal_exes() == [], str(mt5_terminal.running_terminal_exes()))
check("閉じていれば「動いていない」", mt5_terminal.terminal_is_running(fake_exe) is False)
check("どれも動いていなければ「動いていない」", mt5_terminal.terminal_is_running(None) is False)

proc = start_fake()
running = mt5_terminal.running_terminal_exes() or []
check("開いた MT5 をプロセス一覧から見つける（場所まで）",
      any(os.path.normcase(str(p)) == os.path.normcase(str(fake_exe)) for p in running), str(running))
check("開いた MT5 は「動いている」", mt5_terminal.terminal_is_running(fake_exe) is True)
check("別の場所の MT5 は「動いていない」", mt5_terminal.terminal_is_running(other_exe) is False)
proc.kill()
proc.wait()
time.sleep(0.5)
check("閉じたら、また「動いていない」", mt5_terminal.terminal_is_running(fake_exe) is False)

# ブリッジ：MetaTrader5 は身代わり（呼ばれたら記録する）。プロセスの判定だけ本物を使う
calls: list[dict] = []


class FakeMT5(types.ModuleType):
    def initialize(self, **kw):
        calls.append(kw)
        return True

    def shutdown(self):
        return True

    def account_info(self):
        return types.SimpleNamespace(login=777, server="Test-Server", balance=0, equity=0, currency="JPY")

    def terminal_info(self):
        return types.SimpleNamespace(name="MT5", build=1, connected=True, trade_allowed=True, commondata_path=str(work))

    def last_error(self):
        return (0, "")


try:
    import websockets  # noqa: F401
except ImportError:
    pass

fake = FakeMT5("MetaTrader5")
os.environ["MT5_PATH"] = str(fake_exe)
os.environ["LOCALAPPDATA"] = str(work)
import bridge as bridge_mod  # noqa: E402

bridge_mod.mt5 = fake
mt5_terminal.mt5 = fake
bridge_mod.MT5_CLOSED_POLL_SEC = 0.2
cfg = bridge_mod.Config()
cfg.mt5_path = str(fake_exe)
ctl = bridge_mod.MT5Controller(cfg)


async def closed_then_open() -> tuple[int, bool, float]:
    stop = asyncio.Event()
    calls.clear()
    task = asyncio.create_task(ctl.connect_with_retry(stop))
    await asyncio.sleep(2.0)
    while_closed = len(calls)           # 閉じているあいだに initialize を呼んだ回数（0 であるべき）
    opened_at = time.time()
    p = await asyncio.get_running_loop().run_in_executor(None, start_fake)
    try:
        await asyncio.wait_for(task, 15)
        connected = ctl.ready
    except asyncio.TimeoutError:
        stop.set()
        connected = False
    finally:
        p.kill()
    return while_closed, connected, time.time() - opened_at


while_closed, connected, took = asyncio.run(closed_then_open())
check("MT5 が閉じているあいだ、ブリッジは initialize を一度も呼ばない（MT5 を起こさない）", while_closed == 0, str(while_closed))
check("MT5 を開いたら、ブリッジがつながる", connected is True)
check("つなぐのは開いた MT5 を名指しで", bool(calls) and os.path.normcase(str(calls[-1].get("path", ""))) == os.path.normcase(str(fake_exe)), str(calls[-1:] if calls else calls))
check("開いてから数秒でつながる", took < 10, f"{took:.1f} 秒")
print(f"     （開いてからつながるまで {took:.1f} 秒）")
check("偽の MT5 は勝手に起動されていない（テストが止めたまま）", not all_terminal_pids(), str(all_terminal_pids()))

# ══════════ 第 2 部：本物の MT5 ══════════
real = os.environ.get("REAL_MT5", "").strip()
if real and pathlib.Path(real).is_file():
    print("── 第 2 部：本物の MT5（直す前の動きと、直した動き）")
    sys.modules.pop("MetaTrader5", None)
    try:
        import MetaTrader5 as real_mt5  # noqa: E402
    except Exception as exc:  # noqa: BLE001
        real_mt5 = None
        check("本物の MetaTrader5 パッケージを読める", False, str(exc))
    if real_mt5 is not None:
        kill_all_terminals()
        check("（準備）本物の MT5 を閉じた", not all_terminal_pids(), str(all_terminal_pids()))

        # 直した繋ぎ方：閉じた MT5 は起こさない
        bridge_mod.mt5 = real_mt5
        mt5_terminal.mt5 = real_mt5
        cfg2 = bridge_mod.Config()
        cfg2.mt5_path = real
        cfg2.mt5_timeout = 20000
        ctl2 = bridge_mod.MT5Controller(cfg2)
        ok = ctl2._initialize_any_blocking()
        time.sleep(8)
        check("直した繋ぎ方：閉じた MT5 は起動しない", not all_terminal_pids() and ok is False, f"pids={all_terminal_pids()} ok={ok}")
        session = mt5_terminal.find_logged_in_terminal()
        time.sleep(8)
        check("直した探し方：閉じた MT5 は起動しない", session is None and not all_terminal_pids(), f"pids={all_terminal_pids()}")

        # 直す前の繋ぎ方（素の initialize）：閉じた MT5 を起こしてしまう
        try:
            real_mt5.initialize(path=real, timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        launched = False
        for _ in range(60):
            if all_terminal_pids():
                launched = True
                break
            time.sleep(0.5)
        try:
            real_mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass
        check("（比較）直す前の素の initialize は、閉じた MT5 を起動してしまう", launched)
        if launched:
            # 開いている本物の MT5 は、プロセス一覧から見つかる
            check("開いた本物の MT5 をプロセス一覧から見つける", mt5_terminal.terminal_is_running(real) is True)
        kill_all_terminals()
else:
    print("── 第 2 部：本物の MT5 は省きます（REAL_MT5 が無い）")

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
