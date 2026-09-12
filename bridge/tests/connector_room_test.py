"""接続ツールが「どの部屋につなぐか」を、どこから言われても信じないことを確かめる。

    python3 bridge/tests/connector_room_test.py

ここが緩いと、悪意あるページに `aitrader://connect?room=<他人のID>` を開かせるだけで、
お客様の MT5 が他人の管理画面につながる（お客様は何も悪いことをしていない）。

最初は「会員IDの形か」「`from=` が自分たちのサイトか」を見て受け取っていた。
いまは **URL から部屋を受け取ること自体をやめた**。`from=` は名乗るだけのもので、
自分たちのサイトを装う余地が残るため。部屋は、サイトがその場で作った短命の合図
（token）と引き換えに、サイト自身が返したものだけを受け取る。

この試験では、
  ・URL から部屋を読む処理が存在しないこと
  ・部屋を覚えるとき（bridge.env に書くとき）の検査が効いていること
を見る。合図での連携そのものは phase2_test.py が見ている。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

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


# ── URL から部屋を受け取る道は、もう無い ──
check("URL から部屋を読む処理が無い", not hasattr(connect, "site_room_from_args"))
check("`from=` を照合する処理も無い（部屋を受け取らないので不要）", not hasattr(connect, "trusted_site"))

# どんな組み合わせでも、合図としては読まれない
for name, raw in [
    ("自分のサイトを名乗る部屋指定", url(ME)),
    ("他人のIDを渡す部屋指定", url(OTHER)),
    ("知らないサイトからの部屋指定", url(OTHER, "https://warui-site.example")),
    ("似せたドメインからの部屋指定", url(OTHER, SITE + ".evil.example")),
    ("from の無い部屋指定", url(OTHER, None)),
    ("既定の部屋の名指し", url("vps-01")),
]:
    check(f"{name}は合図にならない", connect.connect_token_from_args([raw]) == "")

check("プロトコル以外の引数は見ない", connect.connect_token_from_args(["--status", ME]) == "")

# ── 覚えるとき（bridge.env に書くとき）にも検査する ──
# 合図と引き換えにサイトが返した部屋であっても、形が会員IDでなければ覚えない
written: list[tuple[str, str]] = []
connect.write_env_key = lambda k, v: written.append((k, v))  # type: ignore[assignment]
connect.env_value = lambda key: ""  # type: ignore[assignment]

connect.adopt_room("vps-01")
check("会員IDの形でなければ覚えない", written == [], str(written))

connect.adopt_room(ME + "x")
check("UUIDに似せた文字列も覚えない", written == [], str(written))

connect.adopt_room(ME)
check("会員IDなら覚える", written == [("BRIDGE_ID", ME)], str(written))

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
