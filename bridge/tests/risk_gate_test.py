"""RiskGate の停止・再開のふるまいを、偽の MT5 と偽のサーバーで確かめる。"""
from __future__ import annotations

import asyncio
import os
import random
import pathlib
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ["TRELAB_RISK_TOKEN"] = "secret"
os.environ["RISK_MIN_BLOCK_SEC"] = "2"
os.environ["RISK_UNBLOCK_CONFIRM"] = "2"

import risk_features as rf  # noqa: E402
from risk_gate import GV_BUY, GV_MODE, GV_SELL, GV_SEQ, GV_UNTIL, MODE_ON, RiskConfig, RiskGate  # noqa: E402

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
    out = []
    price = start
    for i in range(n):
        price += step + random.uniform(-0.3, 0.3)
        out.append(
            {
                "time": 1757000000 + i * tf,
                "open": price,
                "high": price + 0.4,
                "low": price - 0.4,
                "close": price,
            }
        )
    return out


class FakeMT:
    """必要なところだけ持つ偽のコントローラ。"""

    def __init__(self) -> None:
        self.gate: dict[str, float] = {}
        self.desired_value = 1.0
        self.mode = "demo"

    async def set_variables(self, values: dict[str, float]) -> bool:
        self.gate.update(values)
        return True

    async def account_mode(self) -> str:
        return self.mode

    async def last_closed_m1(self, symbol: str) -> int:
        return 1757000000

    async def symbol_tick(self, symbol: str):
        return {"bid": 3320.0, "ask": 3320.3}

    async def risk_snapshot(self, *, symbol, bars_m1, bars_h1, bars_h4):
        random.seed(3)
        return {
            "symbol": "XAUUSD",
            "bid": 3320.0,
            "ask": 3320.3,
            "m1": bars(400, 3300, 0.02, 60),
            "h1": bars(300, 3200, 0.3, 3600),
            "h4": bars(150, 3100, 1.0, 14400),
            "d1": bars(40, 3000, 3.0, 86400),
            "w1": bars(12, 2900, 12.0, 604800),
            "profile": {"ema_period": 200, "atr_period": 14, "retest_tolerance_atr": 0.12, "h1_sl_atr_mult": 1.5},
            "account": 221520,
            "bar_time": 1757000000,
            "server_time": "2026-09-09T07:00:00",
            "server_epoch": 1757400000,
        }


