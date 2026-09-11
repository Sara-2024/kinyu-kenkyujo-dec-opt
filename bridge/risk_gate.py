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

# 通信が失敗したときに、次に試すまで待つ最大の秒数。
# サイト側の判定の有効期限（api/_lib/risk.ts の TTL_SEC = 180）より必ず短くすること。
# 長いと、待っているあいだに判定が切れて新規注文が全部止まる。
MAX_BACKOFF_SEC = 90.0


def _iso_after(seconds: float) -> str:
    """いまから seconds 秒後の時刻（画面に出す期限の表示用）。"""
    return datetime.fromtimestamp(time.time() + seconds).isoformat(timespec="seconds")


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
    # 判定を取り直す間隔。確定 M1 足ごと（60秒）にすると費用が倍になるため、
    # 既定は 120 秒。重要水準への接近や急な伸びは、この間隔を待たずに見る。
    eval_sec: float = field(default_factory=lambda: _env_float("RISK_EVAL_SEC", 120.0))
    # 判定を何秒もたせるか。0 ならサイト任せ（既定 180 秒）。
    # 期限が切れるとすぐ聞き直すので、ここが実質の問い合わせ間隔になる。
    # 長くすると API の消費は減るが、相場を見ていない時間も延びる。
    ttl_sec: float = field(default_factory=lambda: _env_float("RISK_TTL_SEC", 0.0))
    # 重要水準まで ATR 1個ぶんより近ければ、足の途中でも見直す
    near_level_atr: float = field(default_factory=lambda: _env_float("RISK_NEAR_LEVEL_ATR", 1.0))
    # AI に聞く条件。ゴールドの1分足（9/3〜9/9 の実データ）で、聞く回数が
    # 全体の 27% に収まる値を選んだ。緩めると費用が増え、締めると危ない場面を
    # 取りこぼす。RISK_ASK_* で調整できる。
    ask_within_atr: float = field(default_factory=lambda: _env_float("RISK_ASK_WITHIN_ATR", 1.0))
    ask_move_atr: float = field(default_factory=lambda: _env_float("RISK_ASK_MOVE_ATR", 4.0))
    # 聞かずに見送ったときに、判定の期限をどれだけ延ばすか（秒）
    quiet_extend_sec: float = field(default_factory=lambda: _env_float("RISK_QUIET_EXTEND_SEC", 180.0))
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
        self.comms = "off"  # off / ok / error（外部AIとの通信だけ）
        self.comms_error = ""
        # MT5 から足が取れない等、手元の材料の問題。通信の障害とは別に持つ
        self.data_error = ""
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
        self.skipped_calls = 0
        self.last_skip_reason = ""
        self.errors = 0
        # サイトが会社から受け取ったトークン数の申告（費用の実測用。無ければ None）
        self._last_usage: dict[str, Any] | None = None
        self._busy = False
        self._last_trace: tuple[str, float] = ("", 0.0)
        # 最後に指令ファイルへ書いた内容。変わったときだけ書き直す
        self._written: tuple[float, bool, bool, int] | None = None
        self._until_epoch = 0
        # AI 側が混んでいる／上限に達したときの、次に試すまでの待ち時間
        self._error_wait = 0.0
        self._error_at = 0.0
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
    async def _sync_gate(self) -> None:
        """モードや停止状態が変わったら、判定を待たずに EA へ伝える。

        画面で「反映 → 記録のみ」に切り替えたのに、次の判定が返るまで
        EA が古い値を読み続けるのを防ぐ。
        """
        now_state = (self.mode, self.buy.blocked, self.sell.blocked, self._until_epoch)
        if now_state == self._written:
            return
        if await self._write_gate(self._until_epoch or None):
            self._written = now_state
            log.info(
                "AIゲートを指令ファイルに反映: モード=%s 買い=%s 売り=%s",
                MODE_NAMES.get(self.mode, "?"),
                "停止" if self.buy.blocked else "許可",
                "停止" if self.sell.blocked else "許可",
            )

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
                if side == "buy":  # 1回の判定で2回数えない
                    self.insufficient += 1
                # 迷いは再開の妨げにもしない。ここで streak を 0 に戻していたので、
                # ALLOW と INSUFFICIENT_DATA が交互に返るだけで永久に再開できなかった
                # （再開には ALLOW が連続 unblock_confirm 回必要なため）。据え置きにする。

    def _record(self, decision: dict[str, Any], payload: dict[str, Any]) -> None:
        """判定を履歴と jsonl に残す。

        jsonl には **同じ問い合わせをもう一度作れるだけの材料**（銘柄・戦略プロフィール・
        サーバー時刻・features）を必ず入れる。あとから別のモデルに同じ場面を見せて
        judgment を突き合わせる（`tools/compare-risk-models.mjs`）ために要る。
        画面へ渡すのは `status()` が選んだ項目だけなので、ここが増えても通信量は変わらない。
        """
        features = payload.get("features") or {}
        item = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "seq": decision.get("seq"),
            # ── 問い合わせを作り直すための材料 ──
            "symbol": payload.get("symbol"),
            "account_mode": payload.get("account_mode"),
            "server_time": payload.get("server_time"),
            "strategy_profile": payload.get("strategy_profile"),
            # ── 実費を数えるための材料（サイトが会社から受け取った申告値） ──
            "usage": self._last_usage,
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
            # 429（上限）や 503（混雑）で叩き続けない。間隔を広げて待つ
            self._back_off("上限・混雑" if exc.code in (429, 503) else f"HTTP {exc.code}")
            log.warning("AIリスク判定に失敗: %s", self.comms_error)
            return None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.comms, self.comms_error = "error", str(exc)[:200]
            self.errors += 1
            self._back_off("届かない")
            log.warning("AIリスク判定に届きません: %s", self.comms_error)
            return None
        usage = data.get("usage") if isinstance(data, dict) else None
        self._last_usage = usage if isinstance(usage, dict) else None
        decision = data.get("decision") if isinstance(data, dict) else None
        if not isinstance(decision, dict):
            self.comms, self.comms_error = "error", "応答の形が違う"
            self.errors += 1
            log.warning("AIゲート: サイトの応答に判定が入っていません")
            return None
        self.comms, self.comms_error = "ok", ""
        self._error_wait = 0.0
        return decision

    # ── 聞く価値があるかの判断（無駄に AI を回さない） ──
    def _entry_possible(self, features: dict[str, Any], profile: dict[str, Any]) -> tuple[bool, str]:
        """EA がこの先すぐ入りうる形か。そうでなければ AI に聞かない。

        EA は「内部高値／安値のブレイク後、リテスト成立」でしか入らない。
        静かな時間帯や、どの水準からも遠い場面で聞いても、その判定は使われない。
        """
        atr = features.get("atr_m1")
        if not atr:
            return False, "ATRが出ていない"

        # M1軸は ATR が下限を割ると一切入らない（EA の InpM1MinAtrUSD と同じ値）
        min_atr = float(profile.get("m1_min_atr_usd", 0.0) or 0.0)
        m1_alive = (not min_atr) or atr >= min_atr
        h1_alive = bool(profile.get("h1_enabled", True))
        if not m1_alive and not h1_alive:
            return False, f"ATR {atr:.2f} が下限 {min_atr:.2f} 未満"

        # 突破待ち・リテスト待ちが立っているか（ブレイクからの本数が浅い）
        retest_bars = int(profile.get("retest_bars", 6) or 6)
        for side in ("resistance", "support"):
            since = features.get(f"{side}_bars_since_break")
            if features.get(f"{side}_break_state") and since is not None and since <= retest_bars:
                return True, f"{'上' if side == 'resistance' else '下'}の水準を抜けた直後"

        # 重要な水準の近く（ここが AI に見てほしい場面そのもの）
        for side in ("resistance", "support"):
            near = features.get(f"dist_to_{side}_atr")
            if near is not None and near <= self.cfg.ask_within_atr:
                return True, f"{'上' if side == 'resistance' else '下'}の水準まで ATR {near:.1f} 個"

        # 急に伸びた直後（飛び乗りが起きやすい）
        move = features.get("move_m1_15bars_atr")
        if move is not None and abs(move) >= self.cfg.ask_move_atr:
            return True, f"直近15本で ATR {abs(move):.1f} 個ぶん動いた"

        return False, "水準から遠く、伸びも小さい"

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
                self.data_error = "MT5 から足を取れません（銘柄が特定できない可能性）"
                log.warning("AIゲート: %s", self.data_error)
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
                missing = [k for k in ("atr_m1", "atr_h1", "price_mid", "ema200_h1") if features.get(k) is None]
                self.data_error = f"足が足りません（{'・'.join(missing)}）"
                log.warning("AIゲート: %s", self.data_error)
                return
            # ここまでは MT5 の中だけの処理（無料）。AI に聞くのは必要なときだけ。
            possible, why = self._entry_possible(features, snapshot["profile"])
            # いま止めている最中は、入る見込みが無くても必ず聞く。
            # 聞かないと `allow_streak` が増えず、再開の条件（最新データで連続して
            # 問題なし）に永久に到達しない。危険が去っても止まったままになる。
            must_ask = self.buy.blocked or self.sell.blocked
            if not possible and not must_ask:
                self.skipped_calls += 1
                self.last_skip_reason = why
                # 入る見込みが無いあいだは、期限だけ延ばして EA を止めない
                self._until_epoch = int(snapshot["server_epoch"]) + int(self.cfg.quiet_extend_sec)
                # 期限を延ばしたことを画面側にも反映する。ここを更新しないと
                # 「判定が期限切れ」の扱いのまま 10 秒ごとに MT5 の足を取り直し続ける
                self.expires_at = _iso_after(self.cfg.quiet_extend_sec)
                if await self._write_gate(self._until_epoch):
                    self._written = (self.mode, self.buy.blocked, self.sell.blocked, self._until_epoch)
                self._trace(f"聞かずに見送り（{why}）")
                return
            if not possible and must_ask:
                self._trace(f"停止中なので聞く（{why}）")

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
            if self.cfg.ttl_sec > 0:
                payload["ttl_sec"] = self.cfg.ttl_sec
            self.data_error = ""
            decision = await self._ask(payload)
            if not decision:
                return
            # 古い応答・別の足の応答は使わない。
            # seq が無い応答を 0 とみなすと、起動直後（applied_seq=0）だけ通ってしまうので、
            # 「seq が入っていない」こと自体を捨てる理由にする。
            got_seq = decision.get("seq")
            if got_seq is None or int(got_seq) < self.applied_seq:
                log.info("古い応答（seq=%s）は使いません", got_seq)
                return
            got_bar = int(decision.get("bar_time", 0) or 0)
            if got_bar and got_bar != int(snapshot["bar_time"] or 0):
                log.info("別の足の応答（bar_time=%s）は使いません", got_bar)
                return
            self.applied_seq = int(decision.get("seq", seq))
            self.evaluations += 1
            self._apply(decision, features)
            self.last_decision = decision
            self.decided_at = decision.get("issued_at")
            self.expires_at = decision.get("expires_at")
            self.summary = str(decision.get("summary", ""))
            self._record(decision, payload)
            ttl = int(decision.get("ttl_sec", 180) or 180)
            self._until_epoch = int(snapshot["server_epoch"]) + ttl
            if await self._write_gate(self._until_epoch):
                self._written = (self.mode, self.buy.blocked, self.sell.blocked, self._until_epoch)
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
            self._until_epoch = 0
            wrote = await self._write_gate(0)
            if wrote:
                self._written = (self.mode, self.buy.blocked, self.sell.blocked, 0)
            self._trace(f"切のまま（{self.mode_reason}）指令の書き込み={'成功' if wrote else '失敗'}")
            return
        # 画面での切り替えを、判定を待たずに EA へ伝える
        await self._sync_gate()
        if not should_watch():
            self._trace("サイトから停止中なので評価しない")
            return  # サイトから停止中は新規注文が無いので、費用をかけない
        if self._waiting_after_error():
            self._trace(f"AI側の失敗のあとなので待機中（あと{self._error_wait:.0f}秒まで）")
            return
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
            self._trace(
                f"待機中（新しい足={new_bar} 間隔待ち={not due} 期限切れ={stale}"
                + (f" 材料={self.data_error}" if self.data_error else "")
                + "）"
            )
        if (new_bar and due) or near or stale:
            self.last_eval = now
            self.last_near_eval = now
            if bar_time:
                self.last_bar_time = bar_time
            reason = "新しい足" if new_bar else ("判定が無い／期限切れ" if stale else "重要水準に接近")
            await self.evaluate(reason=reason)

    def _back_off(self, why: str) -> None:
        """失敗が続くほど、次に試すまでの間隔を広げる（30秒→最大90秒）。

        上限はサイト側の判定の有効期限（TTL 180秒）より必ず短くする。
        以前は最大5分だったので、通信障害が続くと待っているあいだに判定が期限切れになり、
        反映モードでは買いも売りも全部止まる「窓」が必ずできていた。
        """
        self._error_wait = min(MAX_BACKOFF_SEC, self._error_wait * 2 if self._error_wait else 30.0)
        self._error_at = time.time()
        log.info("AIリスク判定は %.0f 秒あけて試します（%s）", self._error_wait, why)

    def _waiting_after_error(self) -> bool:
        return self._error_wait > 0 and (time.time() - self._error_at) < self._error_wait

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
            # 合言葉が無いと、押しても「切」から動かない。画面で押せなくするために返す
            "configured": bool(self.cfg.token and self.cfg.endpoint and self.cfg.enabled),
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
            "data_error": self.data_error,
            "retry_in_sec": round(max(0.0, self._error_wait - (time.time() - self._error_at)), 0) if self._waiting_after_error() else 0,
            "model": (self.last_decision or {}).get("model"),
            "prompt_version": (self.last_decision or {}).get("prompt_version"),
            "metrics": {
                "evaluations": self.evaluations,
                "insufficient": self.insufficient,
                "skipped_calls": self.skipped_calls,
                "last_skip_reason": self.last_skip_reason,
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
