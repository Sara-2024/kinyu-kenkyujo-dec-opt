// AIリスク監督（新規注文の許可・停止）を画面に出すための型と言葉。
//
// 判定そのものはブリッジが持っている。ここでは受け取った値を日本語にするだけで、
// 画面側で状態を作らない（数字も理由も、ブリッジが返したものだけを出す）。

export type AiAssessment = 'ALLOW' | 'BLOCK' | 'INSUFFICIENT_DATA'
export type AiGateMode = 'off' | 'shadow' | 'on'

export interface AiGateSide {
  blocked: boolean
  reasons: string[]
  level_name?: string | null
  level_value?: number | null
  held_sec?: number
  block_count?: number
  blocked_seconds?: number
}

export interface AiGateHistoryItem {
  at: string
  buy: AiAssessment
  sell: AiAssessment
  reason_codes?: { buy?: string[]; sell?: string[] }
  summary?: string
  /** true = 実際に新規注文を止めた／止められる状態。false = 記録だけ */
  enforced?: boolean
}

export interface AiGateState {
  mode: AiGateMode
  mode_reason?: string
  /** false のときは「切」から動かせない（接続ツールに合言葉が入っていない） */
  configured?: boolean
  account_mode?: string
  symbol?: string
  buy: AiGateSide
  sell: AiGateSide
  summary?: string
  decided_at?: string | null
  expires_at?: string | null
  seq?: number
  comms?: 'ok' | 'error' | 'off'
  comms_error?: string
  /** MT5 側の材料が足りないとき（通信の障害とは別物） */
  data_error?: string
  /** AI側が混雑・上限のとき、次に試すまでの秒数 */
  retry_in_sec?: number
  model?: string | null
  prompt_version?: string | null
  metrics?: {
    evaluations?: number
    insufficient?: number
    errors?: number
    skipped?: Record<string, number>
  }
  history?: AiGateHistoryItem[]
}

/** 停止の理由コード → 画面に出す短い日本語 */
export const REASON_LABEL: Record<string, string> = {
  NEAR_RESISTANCE: '上の重要高値が近い',
  NEAR_SUPPORT: '下の重要安値が近い',
  OVEREXTENDED_UP: '短時間で上げすぎ（飛び乗り）',
  OVEREXTENDED_DOWN: '短時間で下げすぎ（飛び乗り）',
  BREAKOUT_UNCONFIRMED: '突破がまだ固まっていない',
  STRATEGY_CONFLICT: 'システムの得意な形と食い違う',
}

/** 重要水準の名前 → 画面に出す短い日本語 */
export const LEVEL_LABEL: Record<string, string> = {
  prev_day_high: '前日の高値',
  prev_day_low: '前日の安値',
  prev_week_high: '前週の高値',
  prev_week_low: '前週の安値',
  swing_h1_high: '1時間足の直近高値',
  swing_h1_low: '1時間足の直近安値',
  swing_h4_high: '4時間足の直近高値',
  swing_h4_low: '4時間足の安値',
  window_high: '取得できた範囲の最高値',
  window_low: '取得できた範囲の最安値',
}

export const MODE_LABEL: Record<AiGateMode, string> = {
  off: '切',
  shadow: '記録のみ',
  on: '反映',
}

export const MODE_NOTE: Record<AiGateMode, string> = {
  off: 'AIは見ていません。既存の安全装置（1日の損失上限・スプレッド制限・手動停止）はそのまま働きます',
  shadow: 'AIの判定は記録するだけで、発注は止めません。効き方の確認に使います',
  on: 'AIが危ないと判断した向きの新規注文だけを止めます。保有中の決済とSL/TPはそのまま続きます',
}

export function reasonText(codes: string[] | undefined): string {
  if (!codes || codes.length === 0) return ''
  return codes.map((c) => REASON_LABEL[c] ?? c).join('・')
}

export function levelText(side: AiGateSide, digits = 2): string {
  if (!side.level_name) return ''
  const name = LEVEL_LABEL[side.level_name] ?? side.level_name
  return side.level_value != null ? `${name} ${side.level_value.toFixed(digits)}` : name
}

/** 有効期限までの残り。切れていたら null */
export function remainSec(expiresAt: string | null | undefined, now = Date.now()): number | null {
  if (!expiresAt) return null
  const t = new Date(expiresAt).getTime()
  if (!Number.isFinite(t)) return null
  const left = Math.round((t - now) / 1000)
  return left > 0 ? left : null
}

export function shortTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}
