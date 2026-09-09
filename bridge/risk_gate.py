"""AIリスク監督：新規注文の許可・停止を、買い／売り別に決める係。

流れ:
    MT5 の足 → risk_features で数値化 → サイトの /api/risk（Gemini）→ 検証済みの判定
    → ここで「停止／再開の条件」を当てて → 指令ファイル（trelab_gate.ini）に数字で書く
    → EA が新規注文の直前に読む。

守っていること:
    * EA を待たせない。通信はここ（ブリッジ）の中だけで完結し、EA は書かれた数字を見るだけ。
    * 停止は方向別。買いを止めても売りは止めない。
    * 迷い（INSUFFICIENT_DATA）や通信の失敗を、新しい停止の理由にしない。
    * 一度止めたら、時間切れでは再開しない。最新のデータで解除条件を満たしたときだけ再開する。
    * 判定が期限切れになったら、EA 側で新規注文だけを止める（決済の管理は続く）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import risk_features as rf

log = logging.getLogger("risk")

# 指令ファイルに書く数字（TradingGate.mqh は「名前=数値」しか運べない）
GV_MODE = "AI_GATE_MODE"  # 0=切 1=記録だけ 2=実際に止める
GV_BUY = "AI_BUY_ALLOWED"
GV_SELL = "AI_SELL_ALLOWED"
GV_UNTIL = "AI_GATE_UNTIL"  # サーバー時計の UNIX 秒。これを過ぎたら EA は新規を止める
GV_SEQ = "AI_GATE_SEQ"

MODE_OFF, MODE_SHADOW, MODE_ON = 0.0, 1.0, 2.0
MODE_NAMES = {MODE_OFF: "off", MODE_SHADOW: "shadow", MODE_ON: "on"}
MODE_VALUES = {"off": MODE_OFF, "shadow": MODE_SHADOW, "on": MODE_ON}


def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, "").strip() or default)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, "").strip() or default)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass
class RiskConfig:
    """しきい値と間隔。すべて環境変数で変えられる（初期値の根拠は AGENTS.md に書く）。"""

    enabled: bool = field(default_factory=lambda: _env_bool("RISK_GATE_ENABLED", True))
    endpoint: str = field(
        default_factory=lambda: _env_str("RISK_API_URL", "https://kinyu-kenkyujo-dec-opt.vercel.app/api/risk")
    )
    token: str = field(default_factory=lambda: _env_str("TRELAB_RISK_TOKEN"))
    symbol: str = field(default_factory=lambda: _env_str("RISK_SYMBOL"))
    # 確定 M1 足ごとに1回（60秒）。人数が増えたら伸ばす
    eval_sec: float = field(default_factory=lambda: _env_float("RISK_EVAL_SEC", 60.0))
    # 重要水準まで ATR 1個ぶんより近ければ、足の途中でも見直す
    near_level_atr: float = field(default_factory=lambda: _env_float("RISK_NEAR_LEVEL_ATR", 1.0))
    near_recheck_sec: float = field(default_factory=lambda: _env_float("RISK_NEAR_RECHECK_SEC", 30.0))
    # 停止したら最低これだけは続ける（数十秒での付け外しを防ぐ）
    min_block_sec: float = field(default_factory=lambda: _env_float("RISK_MIN_BLOCK_SEC", 180.0))
    # 再開に必要な「連続で問題なし」の回数
    unblock_confirm: int = field(default_factory=lambda: _env_int("RISK_UNBLOCK_CONFIRM", 2))
    http_timeout: float = field(default_factory=lambda: _env_float("RISK_HTTP_TIMEOUT", 15.0))
    # 本番口座で自動的に実運用へ入れない。demo と確認できたときだけ on から始める
    live_mode: str = field(default_factory=lambda: _env_str("RISK_LIVE_MODE", "shadow"))
    demo_mode: str = field(default_factory=lambda: _env_str("RISK_DEMO_MODE", "on"))
    history_keep: int = field(default_factory=lambda: _env_int("RISK_HISTORY_KEEP", 40))
    bars_m1: int = field(default_factory=lambda: _env_int("RISK_BARS_M1", 600))
    bars_h1: int = field(default_factory=lambda: _env_int("RISK_BARS_H1", 400))
    bars_h4: int = field(default_factory=lambda: _env_int("RISK_BARS_H4", 200))


@dataclass
class DirectionState:
    """買い（または売り）の停止状態。"""

    blocked: bool = False
    since: float = 0.0  # 停止した時刻（ローカル時計・経過時間の計測用）
    reasons: list[str] = field(default_factory=list)
    level_name: str | None = None
    level_value: float | None = None
    allow_streak: int = 0
    block_count: int = 0
    blocked_seconds: float = 0.0

    def as_dict(self, now: float) -> dict[str, Any]:
        held = (now - self.since) if (self.blocked and self.since) else 0.0
        return {
            "blocked": self.blocked,
            "reasons": list(self.reasons),
            "level_name": self.level_name,
            "level_value": self.level_value,
            "held_sec": round(held, 1),
            "block_count": self.block_count,
            "blocked_seconds": round(self.blocked_seconds + held, 1),
        }


class RiskGate:
    """判定を作って、指令ファイルに反映する。MT5 への出入りは mt(コントローラ)経由。"""

    def __init__(self, mt: Any, cfg: RiskConfig, bridge_id: str, state_dir: Path) -> None:
        self.mt = mt
        self.cfg = cfg
        self.bridge_id = bridge_id
        self.buy = DirectionState()
        self.sell = DirectionState()
        self.seq = 0
        self.applied_seq = 0
        self.mode: float = MODE_OFF
        self.mode_reason = "未開始"
        self.mode_override: str | None = None
        self.comms = "off"  # off / ok / error
        self.comms_error = ""
        self.last_decision: dict[str, Any] | None = None
        self.decided_at: str | None = None
        self.expires_at: str | None = None
        self.summary = ""
        self.history: list[dict[str, Any]] = []
        self.account_mode = "unknown"
        self.symbol = cfg.symbol or ""
        self.last_bar_time = 0
        self.last_eval = 0.0
        self.last_near_eval = 0.0
        self.evaluations = 0
        self.insufficient = 0
        self.errors = 0
        self._busy = False
        self._last_trace: tuple[str, float] = ("", 0.0)
        self._log_path = state_dir / "risk_decisions.jsonl"
        self._override_path = state_dir / "risk_gate.json"
        self._load_override()

    # ── 保存された切り替え（off / shadow / on） ──
    def _load_override(self) -> None:
        try:
            data = json.loads(self._override_path.read_text(encoding="utf-8"))
            mode = str(data.get("mode", "")).lower()
            if mode in MODE_VALUES:
                self.mode_override = mode
        except (OSError, ValueError):
            self.mode_override = None

    def set_mode(self, mode: str) -> bool:
        mode = str(mode).lower()
        if mode not in MODE_VALUES and mode != "auto":
            return False
        self.mode_override = None if mode == "auto" else mode
        try:
            self._override_path.write_text(
                json.dumps({"mode": self.mode_override or "auto", "at": datetime.now().isoformat(timespec="seconds")}),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("AIゲートの設定を保存できませんでした: %s", exc)
        return True

    # ── 口座の種別から、初期の動き方を決める ──
    def _decide_mode(self) -> None:
        if not self.cfg.enabled:
            self.mode, self.mode_reason = MODE_OFF, "設定で無効（RISK_GATE_ENABLED=0）"
            return
        if not self.cfg.token or not self.cfg.endpoint:
            self.mode, self.mode_reason = MODE_OFF, "合言葉（TRELAB_RISK_TOKEN）が未設定"
            return
        if self.mode_override:
            self.mode = MODE_VALUES[self.mode_override]
            self.mode_reason = f"画面から{self.mode_override}に設定"
            return
        if self.account_mode == "demo":
            self.mode = MODE_VALUES.get(self.cfg.demo_mode, MODE_ON)
            self.mode_reason = "デモ口座なので実際に反映"
        elif self.account_mode == "real":
            self.mode = MODE_VALUES.get(self.cfg.live_mode, MODE_SHADOW)
            self.mode_reason = "本番口座なので記録のみ（画面から変更できます）"
        else:
            self.mode = MODE_SHADOW
            self.mode_reason = "口座種別が確認できないので記録のみ"

    # ── 指令ファイルへ ──
    async def _write_gate(self, until_server: int | None) -> bool:
        values = {
            GV_MODE: self.mode,
            GV_BUY: 0.0 if self.buy.blocked else 1.0,
            GV_SELL: 0.0 if self.sell.blocked else 1.0,
            GV_SEQ: float(self.applied_seq),
        }
        if until_server is not None:
            values[GV_UNTIL] = float(until_server)
        ok = await self.mt.set_variables(values)
        if not ok:
            log.warning("AIゲート: 指令ファイルに書けませんでした（MT5 未接続の可能性）")
        return bool(ok)

    # ── 判定を当てる ──
    def _apply(self, decision: dict[str, Any], features: dict[str, Any]) -> None:
        now = time.time()
        for side, state in (("buy", self.buy), ("sell", self.sell)):
            verdict = str(decision.get(side, "ALLOW")).upper()
            codes = list(decision.get("reason_codes", {}).get(side, []))
            if verdict == "BLOCK":
                if not state.blocked:
                    state.blocked = True
                    state.since = now
                    state.block_count += 1
                    log.warning("AIゲート: %s を停止 %s", "買い" if side == "buy" else "売り", ",".join(codes))
                state.reasons = codes
                state.allow_streak = 0
                name = features.get("nearest_resistance_name" if side == "buy" else "nearest_support_name")
                state.level_name = name
                state.level_value = features.get("nearest_resistance" if side == "buy" else "nearest_support")
            elif verdict == "ALLOW":
                if state.blocked:
                    state.allow_streak += 1
                    held = now - state.since
                    # 時間切れでは再開しない。最新データで連続して問題なしになったときだけ
                    if state.allow_streak >= self.cfg.unblock_confirm and held >= self.cfg.min_block_sec:
                        state.blocked = False
                        state.blocked_seconds += held
                        state.reasons = []
                        state.level_name = None
                        state.level_value = None
                        state.allow_streak = 0
                        log.info("AIゲート: %s を再開", "買い" if side == "buy" else "売り")
                else:
                    state.allow_streak = 0
            else:  # INSUFFICIENT_DATA — 迷いを新しい停止の理由にしない
                self.insufficient += 1
                state.allow_streak = 0

    def _record(self, decision: dict[str, Any], features: dict[str, Any]) -> None:
        item = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "seq": decision.get("seq"),
            "mode": MODE_NAMES.get(self.mode, "?"),
            # 実際に発注を止めたのか、記録だけなのかを必ず区別する
            "enforced": self.mode >= MODE_ON,
            "buy": decision.get("buy"),
            "sell": decision.get("sell"),
            "reason_codes": decision.get("reason_codes"),
            "summary": decision.get("summary"),
            "evidence": decision.get("evidence"),
            "dropped": decision.get("dropped"),
            "model": decision.get("model"),
            "prompt_version": decision.get("prompt_version"),
            "expires_at": decision.get("expires_at"),
            "bar_time": decision.get("bar_time"),
            "features": features,
            "applied": {"buy_blocked": self.buy.blocked, "sell_blocked": self.sell.blocked},
        }
        self.history.insert(0, item)
        del self.history[self.cfg.history_keep :]
        try:
            if self._log_path.exists() and self._log_path.stat().st_size > 4_000_000:
                self._log_path.replace(self._log_path.with_suffix(".1.jsonl"))
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            log.debug("判定の記録を書けませんでした: %s", exc)

    # ── 通信（別スレッドで実行して、待っている間もブリッジは動く） ──
    def _post_blocking(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(
            self.cfg.endpoint,
            data=body,
            method="POST",
            headers={"content-type": "application/json", "x-trelab-bridge": self.cfg.token},
        )
        with urllib.request.urlopen(req, timeout=self.cfg.http_timeout) as res:
            return json.loads(res.read().decode("utf-8"))

    async def _ask(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, self._post_blocking, payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            self.comms, self.comms_error = "error", f"HTTP {exc.code} {detail}"
            self.errors += 1
            log.warning("AIリスク判定に失敗: %s", self.comms_error)
            return None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.comms, self.comms_error = "error", str(exc)[:200]
            self.errors += 1
            log.warning("AIリスク判定に届きません: %s", self.comms_error)
            return None
        decision = data.get("decision") if isinstance(data, dict) else None
        if not isinstance(decision, dict):
            self.comms, self.comms_error = "error", "応答の形が違う"
            self.errors += 1
            return None
        self.comms, self.comms_error = "ok", ""
        return decision

    # ── 1回ぶんの評価 ──
    async def evaluate(self, *, reason: str) -> None:
        if self._busy:  # 呼び出しが重ならないようにする
            return
        self._busy = True
        try:
            seq = self.seq = self.seq + 1
            snapshot = await self.mt.risk_snapshot(
                symbol=self.symbol,
                bars_m1=self.cfg.bars_m1,
                bars_h1=self.cfg.bars_h1,
                bars_h4=self.cfg.bars_h4,
            )
            if not snapshot:
                self.comms, self.comms_error = "error", "MT5 から足を取れません"
                return
            self.symbol = snapshot["symbol"]
            features = rf.build_features(
                bid=snapshot["bid"],
                ask=snapshot["ask"],
                m1=snapshot["m1"],
                h1=snapshot["h1"],
                h4=snapshot["h4"],
                d1=snapshot["d1"],
                w1=snapshot["w1"],
                profile=snapshot["profile"],
            )
            if not rf.data_is_usable(features):
                # データが足りないのに AI に聞かない（憶測で埋めさせない）
                self.comms_error = "足が足りません"
                return
            payload = {
                "bridge_id": self.bridge_id,
                "seq": seq,
                "account": snapshot["account"],
                "account_mode": self.account_mode,
                "symbol": self.symbol,
                "server_time": snapshot["server_time"],
                "bar_time": snapshot["bar_time"],
                "strategy_profile": snapshot["profile"],
                "features": features,
            }
            decision = await self._ask(payload)
            if not decision:
                return
            if int(decision.get("seq", 0)) < self.applied_seq:
                log.info("古い応答（seq=%s）は使いません", decision.get("seq"))
                return
            self.applied_seq = int(decision.get("seq", seq))
            self.evaluations += 1
            self._apply(decision, features)
            self.last_decision = decision
            self.decided_at = decision.get("issued_at")
            self.expires_at = decision.get("expires_at")
            self.summary = str(decision.get("summary", ""))
            self._record(decision, features)
            ttl = int(decision.get("ttl_sec", 180) or 180)
            await self._write_gate(int(snapshot["server_epoch"]) + ttl)
            log.info(
                "AIゲート判定 seq=%s 買い=%s 売り=%s (%s)",
                self.applied_seq,
                decision.get("buy"),
                decision.get("sell"),
                reason,
            )
        finally:
            self._busy = False

    # ── 常駐ループ ──
    async def run(self, stop: asyncio.Event, should_watch: Callable[[], bool]) -> None:
        log.info(
            "AIリスク監督を開始します（合言葉=%s 宛先=%s 間隔=%.0f秒）",
            "あり" if self.cfg.token else "なし（切のまま）",
            self.cfg.endpoint,
            self.cfg.eval_sec,
        )
        while not stop.is_set():
            try:
                await self._tick(should_watch)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 監督が落ちても本体は止めない
                log.warning("AIリスク監督でエラー: %s", exc)
            try:
                await asyncio.wait_for(stop.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    def _trace(self, why: str) -> None:
        """なぜ評価したか／しなかったかを、たまに1行だけ残す（追跡用）。"""
        now = time.time()
        if why == self._last_trace[0] and (now - self._last_trace[1]) < 60.0:
            return
        self._last_trace = (why, now)
        log.info(
            "AIゲート: %s（モード=%s 口座=%s 銘柄=%s 通信=%s）",
            why,
            MODE_NAMES.get(self.mode, "?"),
            self.account_mode,
            self.symbol or "未定",
            self.comms,
        )

    async def _tick(self, should_watch: Callable[[], bool]) -> None:
        info = await self.mt.account_mode()
        if info:
            self.account_mode = info
        self._decide_mode()
        if self.mode <= MODE_OFF:
            # 切っているときは、EA が期限切れで止まらないよう指令も 0（=判定なし）にしておく
            wrote = await self._write_gate(0)
            self._trace(f"切のまま（{self.mode_reason}）指令の書き込み={'成功' if wrote else '失敗'}")
            return
        if not should_watch():
            self._trace("サイトから停止中なので評価しない")
            return  # サイトから停止中は新規注文が無いので、費用をかけない
        now = time.time()
        bar_time = await self.mt.last_closed_m1(self.symbol)
        new_bar = bool(bar_time and bar_time != self.last_bar_time)
        due = (now - self.last_eval) >= self.cfg.eval_sec
        # 有効な判定が無い（起動直後・期限切れ）ときは、足を待たずに取りにいく。
        # 待っているあいだ、実反映モードでは新規注文が止まったままになるため。
        stale = self._expired() and (now - self.last_eval) >= 10.0
        near = False
        if not (new_bar and due) and not stale and (now - self.last_near_eval) >= self.cfg.near_recheck_sec:
            near = await self._near_level()
        if not ((new_bar and due) or near or stale):
            self._trace(f"待機中（新しい足={new_bar} 間隔待ち={not due} 期限切れ={stale}）")
        if (new_bar and due) or near or stale:
            self.last_eval = now
            self.last_near_eval = now
            if bar_time:
                self.last_bar_time = bar_time
            reason = "新しい足" if new_bar else ("判定が無い／期限切れ" if stale else "重要水準に接近")
            await self.evaluate(reason=reason)

    def _expired(self) -> bool:
        """いま手元にある判定が切れているか（まだ一度も無い場合も切れている扱い）。"""
        if not self.expires_at:
            return True
        try:
            end = datetime.fromisoformat(str(self.expires_at).replace("Z", "+00:00"))
        except ValueError:
            return True
        return end.timestamp() <= time.time()

    async def _near_level(self) -> bool:
        """前回の判定で見ていた水準に近づいたか（近ければ足の途中でも見直す）。"""
        last = self.last_decision
        if not last:
            return False
        levels = [s.level_value for s in (self.buy, self.sell) if s.level_value]
        if not levels:
            return False
        tick = await self.mt.symbol_tick(self.symbol)
        atr = None
        for item in self.history[:1]:
            atr = item.get("features", {}).get("atr_m1")
        if not tick or not atr:
            return False
        price = (tick["bid"] + tick["ask"]) / 2.0
        return any(abs(price - lv) <= atr * self.cfg.near_level_atr for lv in levels)

    # ── 画面へ ──
    def status(self, ea_counters: dict[str, Any] | None = None) -> dict[str, Any]:
        now = time.time()
        return {
            "mode": MODE_NAMES.get(self.mode, "off"),
            "mode_reason": self.mode_reason,
            "account_mode": self.account_mode,
            "symbol": self.symbol,
            "buy": self.buy.as_dict(now),
            "sell": self.sell.as_dict(now),
            "summary": self.summary,
            "decided_at": self.decided_at,
            "expires_at": self.expires_at,
            "seq": self.applied_seq,
            "comms": self.comms,
            "comms_error": self.comms_error,
            "model": (self.last_decision or {}).get("model"),
            "prompt_version": (self.last_decision or {}).get("prompt_version"),
            "metrics": {
                "evaluations": self.evaluations,
                "insufficient": self.insufficient,
                "errors": self.errors,
                "skipped": ea_counters or {},
            },
            "history": [
                {
                    "at": h["at"],
                    "buy": h["buy"],
                    "sell": h["sell"],
                    "reason_codes": h["reason_codes"],
                    "summary": h["summary"],
                    "enforced": h["enforced"],
                }
                for h in self.history[:10]
            ],
        }
