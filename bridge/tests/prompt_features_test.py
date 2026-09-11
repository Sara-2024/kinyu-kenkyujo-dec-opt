"""AI に渡す数値と、プロンプトの説明が食い違っていないことを確かめる。

    python3 bridge/tests/prompt_features_test.py

説明の無い項目は、AI が名前から意味を推測することになる。
たとえば `dist_to_resistance_atr` を H1 の ATR 基準だと解釈すると、
実際には $3 しか離れていないのに「まだ遠い」と判断してしまう。
項目を足したら、`api/_lib/risk.ts` の【数値の読み方】にも必ず足すこと。
"""
from __future__ import annotations

import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "bridge"))

import risk_features as rf  # noqa: E402

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


def bars(n: int, start: float, step: float, tf: int) -> list[dict]:
    random.seed(1)
    out = []
    price = start
    for i in range(n):
        price += step + random.uniform(-0.3, 0.3)
        out.append({"time": 1757000000 + i * tf, "open": price, "high": price + 0.4, "low": price - 0.4, "close": price})
    return out


features = rf.build_features(
    bid=3320.0,
    ask=3320.3,
    m1=bars(400, 3300, 0.02, 60),
    h1=bars(300, 3200, 0.3, 3600),
    h4=bars(150, 3100, 1.0, 14400),
    d1=bars(40, 3000, 3.0, 86400),
    w1=bars(12, 2900, 12.0, 604800),
    profile={"ema_period": 200, "atr_period": 14, "retest_tolerance_atr": 0.12, "h1_sl_atr_mult": 1.5},
)

risk_ts = (ROOT / "api" / "_lib" / "risk.ts").read_text(encoding="utf-8")
prompt = risk_ts.split("const SYSTEM_PROMPT = `", 1)[1].split("`", 1)[0]

# ── 1. すべての項目に説明があること ──
# `prev_day_high/low` のようにまとめて書いてある項目も拾えるよう、
# 「名前そのもの」と「末尾を省いた書き方」の両方を見る。
def described(key: str) -> bool:
    if key in prompt:
        return True
    m = re.match(r"^(.*)_(high|low)$", key)
    if m and f"{m.group(1)}_high/low" in prompt:
        return True
    return False


missing = sorted(k for k in features if not described(k))
check(f"AI に渡す {len(features)} 項目すべてに説明がある", not missing, "説明が無い: " + ", ".join(missing))

# ── 2. 説明にあるのに、実際には渡していない項目が無いこと ──
mentioned = set(re.findall(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,4})\b", prompt))
known = set(features) | {
    # プロンプトが説明のために使う、features 以外の言葉
    "ema_period", "atr_period", "buy_assessment", "sell_assessment",
    "buy_reason_codes", "sell_reason_codes", "prev_day_high", "prev_day_low",
    "prev_week_high", "prev_week_low", "swing_h1_high", "swing_h4_low",
}
ghosts = sorted(m for m in mentioned if m not in known and not m.startswith(("dist_to", "nearest_", "resistance_", "support_", "move_", "ema_dev_", "window_", "price_", "planned_sl")))
check("説明にあるのに渡していない項目が無い", not ghosts, "実在しない: " + ", ".join(ghosts))

# ── 3. 取り違えやすい単位が明記されていること ──
check("ATR の基準足を書いてある", "atr_m1 の何個ぶん" in prompt)
check("損切りは『幅』であって価格でないと書いてある", "価格ではなく幅" in prompt)
check("null は推測で埋めないと書いてある", "推測で埋めない" in prompt)
check("上抜け済みの高値が支持側に出ることを書いてある", "nearest_support_name に *_high" in prompt)
check("EMA の期間が 200 固定でないことを書いてある", "期間は ema_period に従う" in prompt)

# ── 4. プロンプトを変えたら版も上げる ──
version = re.search(r"PROMPT_VERSION = '([^']+)'", risk_ts).group(1)
check("プロンプトの版が入っている", bool(version) and version >= "2026-09-10.1", version)

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
