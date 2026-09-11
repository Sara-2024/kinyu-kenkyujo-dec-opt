"""接続ツールが「どの部屋につなぐか」を、どこから言われても信じないことを確かめる。

    python3 bridge/tests/connector_room_test.py

ここが緩いと、悪意あるページに `aitrader://connect?room=<他人のID>` を開かせるだけで、
お客様の MT5 が他人の管理画面につながる（お客様は何も悪いことをしていない）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

import connect  # noqa: E402

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


SITE = "https://kinyu-kenkyujo-dec-opt.vercel.app"
ME = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def url(room: str, origin: str | None = SITE) -> str:
    q = f"room={room}"
    if origin is not None:
        q += f"&from={origin}"
    return f"aitrader://connect?{q}"


# ── 正しい導線 ──
check("自分のサイトから渡された会員IDは受け取る", connect.site_room_from_args([url(ME)]) == ME)
check(
    "開発機（localhost）からも受け取る",
    connect.site_room_from_args([url(ME, "http://localhost:5181")]) == ME,
)
check(
    "末尾のスラッシュや大文字は気にしない",
    connect.site_room_from_args([url(ME, SITE.upper() + "/")]) == ME,
)

# ── 断るべき導線 ──
check(
    "知らないサイトから渡された部屋は受け取らない",
    connect.site_room_from_args([url(OTHER, "https://warui-site.example")]) == "",
)
check(
    "似せたドメインも受け取らない",
    connect.site_room_from_args([url(OTHER, "https://kinyu-kenkyujo-dec-opt.vercel.app.evil.example")]) == "",
)
check(
    "会員IDの形でない部屋は受け取らない（既定の部屋を名指しされても）",
    connect.site_room_from_args([url("vps-01")]) == "",
)
check(
    "UUIDに似せた文字列も受け取らない",
    connect.site_room_from_args([url(ME + "x")]) == "",
)
check("部屋の指定が無ければ空", connect.site_room_from_args([f"aitrader://connect?from={SITE}"]) == "")
check(
    "from が無い部屋指定は受け取らない（悪意あるページが from を省略する経路）",
    connect.site_room_from_args([url(OTHER, None)]) == "",
)
check("プロトコル以外の引数は見ない", connect.site_room_from_args(["--status", ME]) == "")

# ── 覚えるとき（bridge.env に書くとき）にも同じ検査をする ──
written: list[tuple[str, str]] = []
connect.write_env_key = lambda k, v: written.append((k, v))  # type: ignore[assignment]
connect.env_value = lambda key: ""  # type: ignore[assignment]

connect.adopt_room("vps-01")
check("会員IDの形でなければ覚えない", written == [], str(written))

connect.adopt_room(ME)
check("会員IDなら覚える", written == [("BRIDGE_ID", ME)], str(written))

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
