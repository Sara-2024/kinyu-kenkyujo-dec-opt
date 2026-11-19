"""
本物の中継（server/index.js）を手元で立て、本物のブリッジ（bridge/bridge.py）を
「MT5 が閉じている（つながらない）」状態で起こして、サイトに名乗れるかを確かめる。MT5 も Windows も要らない。

実行: python3 bridge/tests/bridge_relay_e2e_test.py

2026-11-19：MT5 につながる前の名乗りで、MT5 につながったあとにしか無い項目（intent_by）を読んで落ち、
MT5 が閉じているあいだ一度もサイトに現れなかった（接続ツールは「完了」と出るのに、サイトは「つながっていない」）。
「MT5 を勝手に開かない」に直したことで表に出た。部品ごとの試験では見つからなかったので、通しで見る。
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


try:
    import websockets  # noqa: F401
except ImportError:
    print("  （websockets が無いので省きます）\n\n0 ok / 0 NG")
    sys.exit(0)

work = pathlib.Path(tempfile.mkdtemp(prefix="e2e-"))
fake = work / "fakemt5"
fake.mkdir()
# MT5 が閉じている状態の身代わり。initialize はいつも失敗する
(fake / "MetaTrader5.py").write_text(
    "def initialize(*a, **k): return False\n"
    "def shutdown(): return True\n"
    "def last_error(): return (-1, 'closed')\n"
    "def account_info(): return None\n"
    "def terminal_info(): return None\n",
    encoding="utf-8",
)
port = free_port()
env_relay = {k: v for k, v in os.environ.items() if not k.endswith(("SUPABASE_URL", "SUPABASE_ANON_KEY"))}
env_relay["PORT"] = str(port)
relay = subprocess.Popen(["node", "index.js"], cwd=str(ROOT / "server"), env=env_relay,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
room = "11111111-2222-4333-8444-555555555555"
log_file = work / "bridge.log"
env_bridge = dict(os.environ)
env_bridge.update({
    "PYTHONPATH": str(fake),
    "TRELAB_WS_URL": f"ws://127.0.0.1:{port}/bridge",
    "BRIDGE_ID": room,
    "LOCALAPPDATA": str(work / "la"),
    "LOG_FILE": str(log_file),
    "RECONNECT_MIN_SEC": "0.5",
})
bridge = None
try:
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    bridge = subprocess.Popen([sys.executable, "bridge.py"], cwd=str(ROOT / "bridge"), env=env_bridge,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seen = False
    for _ in range(60):
        try:
            body = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health?room={room}", timeout=2).read())
            if body.get("room", {}).get("bridge"):
                seen = True
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.25)
    time.sleep(1.5)
    text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.is_file() else ""
    check("MT5 が閉じていても、ブリッジはサイト（中継）に名乗る", seen, text[-800:])
    check("名乗りで落ちない（エラーの記録が無い）", "Traceback" not in text, text[-800:])
finally:
    for p in (bridge, relay):
        if p is not None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
