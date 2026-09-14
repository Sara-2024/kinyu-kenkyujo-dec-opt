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

# ── 2) URL の room= は、もう読まない ────────────────
check("room= を読む処理は無い", not hasattr(connect, "site_room_from_args"))
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

# ── 8) DB の追加分（migration）と schema.sql がずれていないか ──
mig_path = ROOT / "supabase" / "migrations" / "20260912_add_connect_tokens.sql"
schema_path = ROOT / "supabase" / "schema.sql"
check("migration がある", mig_path.is_file())
if mig_path.is_file():
    mig = mig_path.read_text(encoding="utf-8")
    schema = schema_path.read_text(encoding="utf-8")
    body = mig[mig.index("create table if not exists public.connect_tokens") :]
    check("migration の中身が schema.sql と同じ", body.strip() in schema)
    for name in ("connect_tokens", "connect_token_issue", "connect_token_redeem"):
        check(f"migration に {name} が入っている", name in mig)
    check("索引も入っている", "connect_tokens_member_idx" in mig and "connect_tokens_expires_idx" in mig)
    check("権限も入っている", mig.count("grant execute") == 2, str(mig.count("grant execute")))
    # 実行される行（コメントを除いたもの）が、既存のものに触っていないこと
    lines = [ln.split("--")[0].strip() for ln in mig.splitlines()]
    sql = " ".join(ln for ln in lines if ln)
    import re as _re

    bad = [
        m
        for m in _re.findall(r"(?:alter|drop)\s+(?:table|function|index)\s+[\w.]+", sql, _re.I)
        if "connect_token" not in m
    ]
    check("既存のテーブル・関数に触らない", not bad, str(bad))
    check("members や sessions を書き換えない", "alter table public.members" not in sql and "public.sessions" not in sql)

# ══════════════════════════════════════════════════
# 9) 通しで確かめる。CONNECTED になれる入口は合図だけ
# ══════════════════════════════════════════════════
connect_state.mark_install_only("通しの試験の前に戻す")

# にせの MT5 と配布物（EA を置くところまでは動かせるようにする）
import hashlib  # noqa: E402

mt5_dir = pathlib.Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / ("C" * 32)
(mt5_dir / "MQL5" / "Experts").mkdir(parents=True, exist_ok=True)
(mt5_dir / "MQL5" / "Include").mkdir(parents=True, exist_ok=True)
install_dir = pathlib.Path(WORK) / "PF" / "HFM MetaTrader 5"
install_dir.mkdir(parents=True, exist_ok=True)
(install_dir / "terminal64.exe").write_text("")
(mt5_dir / "origin.txt").write_text(str(install_dir), encoding="utf-16")

assets = pathlib.Path(WORK) / "assets"
assets.mkdir(exist_ok=True)
BODY = b"EX5-FOR-PHASE2"
(assets / "OrbitGoldEA_v11.ex5").write_bytes(BODY)
(assets / "TradingGate.mqh").write_text("// 共通部品", encoding="utf-8")
(assets / "ea_manifest.json").write_text(
    json.dumps({"ea": "OrbitGoldEA_v11", "file": "OrbitGoldEA_v11.ex5", "version": "6.10",
                "sha256": hashlib.sha256(BODY).hexdigest()}), encoding="utf-8")
connect.BRIDGE_DIR = assets
connect.installer_ui.open_window = lambda: None


def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
    raise AssertionError(f"起動・通信してはいけない場面で呼ばれた: {a[:1]}")


connect.spawn_hidden = boom
connect.run_hidden = boom
connect.urllib.request.urlopen = boom
connect.write_env_key = lambda *a, **k: None

calls: list[str] = []
connect.connect_all = lambda room="": (calls.append(room), 0)[1]


def run_main(*argv: str) -> int:
    sys.argv = ["connect.py", *argv]
    return connect.main()


# (A) INSTALL_ONLY の PC に room= を投げても、連携させない
connect_state.mark_install_only("試験")
calls.clear()
code = run_main(f"aitrader://connect?room={MEMBER}")
check("room= を渡しても失敗にはしない（EA は置く）", code == 0, f"code={code}")
check("room= では CONNECTED にならない", not connect_state.is_connected(), connect_state.current())
check("room= では連携の処理に進まない", calls == [], str(calls))
check("room= ではブリッジも通信も起きない", True)  # boom が呼ばれたらここまで来ない
check("room= でも EA は置かれる", (mt5_dir / "MQL5" / "Experts" / "OrbitGoldEA_v11.ex5").is_file())

