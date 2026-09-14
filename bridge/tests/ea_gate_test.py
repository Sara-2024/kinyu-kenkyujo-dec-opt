"""配る EA に、サイト連携がちゃんと入っているかを確かめる。

    python3 bridge/tests/ea_gate_test.py

MetaEditor はここでは動かせないので、ソースを読んで
「無いと動かないもの」が揃っているかだけを見る。

これが欠けると何が起きるか:
  include が無い            … そもそもコンパイルが通らない
  OnTimer が無い            … ea_alive が立たず、サイトが EA を見つけられない。
                               ユイの初期設定がそこで止まる
  IsTradingAllowedRaw が無い … 管理画面の「停止」を押しても止まらない
  AiAllowsEntry が無い       … AIの見張りが効かない
  SiteLot が無い             … 管理画面でロットを変えても反映されない
  GateProfile が無い         … AI に渡す戦略の説明が既定値のままになる

ソースが無いとき（配るのは .ex5 だけなので、普通は無い）は何もせず通す。
"""
from __future__ import annotations

import pathlib
import re
import sys

BRIDGE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE))

from mt5_terminal import EA_NAMES  # noqa: E402

SOURCE = BRIDGE / f"{EA_NAMES[0]}.mq5"

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


if not SOURCE.is_file():
    print(f"  --   {SOURCE.name} が無いので省略します（配るのは .ex5 だけ）")
    raise SystemExit(0)

src = SOURCE.read_text(encoding="utf-8", errors="ignore")


def body_of(name: str) -> str:
    """関数の中身を、波かっこの対応で取り出す。"""
    m = re.search(rf"\b{name}\s*\([^)]*\)\s*\n?\s*{{", src)
    if m is None:
        return ""
    start = m.end() - 1
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    return src[start:]


# ── 1) 連携部品を読んでいるか ──
check("TradingGate.mqh を include している", "#include <TradingGate.mqh>" in src)

# ── 2) 生存を知らせているか（これが無いとサイトは EA を見つけられない）──
on_timer = body_of("OnTimer")
check("OnTimer がある", bool(on_timer))
check("OnTimer で状態ファイルを書いている", "SyncGateFileToGlobals" in on_timer, on_timer[:80])

on_init = body_of("OnInit")
check("OnInit でタイマーを起こしている", "EventSetMillisecondTimer" in on_init)
check("OnInit でも一度だけ状態を書いている", "SyncGateFileToGlobals" in on_init)
check("OnInit で戦略プロフィールを書き出している", "GateProfile" in on_init)

on_deinit = body_of("OnDeinit")
check("OnDeinit でタイマーを止めている", "EventKillTimer" in on_deinit)
check("OnDeinit で画面の表示を片づけている", "RemoveGateStatus" in on_deinit)

# ── 3) 新規注文の前に、サイトと AI の判断を見ているか ──
open_trade = body_of("OpenTrade")
check("OpenTrade がある", bool(open_trade))
check("サイトの稼働／停止を見ている", "SiteAllowsEntry" in open_trade, "")
check("AIの見張りを見ている", "AiAllowsEntry" in open_trade, "")
check("止めたときに数えている", "AiCountSkip" in open_trade)
check("入ったら回数を記録している", "MarkSiteEntry" in open_trade)

# 停止の判断は、実際に発注する前でなければ意味がない
if open_trade:
    order = re.search(r"g_trade\.(Buy|Sell)\s*\(", open_trade)
    gate = open_trade.find("SiteAllowsEntry")
    ai = open_trade.find("AiAllowsEntry")
    check(
        "判断は発注より前にある",
        order is not None and 0 <= gate < order.start() and 0 <= ai < order.start(),
        f"停止={gate} AI={ai} 発注={order.start() if order else '無し'}",
    )

# ── 4) ロットはサイトの設定を使うか ──
calc_lot = body_of("CalcLot")
check("ロットはサイトの設定から取る", "SiteLot" in calc_lot, calc_lot[:80])

# ── 5) この EA の建玉を、取りこぼさず数えているか ──
magic = body_of("IsOrbitMagic")
for axis in ("InpM1Magic", "InpH1Magic", "InpM30Magic"):
    check(f"{axis} を自分のものと数える", axis in magic, magic[:120])

# ── 6) ナンピンを使うときも同じ関門を通るか ──
basket = body_of("ManageM1Basket")
check("ナンピン追加も AI の見張りを通す", "AiAllowsEntry" in basket)
check("ナンピン追加もサイトの指示を見る", "SiteAllowsEntry" in basket)

# ── 7) 売買ロジックに手を入れていないか（触ってよいのは連携だけ）──
check("エントリー条件（リテスト）はそのまま", "retestBuy" in src and "retestSell" in src)
check("トレールはそのまま", "ManageTrail" in src)
check("日次損失リミットはそのまま", "TodayRealizedPnL" in src)

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