def decision(buy: str, sell: str, seq: int, *, buy_codes=(), sell_codes=(), ttl=180) -> dict:
    return {
        "decision": {
            "seq": seq,
            "issued_at": "2026-09-09T07:00:00Z",
            "expires_at": "2026-09-09T07:03:00Z",
            "ttl_sec": ttl,
            "account": 221520,
            "symbol": "XAUUSD",
            "bar_time": 1757000000,
            "model": "gemini-3.5-flash",
            "prompt_version": "test",
            "buy": buy,
            "sell": sell,
            "reason_codes": {"buy": list(buy_codes), "sell": list(sell_codes)},
            "evidence": [{"field": "atr_m1", "value": 0.7, "why": "test"}],
            "summary": "テスト",
            "dropped": [],
        }
    }


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    mt = FakeMT()
    gate = RiskGate(mt, RiskConfig(), "test-room", tmp)
    gate.account_mode = "demo"
    gate._decide_mode()
    check("デモ口座では実際に反映する", gate.mode == MODE_ON, f"mode={gate.mode} {gate.mode_reason}")

    replies: list = []

    def fake_post(payload):
        item = replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    gate._post_blocking = fake_post  # type: ignore[method-assign]
    # ここで見たいのは停止と再開のふるまいなので、聞く条件は満たしている前提にする
    always = lambda features, profile: (True, "テスト")  # noqa: E731
    gate._entry_possible = always  # type: ignore[method-assign]

    # 1) 買いだけ停止
    replies.append(decision("BLOCK", "ALLOW", 1, buy_codes=["NEAR_RESISTANCE"]))
    await gate.evaluate(reason="test")
    check("買いだけ停止した", gate.buy.blocked and not gate.sell.blocked)
    check("指令ファイルに買い0・売り1", mt.gate[GV_BUY] == 0.0 and mt.gate[GV_SELL] == 1.0, str(mt.gate))
    check("有効期限を書いた", mt.gate[GV_UNTIL] == 1757400000 + 180)
    check("モードと連番を書いた", mt.gate[GV_MODE] == MODE_ON and mt.gate[GV_SEQ] == 1)

    # 2) 材料不足では新しい停止を作らない（売りは許可のまま）
    replies.append(decision("INSUFFICIENT_DATA", "INSUFFICIENT_DATA", 2))
    await gate.evaluate(reason="test")
    check("材料不足で売りを止めない", not gate.sell.blocked)
    check("材料不足で買いの停止は続く", gate.buy.blocked)

    # 3) 1回 ALLOW では再開しない（連続確認が必要）
    replies.append(decision("ALLOW", "ALLOW", 3))
    await gate.evaluate(reason="test")
    check("1回の許可では再開しない", gate.buy.blocked)

    # 4) 最短の停止時間を満たす前は、連続 ALLOW でも再開しない
    replies.append(decision("ALLOW", "ALLOW", 4))
    await gate.evaluate(reason="test")
    held = time.time() - gate.buy.since
    if held < gate.cfg.min_block_sec:
        check("最短停止時間の前は再開しない", gate.buy.blocked, f"held={held:.1f}")
    else:
        check("最短停止時間の前は再開しない（時間経過のため判定省略）", True)

    # 5) 時間を満たしてから連続 ALLOW で再開
    gate.buy.since = time.time() - 10
    replies.append(decision("ALLOW", "ALLOW", 5))
    await gate.evaluate(reason="test")
    check("条件がそろえば再開する", not gate.buy.blocked)
    check("再開が指令ファイルに出る", mt.gate[GV_BUY] == 1.0)

    # 6) 通信の失敗では新しい停止を作らない・前の判定を残す
    replies.append(OSError("接続できません"))
    before = (gate.buy.blocked, gate.sell.blocked, gate.applied_seq)
    await gate.evaluate(reason="test")
    check("通信失敗で状態を変えない", (gate.buy.blocked, gate.sell.blocked, gate.applied_seq) == before)
    check("通信状態がエラーになる", gate.comms == "error")

    # 7) 古い応答は無視する
    replies.append(decision("BLOCK", "BLOCK", 2, buy_codes=["NEAR_RESISTANCE"], sell_codes=["NEAR_SUPPORT"]))
    await gate.evaluate(reason="test")
    check("古い連番の応答は使わない", not gate.buy.blocked and not gate.sell.blocked)

    # 8) 売りだけ停止
    replies.append(decision("ALLOW", "BLOCK", 9, sell_codes=["NEAR_SUPPORT"]))
    await gate.evaluate(reason="test")
    check("売りだけ停止した", gate.sell.blocked and not gate.buy.blocked)
    check("指令ファイルに売り0・買い1", mt.gate[GV_SELL] == 0.0 and mt.gate[GV_BUY] == 1.0)

    # 9) 本番口座では自動で実運用にしない
    live = RiskGate(FakeMT(), RiskConfig(), "test-room", tmp)
    live.account_mode = "real"
    live._decide_mode()
    check("本番口座は記録のみで始まる", live.mode == 1.0, f"mode={live.mode}")
    live.set_mode("on")
    live._decide_mode()
    check("画面から実反映に変えられる", live.mode == MODE_ON)

    # 10) 記録が残る（実反映か記録のみかを区別している）
    check("判定の記録が残る", len(gate.history) >= 5 and "enforced" in gate.history[0])
    check("記録ファイルができる", (tmp / "risk_decisions.jsonl").is_file())

    # 11) 画面に出す状態
    st = gate.status({"ai_skip_buy": 3})
    check("画面用の状態がそろう", st["buy"]["blocked"] is False and st["sell"]["blocked"] is True and st["metrics"]["skipped"]["ai_skip_buy"] == 3)

    # 12) データ不足なら AI に聞きにいかない
    class ThinMT(FakeMT):
        async def risk_snapshot(self, **kw):
            snap = await FakeMT.risk_snapshot(self, **kw)
            snap["m1"] = snap["m1"][:5]
            snap["h1"] = snap["h1"][:5]
            return snap

    thin = RiskGate(ThinMT(), RiskConfig(), "test-room", tmp)
    thin.account_mode = "demo"
    thin._decide_mode()
    thin._entry_possible = always  # type: ignore[method-assign]
    called = []
    thin._post_blocking = lambda payload: called.append(payload)  # type: ignore[method-assign]
    await thin.evaluate(reason="test")
    check("足が足りないときは問い合わせない", not called)


    # 13) AI の応答が遅くても、ブリッジの他の仕事は止まらない
    slow = RiskGate(FakeMT(), RiskConfig(), "test-room", tmp)
    slow.account_mode = "demo"
    slow._decide_mode()
    slow._entry_possible = always  # type: ignore[method-assign]

    def slow_post(payload):
        time.sleep(2.0)          # 遅い外部AIのつもり
        return decision("ALLOW", "ALLOW", 50)

    slow._post_blocking = slow_post  # type: ignore[method-assign]
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    t0 = time.time()
    await slow.evaluate(reason="test")
    beat.cancel()
    took = time.time() - t0
    check("遅い応答でも他の処理が動き続ける", ticks >= 20 and took >= 1.9, f"ticks={ticks} took={took:.1f}s")

    # 14) 呼び出しが重ならない
    over = RiskGate(FakeMT(), RiskConfig(), "test-room", tmp)
    over.account_mode = "demo"
    over._decide_mode()
    over._entry_possible = always  # type: ignore[method-assign]
    calls = []

    def counting(payload):
        calls.append(payload)
        time.sleep(0.5)
        return decision("ALLOW", "ALLOW", 60 + len(calls))

    over._post_blocking = counting  # type: ignore[method-assign]
    await asyncio.gather(over.evaluate(reason="a"), over.evaluate(reason="b"), over.evaluate(reason="c"))
    check("同時に呼ばれても1回だけ問い合わせる", len(calls) == 1, f"calls={len(calls)}")


    # 15) 画面でモードを切り替えたら、判定を待たずに指令ファイルへ出る
    sw = RiskGate(FakeMT(), RiskConfig(), "test-room", tmp)
    sw.account_mode = "demo"
    sw.set_mode("on")
    sw._decide_mode()
    sw._entry_possible = always  # type: ignore[method-assign]
    await sw._sync_gate()
    check("反映にすると指令ファイルが 2 になる", sw.mt.gate.get(GV_MODE) == MODE_ON, str(sw.mt.gate))
    sw.set_mode("shadow")
    sw._decide_mode()
    await sw._sync_gate()
    check("記録のみに切り替えると 1 になる", sw.mt.gate.get(GV_MODE) == 1.0, str(sw.mt.gate))
    before = dict(sw.mt.gate)
    await sw._sync_gate()
    check("変化が無ければ書き直さない", sw.mt.gate == before)

    # 16) AI 側が上限・混雑のときは、間隔をあけて試す（無料枠を数分で使い切らない）
    bo = RiskGate(FakeMT(), RiskConfig(), "test-room", tmp)
    bo.account_mode = "demo"
    bo._decide_mode()
    bo._entry_possible = always  # type: ignore[method-assign]
    import urllib.error, io

    def quota(payload):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", None, io.BytesIO(b"quota"))

    bo._post_blocking = quota  # type: ignore[method-assign]
    await bo.evaluate(reason="test")
    check("429 のあとは待機に入る", bo._waiting_after_error() and bo._error_wait == 30.0, f"wait={bo._error_wait}")
    await bo.evaluate(reason="test")
    check("失敗が続くと間隔が広がる", bo._error_wait == 60.0, f"wait={bo._error_wait}")
    bo._post_blocking = lambda payload: decision("ALLOW", "ALLOW", 99)  # type: ignore[method-assign]
    await bo.evaluate(reason="test")
    check("成功したら間隔は元に戻る", bo._error_wait == 0.0 and not bo._waiting_after_error())


    # 17) 入る見込みが無いときは AI に聞かない（費用をかけない）
    quiet = RiskGate(FakeMT(), RiskConfig(), "test-room", tmp)
    quiet.account_mode = "demo"
    quiet._decide_mode()
    asked = []
    quiet._post_blocking = lambda payload: (asked.append(payload), decision("ALLOW", "ALLOW", 200))[1]  # type: ignore[method-assign]

    profile = {"m1_min_atr_usd": 2.0, "retest_bars": 6, "h1_enabled": True}
    far = {
        "atr_m1": 3.0,
        "dist_to_resistance_atr": 12.0,
        "dist_to_support_atr": 9.0,
        "move_m1_15bars_atr": 0.4,
        "resistance_break_state": 0,
        "support_break_state": 0,
    }
    ok, why = quiet._entry_possible(far, profile)
    check("水準から遠ければ聞かない", not ok, why)

    near = dict(far, dist_to_resistance_atr=0.8)  # 既定は ATR 1個以内
    ok, why = quiet._entry_possible(near, profile)
    check("水準が近ければ聞く", ok, why)

    broke = dict(far, resistance_break_state=1, resistance_bars_since_break=3)
    check("抜けた直後は聞く", quiet._entry_possible(broke, profile)[0])

    ran = dict(far, move_m1_15bars_atr=-4.6)  # 既定は ATR 4個以上
    check("急に動いた直後は聞く", quiet._entry_possible(ran, profile)[0])

    thin_atr = dict(far, atr_m1=0.5)
    check("ATRが下限未満で水準も遠ければ聞かない", quiet._entry_possible(thin_atr, profile)[0] is False)
    check("H1軸も止めていれば聞かない", quiet._entry_possible(thin_atr, dict(profile, h1_enabled=False))[0] is False)

    # 実際に evaluate を回して、静かな場面では問い合わせが起きないこと
    quiet._entry_possible = lambda f, p: (False, "静か")  # type: ignore[method-assign]
    await quiet.evaluate(reason="test")
    check("静かな場面では問い合わせが1回も出ない", not asked, str(len(asked)))
    check("聞かなくても期限は延ばす（EAを止めない）", quiet.mt.gate.get(GV_UNTIL, 0) > 1757400000)
    check("見送りの回数を数える", quiet.skipped_calls == 1)


asyncio.run(main())
print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