# (B) 会員IDを知っていても、部屋を名乗るだけでは連携できない
calls.clear()
run_main(f"aitrader://connect?room={MEMBER}&from=https://example.test")
check("from が付いていても同じ", not connect_state.is_connected() and calls == [])

# (C) 形だけ token に似せても、サイトが確かめないかぎり連携しない
calls.clear()
connect.urllib.request.urlopen = fake_urlopen(
    connect.urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
)
code = run_main(f"aitrader://connect?token={GOOD}")
check("サイトが断れば失敗で終わる", code == 1, f"code={code}")
check("断られたら CONNECTED にならない", not connect_state.is_connected())
check("断られたら連携の処理に進まない", calls == [])
connect.urllib.request.urlopen = boom

# (D) 正しい合図のときだけ INSTALL_ONLY → CONNECTED
calls.clear()
connect.urllib.request.urlopen = fake_urlopen({"ok": True, "room": MEMBER})
code = run_main(f"aitrader://connect?token={GOOD}")
check("正しい合図なら成功", code == 0, f"code={code}")
check("正しい合図で連携の処理に進む", calls == [MEMBER], str(calls))
connect.urllib.request.urlopen = boom

# (E) すでに使っているお客様は、URL ではなく手元の設定から引き継ぐ
connect_state.state_path().unlink(missing_ok=True)
calls.clear()
connect.env_value = lambda key: MEMBER if key == "BRIDGE_ID" else ""
code = run_main()
check("既存のお客様は引き継げる", connect_state.is_connected(), connect_state.current())
check("引き継いだらこれまでどおり動く", calls == [""], str(calls))

# (E2) つなぎ直しの URL（合図なし）。サイトの管理画面から開かれるもの
#      条件: 正式な連携情報があるときだけ再接続する／未連携は CONNECTED にならない／
#            合図なしで新しい紐付けはできない
RELAUNCH = "aitrader://connect"
check("つなぎ直しの URL からは合図を読まない", connect.connect_token_from_args([RELAUNCH]) == "")

#   連携済みの PC → これまでどおりつなぎ直す
connect_state.state_path().unlink(missing_ok=True)
connect.env_value = lambda key: MEMBER if key == "BRIDGE_ID" else ""
calls.clear()
code = run_main(RELAUNCH)
check("連携済みなら、つなぎ直しに進む", calls == [""], str(calls))
check("連携済みのままでいる", connect_state.is_connected())

#   未連携の PC → EA を置くだけ。部屋も持たない
connect_state.state_path().unlink(missing_ok=True)
connect.env_value = lambda key: ""
calls.clear()
code = run_main(RELAUNCH)
check("未連携なら CONNECTED にならない", not connect_state.is_connected(), connect_state.current())
check("未連携ならつなぎ直しにも進まない", calls == [], str(calls))
check("未連携でもブリッジも通信も起きない", True)  # boom が呼ばれたらここまで来ない
check("合図なしでは新しい紐付けができない", connect_state.read().get("room") in (None, ""), str(connect_state.read()))

# (E3) Windows の起動時（--startup）。古い版が登録した自動起動が残っている PC で、
#      毎回ログインのたびに設定画面が開かないこと
connect_state.state_path().unlink(missing_ok=True)
connect.env_value = lambda key: ""
calls.clear()
opened = []
connect.installer_ui.open_window = lambda: (opened.append(1), None)[1]
code = run_main("--silent", "--startup")
check("未連携なら自動起動で何もしない", code == 0 and calls == [] and opened == [], f"code={code} calls={calls} 画面={opened}")
check("未連携の自動起動では CONNECTED にならない", not connect_state.is_connected())

#      連携済みなら、これまでどおり裏でつなぎ直す
connect_state.state_path().unlink(missing_ok=True)
connect.env_value = lambda key: MEMBER if key == "BRIDGE_ID" else ""
calls.clear()
opened.clear()
code = run_main("--silent", "--startup")
check("連携済みなら自動起動でつなぎ直す", calls == [""], str(calls))
check("自動起動では画面を出さない", opened == [], str(opened))
connect.installer_ui.open_window = lambda: None

# (F) 引き継ぐ材料が無い PC は、EA を置くだけ
connect_state.state_path().unlink(missing_ok=True)
calls.clear()
connect.env_value = lambda key: "vps-01" if key == "BRIDGE_ID" else ""
code = run_main()
check("既定の部屋では引き継がない", not connect_state.is_connected(), connect_state.current())
check("EA を置くだけで終わる", calls == [], str(calls))

connect.urllib.request.urlopen = real_urlopen
shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
