"""サイトからの連携（Phase 2）を、サイトも MT5 も無いところで確かめる。

見たいのは4つ。

  ・aitrader://connect?token=... から合図を読めるか
  ・合図をサイトに確かめてもらい、その返事の部屋だけを採用するか
  ・確かめられなければ連携しない（＝通信も始めない）か
  ・アプリ単体では連携できない（合図を自分で作れない）か

実行: python3 bridge/tests/phase2_test.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile

BRIDGE = pathlib.Path(__file__).resolve().parent.parent
ROOT = BRIDGE.parent
WORK = tempfile.mkdtemp(prefix="aitrader-phase2-")
os.environ["LOCALAPPDATA"] = str(pathlib.Path(WORK) / "Local")
os.environ["APPDATA"] = str(pathlib.Path(WORK) / "Roaming")

sys.path.insert(0, str(BRIDGE))
sys.path.insert(0, str(ROOT))

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


import connect  # noqa: E402
import connect_state  # noqa: E402

GOOD = "a" * 64
MEMBER = "11111111-2222-4333-8444-555555555555"

# ── 1) URL から合図を読む ────────────────────────────
check("合図を読める", connect.connect_token_from_args([f"aitrader://connect?token={GOOD}"]) == GOOD)
check(
    "from が一緒でも読める",
    connect.connect_token_from_args([f"aitrader://connect?from=https://x.test&token={GOOD}"]) == GOOD,
)
check("短い合図は読まない", connect.connect_token_from_args(["aitrader://connect?token=abc"]) == "")
check("16進でない合図は読まない", connect.connect_token_from_args([f"aitrader://connect?token={'z' * 64}"]) == "")
check("合図が無ければ空", connect.connect_token_from_args(["aitrader://connect?room=" + MEMBER]) == "")
check("ただの引数は読まない", connect.connect_token_from_args(["--console", GOOD]) == "")

# ── 2) 古い形（room=）は互換として読めるが、合図とは別物 ──
check("room= は読める（互換）", connect.site_room_from_args([f"aitrader://connect?room={MEMBER}"]) == MEMBER)
check("room= からは合図を作らない", connect.connect_token_from_args([f"aitrader://connect?room={MEMBER}"]) == "")

# ── 3) 合図をサイトに確かめてもらう ──────────────────
sent: list[dict] = []


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *_a) -> None:  # noqa: ANN002
        return None


def fake_urlopen(payload):  # noqa: ANN001, ANN202
    def inner(req, timeout=0):  # noqa: ANN001, ANN202
        sent.append({"url": req.full_url, "body": json.loads(req.data.decode("utf-8"))})
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)

    return inner


real_urlopen = connect.urllib.request.urlopen

connect.urllib.request.urlopen = fake_urlopen({"ok": True, "room": MEMBER})
room = connect.redeem_connect_token(GOOD)
check("正しい合図なら部屋が返る", room == MEMBER, room)
check("問い合わせ先は /api/connect", sent and sent[0]["url"].endswith("/api/connect"), str(sent[:1]))
check("合図を送っている", sent and sent[0]["body"].get("token") == GOOD)
check("宛先は決め打ち（from= を当てにしない）", sent and sent[0]["url"].startswith("https://"), str(sent[:1]))

# 返事に部屋が無い／おかしい
connect.urllib.request.urlopen = fake_urlopen({"ok": True})
check("部屋が無ければ連携しない", connect.redeem_connect_token(GOOD) == "")
connect.urllib.request.urlopen = fake_urlopen({"ok": True, "room": "../../etc/passwd"})
check("おかしな部屋は受け取らない", connect.redeem_connect_token(GOOD) == "")

# サイトが断った／つながらない
connect.urllib.request.urlopen = fake_urlopen(
    connect.urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
)
check("サイトが断れば連携しない", connect.redeem_connect_token(GOOD) == "")
connect.urllib.request.urlopen = fake_urlopen(OSError("network"))
check("つながらなければ連携しない", connect.redeem_connect_token(GOOD) == "")

# ── 4) 合図が通らないかぎり、状態は変わらない ────────────
check("まだ INSTALL_ONLY", connect_state.current() == connect_state.INSTALL_ONLY, connect_state.current())
check("つながっていない", not connect_state.is_connected())

# 合図が通ったときだけ CONNECTED になる（adopt_room を通す）
connect.write_env_key = lambda *a, **k: None  # .env は書かせない
connect.adopt_room(MEMBER)
check("連携すると CONNECTED", connect_state.is_connected())
check("部屋を覚えている", connect_state.read().get("room") == MEMBER)

# 連携が済めば、既存のブリッジが動かせるようになる（歯止めを通り抜ける）
reached = []
connect.bridge_already_running = lambda: (reached.append("見に行った"), False)[1]
connect.spawn_hidden = lambda *a, **k: reached.append("起動した")
connect.start_bridge(None)
check("連携後はブリッジが動かせる", "起動した" in reached, str(reached))

# 解除すれば、また止まる
connect_state.mark_install_only("試験")
reached.clear()
connect.start_bridge(None)
check("解除すると、また止まる", reached == [], str(reached))
connect_state.mark_connected(MEMBER)

# ── 5) アプリ単体では合図を作れない ──────────────────
src = (ROOT / "connect.py").read_text(encoding="utf-8")
# コメントに書いてある言葉ではなく、実際に呼んでいる処理で見る
import ast  # noqa: E402

tree = ast.parse(src)
called = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute):
            base = fn.value.id if isinstance(fn.value, ast.Name) else ""
            called.add(f"{base}.{fn.attr}".lstrip("."))
        elif isinstance(fn, ast.Name):
            called.add(fn.id)
risky = {c for c in called if c.startswith(("secrets.", "random.")) or c in ("os.urandom", "uuid4")}
check("合図を自分で作らない", not risky, str(risky))
check("発行の関数を呼んでいない", "connect_token_issue" not in called and "connect_token_issue" not in src)
check("確かめるのもサイトに任せる（直接 DB を叩かない）", "connect_token_redeem" not in src)

# ── 6) 記録に合図そのものを残さない ──────────────────
log_text = ""
log_path = pathlib.Path(os.environ["LOCALAPPDATA"]) / "AITrader" / "connect.log"
if log_path.is_file():
    log_text = log_path.read_text(encoding="utf-8")
check("記録に合図を書いていない", GOOD not in log_text)

# ── 7) サイト側が room= を作っていないこと ───────────────
connector_ts = (ROOT / "src" / "data" / "connector.ts").read_text(encoding="utf-8")
check("サイトは room= を発行しない", "params.set('room'" not in connector_ts)
check("サイトは token= を発行する", "params.set('token'" in connector_ts)
check("サイトは会員IDを URL に載せない", "member?.id" not in connector_ts)

dialogue = (ROOT / "src" / "components" / "DialogueWindow.tsx").read_text(encoding="utf-8")
check("画面も会員IDを渡していない", "launchConnector(member?.id)" not in dialogue)

connect.urllib.request.urlopen = real_urlopen
shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
