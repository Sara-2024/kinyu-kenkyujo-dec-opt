"""AIリスク監督に渡す数値を、MT5 のローソク足から作る。

ここは計算だけ。MT5 にも外部にも触らないので、作り物の足で試験できる。

約束ごと:
  * 足はすべて「確定した足」だけを渡す（形成中の足は呼び出し側で落とす）。
    スイングの判定に未来の足は使わない（右側に必要な本数がそろった山谷だけを採る）。
  * 時刻は MT5 が返す UNIX 秒＝ブローカーのサーバー時計。ここで現在時刻を取らない。
  * 取得できた範囲の最高値は window_high と呼ぶ。史上最高値ではないので、そう呼ばない。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

Bar = dict[str, Any]  # time(int), open, high, low, close


# ────────────────────────────────
# 指標
# ────────────────────────────────
def ema(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    out = sum(values[:period]) / period
    for v in values[period:]:
        out = v * k + out * (1.0 - k)
    return out


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """EMA の推移（傾きを見るのに使う）。先頭 period-1 本は空になるので詰めて返す。"""
    if period <= 0 or len(values) < period:
        return []
    k = 2.0 / (period + 1.0)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def atr_wilder(bars: Sequence[Bar], period: int) -> float | None:
    """EA と同じ Wilder の RMA。足りなければ None。"""
    if period <= 0 or len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    out = sum(trs[:period]) / period
    for tr in trs[period:]:
        out = (out * (period - 1) + tr) / period
    return out


def adx(bars: Sequence[Bar], period: int = 14) -> float | None:
    """向きの強さ。レンジか流れかの目安に使う（これ単体では停止理由にしない）。"""
    if len(bars) < period * 2 + 1:
        return None
    plus: list[float] = []
    minus: list[float] = []
    trs: list[float] = []
    for i in range(1, len(bars)):
        up = bars[i]["high"] - bars[i - 1]["high"]
        down = bars[i - 1]["low"] - bars[i]["low"]
        plus.append(up if (up > down and up > 0) else 0.0)
        minus.append(down if (down > up and down > 0) else 0.0)
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    def rma(xs: list[float]) -> list[float]:
        out = [sum(xs[:period]) / period]
        for x in xs[period:]:
            out.append((out[-1] * (period - 1) + x) / period)
        return out

    tr_s, plus_s, minus_s = rma(trs), rma(plus), rma(minus)
    dx: list[float] = []
    for tr, p, m in zip(tr_s, plus_s, minus_s):
        if tr <= 0:
            continue
        pdi, mdi = 100.0 * p / tr, 100.0 * m / tr
        if pdi + mdi <= 0:
            continue
        dx.append(100.0 * abs(pdi - mdi) / (pdi + mdi))
    if len(dx) < period:
        return None
    out = sum(dx[:period]) / period
    for v in dx[period:]:
        out = (out * (period - 1) + v) / period
    return out


# ────────────────────────────────
# 山と谷（確定したものだけ）
# ────────────────────────────────
def swing_points(bars: Sequence[Bar], left: int = 2, right: int = 2) -> tuple[list[Bar], list[Bar]]:
    """左右に指定本数ぶん確定している山と谷。右側が足りない足は候補にしない。"""
    highs: list[Bar] = []
    lows: list[Bar] = []
    for i in range(left, len(bars) - right):
        window = bars[i - left : i + right + 1]
        if bars[i]["high"] >= max(b["high"] for b in window):
            highs.append(bars[i])
        if bars[i]["low"] <= min(b["low"] for b in window):
            lows.append(bars[i])
    return highs, lows


def last_completed(bars: Sequence[Bar]) -> Bar | None:
    """日足・週足の「前の期間」。最後の足は形成中なので1本前を返す。"""
    return bars[-2] if len(bars) >= 2 else None


# ────────────────────────────────
# 重要な水準
# ────────────────────────────────
def build_levels(
    price: float,
    *,
    h1: Sequence[Bar],
    h4: Sequence[Bar],
    d1: Sequence[Bar],
    w1: Sequence[Bar],
) -> tuple[dict[str, float], dict[str, float]]:
    """上側（抵抗）と下側（支持）の候補を名前つきで返す。名前は evidence の項目名になる。"""
    above: dict[str, float] = {}
    below: dict[str, float] = {}

    def put(name: str, value: float | None) -> None:
        if value is None:
            return
        if value > price:
            above[name] = value
        elif value < price:
            below[name] = value

    pd = last_completed(d1)
    pw = last_completed(w1)
    if pd:
        put("prev_day_high", pd["high"])
        put("prev_day_low", pd["low"])
    if pw:
        put("prev_week_high", pw["high"])
        put("prev_week_low", pw["low"])

    for name, bars in (("swing_h1", h1), ("swing_h4", h4)):
        hs, ls = swing_points(bars)
        # 現在値より上で一番近い山／下で一番近い谷
        ups = [b["high"] for b in hs if b["high"] > price]
        downs = [b["low"] for b in ls if b["low"] < price]
        if ups:
            above[f"{name}_high"] = min(ups)
        if downs:
            below[f"{name}_low"] = max(downs)

    if h1:
        put("window_high", max(b["high"] for b in h1))
        put("window_low", min(b["low"] for b in h1))
    return above, below


def _break_state(
    m1: Sequence[Bar],
    level: float | None,
    direction: int,
    tol: float,
    lookback: int = 360,
) -> dict[str, Any]:
    """その水準を抜けたか、抜けたあと戻って試したか（リテスト）。

    direction=+1 は上抜け、-1 は下抜け。戻り足は「確定した足の終値」だけで見る。
    """
    out: dict[str, Any] = {"broken": 0, "bars_since_break": None, "retest_seen": 0, "retest_confirmed": 0}
    if level is None or not m1:
        return out

    def beyond(bar: Bar) -> bool:
        return bar["close"] > level if direction > 0 else bar["close"] < level

    def touching(bar: Bar) -> bool:
        return bar["low"] <= level + tol if direction > 0 else bar["high"] >= level - tol

    window = list(m1[-lookback:])
    if not any(beyond(bar) for bar in window):
        return out
    # 直近の「抜けた瞬間」の足。抜けたあとの足ではなく、内側から外側へ移った足を探す。
    idx = 0
    for i in range(1, len(window)):
        if beyond(window[i]) and not beyond(window[i - 1]):
            idx = i
    out["broken"] = 1
    out["bars_since_break"] = len(window) - 1 - idx
    after = window[idx + 1 :]
    if not after:
        return out

    # 突破後に水準の許容幅まで戻ったか（リテスト）
    first_touch = None
    for i, bar in enumerate(after):
        if touching(bar):
            first_touch = i
            break
    if first_touch is None:
        return out
    out["retest_seen"] = 1
    # 戻ったあと、もう一度その方向で終値が水準の外に出たら成立
    out["retest_confirmed"] = 1 if any(beyond(bar) for bar in after[first_touch + 1 :]) else 0
    return out


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(float(value), digits)


def _iso(unix_sec: int | float | None) -> str | None:
    if unix_sec is None:
        return None
    # MT5 の時刻はサーバー時計。タイムゾーン記号は付けず、サーバー時計であることを名前で示す
    return datetime.fromtimestamp(int(unix_sec), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def build_features(
    *,
    bid: float,
    ask: float,
    m1: Sequence[Bar],
    h1: Sequence[Bar],
    h4: Sequence[Bar],
    d1: Sequence[Bar],
    w1: Sequence[Bar],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """AI に渡す数値一式。足りないものは None のまま返す（推測で埋めない）。"""
    price = (bid + ask) / 2.0 if bid and ask else (bid or ask)
    ema_period = int(profile.get("ema_period", 200))
    atr_period = int(profile.get("atr_period", 14))
    retest_tol_mult = float(profile.get("retest_tolerance_atr", 0.12))

    atr_m1 = atr_wilder(m1, atr_period)
    atr_h1 = atr_wilder(h1, atr_period)
    ema_m1 = ema([b["close"] for b in m1], ema_period)
    ema_h1_series = ema_series([b["close"] for b in h1], ema_period)
    ema_h1 = ema_h1_series[-1] if ema_h1_series else None
    ema_h4 = ema([b["close"] for b in h4], ema_period)

    above, below = build_levels(price, h1=h1, h4=h4, d1=d1, w1=w1)
    res_name, res_level = (min(above.items(), key=lambda kv: kv[1] - price) if above else (None, None))
    sup_name, sup_level = (max(below.items(), key=lambda kv: kv[1] - price) if below else (None, None))

    # 予定 SL 幅（EA の設定から）。距離を「損切り何個ぶんか」で見るのに使う
    sl_m1 = None
    if atr_m1:
        if profile.get("m1_nanpin_enabled"):
            step = atr_m1 * float(profile.get("m1_nanpin_step_atr", 1.0))
            sl_m1 = step * (int(profile.get("m1_nanpin_max_adds", 3)) + int(profile.get("m1_nanpin_sl_room", 4)))
        else:
            sl_m1 = atr_m1 * float(profile.get("m1_sl_atr_mult", 5.0))
    sl_h1 = atr_h1 * float(profile.get("h1_sl_atr_mult", 1.5)) if atr_h1 else None

    tol = (atr_m1 or 0.0) * retest_tol_mult
    up_break = _break_state(m1, res_level, +1, tol)
    down_break = _break_state(m1, sup_level, -1, tol)

    closes_m1 = [b["close"] for b in m1]
    move_15 = (closes_m1[-1] - closes_m1[-16]) if len(closes_m1) >= 16 else None
    closes_h1 = [b["close"] for b in h1]
    move_h1_6 = (closes_h1[-1] - closes_h1[-7]) if len(closes_h1) >= 7 else None

    # 押し目・戻りができているか（直近30本の伸びに対する引き戻しの割合）
    pull_up = pull_down = None
    if len(m1) >= 30:
        seg = m1[-30:]
        hi = max(b["high"] for b in seg)
        lo = min(b["low"] for b in seg)
        span = hi - lo
        if span > 0:
            pull_up = (hi - closes_m1[-1]) / span  # 上げたあと、どれだけ引いたか
            pull_down = (closes_m1[-1] - lo) / span

    slope_h1 = None
    if len(ema_h1_series) >= 21 and atr_h1:
        slope_h1 = (ema_h1_series[-1] - ema_h1_series[-21]) / atr_h1

    alternation = None
    if len(closes_h1) >= 21:
        signs = [1 if closes_h1[i] > closes_h1[i - 1] else -1 for i in range(len(closes_h1) - 20, len(closes_h1))]
        alternation = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i - 1])

    htf_align = None
    if ema_h1 is not None and ema_h4 is not None and closes_h1 and h4:
        h1_dir = 1 if closes_h1[-1] > ema_h1 else -1
        h4_dir = 1 if h4[-1]["close"] > ema_h4 else -1
        htf_align = h1_dir if h1_dir == h4_dir else 0

    spread = round(ask - bid, 3) if ask and bid else None

    f: dict[str, Any] = {
        "price_bid": _round(bid),
        "price_ask": _round(ask),
        "price_mid": _round(price),
        "spread_usd": spread,
        "spread_atr_m1": _round(spread / atr_m1, 3) if (spread is not None and atr_m1) else None,
        "atr_m1": _round(atr_m1),
        "atr_h1": _round(atr_h1),
        "ema200_m1": _round(ema_m1),
        "ema200_h1": _round(ema_h1),
        "ema_dev_m1_atr": _round((price - ema_m1) / atr_m1, 3) if (ema_m1 and atr_m1) else None,
        "ema_dev_h1_atr": _round((price - ema_h1) / atr_h1, 3) if (ema_h1 and atr_h1) else None,
        "ema200_h1_slope_atr": _round(slope_h1, 3),
        "adx_h1": _round(adx(h1), 1),
        "alternation_h1_20": alternation,
        "htf_alignment": htf_align,
        "planned_sl_m1": _round(sl_m1),
        "planned_sl_h1": _round(sl_h1),
        "move_m1_15bars": _round(move_15),
        "move_m1_15bars_atr": _round(move_15 / atr_m1, 3) if (move_15 is not None and atr_m1) else None,
        "move_h1_6bars": _round(move_h1_6),
        "move_h1_6bars_atr": _round(move_h1_6 / atr_h1, 3) if (move_h1_6 is not None and atr_h1) else None,
        "pullback_from_high_ratio": _round(pull_up, 3),
        "pullback_from_low_ratio": _round(pull_down, 3),
        "nearest_resistance_name": res_name,
        "nearest_resistance": _round(res_level),
        "nearest_support_name": sup_name,
        "nearest_support": _round(sup_level),
        "dist_to_resistance": _round(res_level - price) if res_level is not None else None,
        "dist_to_support": _round(price - sup_level) if sup_level is not None else None,
        "resistance_break_state": up_break["broken"],
        "resistance_bars_since_break": up_break["bars_since_break"],
        "resistance_retest_seen": up_break["retest_seen"],
        "resistance_retest_confirmed": up_break["retest_confirmed"],
        "support_break_state": down_break["broken"],
        "support_bars_since_break": down_break["bars_since_break"],
        "support_retest_seen": down_break["retest_seen"],
        "support_retest_confirmed": down_break["retest_confirmed"],
        "window_tf": "H1",
        "window_bars": len(h1),
        "window_start": _iso(h1[0]["time"]) if h1 else None,
        "window_high": _round(max((b["high"] for b in h1), default=None)) if h1 else None,
        "window_low": _round(min((b["low"] for b in h1), default=None)) if h1 else None,
        "last_closed_m1_time": _iso(m1[-1]["time"]) if m1 else None,
    }
    pd_bar, pw_bar = last_completed(d1), last_completed(w1)
    f["prev_day_high"] = _round(pd_bar["high"]) if pd_bar else None
    f["prev_day_low"] = _round(pd_bar["low"]) if pd_bar else None
    f["prev_week_high"] = _round(pw_bar["high"]) if pw_bar else None
    f["prev_week_low"] = _round(pw_bar["low"]) if pw_bar else None

    # 距離を ATR と予定 SL 幅で正規化（「近い」を数字で言えるようにする）
    for side, dist in (("resistance", f["dist_to_resistance"]), ("support", f["dist_to_support"])):
        f[f"dist_to_{side}_atr"] = _round(dist / atr_m1, 3) if (dist is not None and atr_m1) else None
        f[f"dist_to_{side}_sl_m1"] = _round(dist / sl_m1, 3) if (dist is not None and sl_m1) else None
        f[f"dist_to_{side}_sl_h1"] = _round(dist / sl_h1, 3) if (dist is not None and sl_h1) else None
    return f


def data_is_usable(features: dict[str, Any]) -> bool:
    """判定を求めてよい最低限のデータがあるか（無いのに AI に聞かない）。"""
    need = ("atr_m1", "atr_h1", "price_mid", "ema200_h1")
    return all(features.get(k) is not None for k in need)


def missing_fields(features: dict[str, Any], keys: Iterable[str]) -> list[str]:
    return [k for k in keys if features.get(k) is None]
