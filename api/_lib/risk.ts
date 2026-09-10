// AIリスク監督：新規注文の許可・停止を、買い／売り別に評価する。
//
//   ブリッジ（お客様のPC）が MT5 から数字を作って送る → ここで Gemini に見せる →
//   返ってきた判定を検証して返す → ブリッジが指令ファイルに書く → EA が新規注文の直前に見る。
//
// ここでやらないこと:
//   * 相場を自分で調べない（数字はブリッジが送ってきたものだけ）
//   * 決済・ロット・SL/TP の指示は作らない（EA の既存ロジックは触らない）
//   * AI に有効期限や口座・銘柄を作らせない（この関数が付ける）
import { createHash } from 'node:crypto'

/** システムプロンプトを変えたら上げる。判定の記録に残る */
export const PROMPT_VERSION = '2026-09-10.1'

/** 既定のモデル。環境変数 GEMINI_RISK_MODEL で変更できる（黙って別のモデルに落とさない） */
const DEFAULT_MODEL = 'gemini-3.5-flash'
const GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta'

/**
 * DeepSeek は OpenAI 互換の口。RISK_PROVIDER=deepseek で切り替える。
 * 既定は `deepseek-flash`。以前ここに書いていた `deepseek-chat` は
 * DeepSeek の料金表・モデル一覧から消えているので、既定にはしない
 * （どうしても使うときは DEEPSEEK_RISK_MODEL で明示する）。
 */
const DEEPSEEK_BASE = 'https://api.deepseek.com/v1'
const DEEPSEEK_DEFAULT_MODEL = 'deepseek-flash'

/** 判定の有効期限（秒）。切れたらブリッジ側で新規注文を止める */
const TTL_SEC = 180
/** Gemini の応答待ちの上限。ここで諦めても EA は前の判定を期限まで使う */
const TIMEOUT_MS = 12_000
/** ブリッジ1台あたりの呼び出し上限（1分） */
const RATE_LIMIT = 40
const RATE_WINDOW_MS = 60_000

export type Assessment = 'ALLOW' | 'BLOCK' | 'INSUFFICIENT_DATA'

/** 停止の理由コード。AI にはこの中からだけ選ばせ、これ以外は捨てる */
export const REASON_CODES = [
  'NEAR_RESISTANCE',
  'NEAR_SUPPORT',
  'OVEREXTENDED_UP',
  'OVEREXTENDED_DOWN',
  'BREAKOUT_UNCONFIRMED',
  'STRATEGY_CONFLICT',
] as const
export type ReasonCode = (typeof REASON_CODES)[number]

export interface EvidenceItem {
  field: string
  value: number | string
  why: string
}

export interface RiskRequest {
  bridge_id: string
  seq: number
  account: number | string
  /** demo / real / contest。ブリッジが MT5 の口座種別から入れる */
  account_mode: string
  symbol: string
  /** ブローカーのサーバー時計（ISO, 秒） */
  server_time: string
  /** 判定のもとになった確定 M1 足の時刻（UNIX 秒・サーバー時計） */
  bar_time: number
  /** EA の実際の設定から作った戦略プロフィール */
  strategy_profile: Record<string, unknown>
  /** ブリッジが計算した数値。evidence はこの項目名しか使えない */
  features: Record<string, number | string | null>
}

export interface RiskDecision {
  seq: number
  issued_at: string
  expires_at: string
  ttl_sec: number
  account: number | string
  symbol: string
  bar_time: number
  model: string
  prompt_version: string
  buy: Assessment
  sell: Assessment
  reason_codes: { buy: ReasonCode[]; sell: ReasonCode[] }
  evidence: EvidenceItem[]
  summary: string
  /** 検証で落とした項目（透明性のために返す） */
  dropped: string[]
}

// ────────────────────────────────
// システムプロンプト（依頼された文面をそのまま実装する）
// ────────────────────────────────
const SYSTEM_PROMPT = `あなたは既存EAの新規エントリーを監督するリスク評価担当です。

原則は取引許可です。与えられた戦略プロフィールと市場データを使い、買い・売りを別々に評価してください。

あなたの目的は、重要高値直前での買い、重要安値直前での売り、急伸・急落後の飛び乗り、戦略条件と明確に衝突する相場での新規注文を見送ることです。

重要水準に近いという理由だけでは停止せず、方向、残された値幅、伸びすぎ、突破・リテスト状態を合わせて判断してください。

通常のブレイクや成立済みリテストを過剰に停止しないでください。不確実性だけでは停止しません。判断材料が不足している場合はINSUFFICIENT_DATAを返し、不足データを推測で補わないでください。

停止を提案する場合、入力に存在する具体的な数値と理由コードを必ず示してください。将来の反転や損失を断定しないでください。

保有ポジションの決済、ロット変更、SL・TP変更、新規の売買指示は行いません。

指定された構造のJSONのみを返してください。

【評価の約束】
- 買いの停止に使える理由コード: NEAR_RESISTANCE, OVEREXTENDED_UP, BREAKOUT_UNCONFIRMED, STRATEGY_CONFLICT
- 売りの停止に使える理由コード: NEAR_SUPPORT, OVEREXTENDED_DOWN, BREAKOUT_UNCONFIRMED, STRATEGY_CONFLICT
- 高値が近いことを理由に売りを止めない。安値が近いことを理由に買いを止めない。
- 過去成績のデータは渡していない。「実績上苦手」と書かない。テスト用の仮説として書く。
- summary は日本語で1〜2文。お客様に見せる短い説明。

【evidence の書き方】守られていない停止は、こちらで取り消します。
- field は features に実在する項目名だけ。value は features の値をそのまま写す（丸めない・注記を付けない）。
- 値が null の項目は根拠にしない。
- 止める方向に対応する項目を必ず1つ以上入れる。
  買いの停止 → nearest_resistance / dist_to_resistance* / resistance_* / window_high / prev_*_high / move_* / ema_dev_* のいずれか
  売りの停止 → nearest_support / dist_to_support* / support_* / window_low / prev_*_low / move_* / ema_dev_* のいずれか
- 2〜4件にとどめる。

【数値の読み方】単位はすべて銘柄の値段と同じ（金なら USD）。ATR は Wilder、期間は戦略プロフィールの atr_period 本。
- price_mid / price_bid / price_ask: 仲値・売値・買値。spread_usd / spread_atr_m1: スプレッド（幅と、atr_m1 の何個ぶんか）。
- atr_m1 / atr_h1: M1 / H1 の ATR。
- ema200_m1 / ema200_h1: 戦略プロフィールの ema_period 本の EMA の値（名前は 200 だが、期間は ema_period に従う）。
- ema_dev_m1_atr / ema_dev_h1_atr: (価格 − その足の EMA) ÷ その足の ATR。＋は価格が EMA の上。
  ema200_h1_slope_atr: H1 の EMA が直近20本で動いた幅 ÷ atr_h1。
- move_m1_15bars / move_h1_6bars: 直近15本(M1) / 直近6本(H1) の値動き。
  move_m1_15bars_atr は atr_m1 の、move_h1_6bars_atr は atr_h1 の、それぞれ何個ぶんか。
- pullback_from_high_ratio / pullback_from_low_ratio: 直近30本(M1)の高安レンジの中で、高値／安値からどれだけ引き戻したか（0〜1）。
  高値に張り付いていれば pullback_from_high_ratio は 0。2つの合計は必ず 1。
- nearest_resistance / nearest_support: いまの値段の**上**と**下**で、いちばん近い水準。
  nearest_resistance_name / nearest_support_name はその出どころ
  （prev_day_high, prev_week_low, swing_h1_high, swing_h4_low, window_high, window_low など）。
  上抜け済みの高値は「下側の水準」に移るので、nearest_support_name に *_high が出ることがある（誤りではない）。
- dist_to_resistance / dist_to_support: そこまでの値幅。
  dist_to_resistance_atr / dist_to_support_atr は atr_m1 の何個ぶんか。
  dist_to_resistance_sl_m1 / dist_to_support_sl_m1（H1軸は dist_to_resistance_sl_h1 / dist_to_support_sl_h1）は、
  予定している損切りの**幅**
  （planned_sl_m1 / planned_sl_h1。価格ではなく幅）の何倍か。1 を下回るなら、損切り幅ぶんの値幅も残っていない。
- resistance_break_state / support_break_state: 直近 window_bars 本の中で、その水準の外側で確定した終値があれば 1。
  resistance_bars_since_break / support_bars_since_break は最後に外へ出てからの本数。
  resistance_retest_seen / support_retest_seen は一度戻ったか、
  resistance_retest_confirmed / support_retest_confirmed は戻ってから再び外へ出たか（＝成立した突破）。
- htf_alignment: H1 と H4 の向きが揃えば +1（上）/ -1（下）、食い違えば 0。
- adx_h1: H1 の ADX（0〜100）。alternation_h1_20: 直近20本(H1)で上下が入れ替わった回数（0〜19。多いほどレンジ）。
  この2つだけを理由に止めない（補助として使う）。
- window_high / window_low: 取得できた履歴（window_tf の足を window_bars 本、window_start から）の中の最高値・最安値。
  史上最高値ではない。そう呼ばない。
- last_closed_m1_time: 判定のもとにした確定 M1 足の時刻（ブローカーのサーバー時計）。
- prev_day_high/low, prev_week_high/low: 前日・前週の高値と安値。
- null は「計算できなかった」という意味。推測で埋めない。`

const RESPONSE_SCHEMA = {
  type: 'OBJECT',
  properties: {
    buy_assessment: { type: 'STRING', enum: ['ALLOW', 'BLOCK', 'INSUFFICIENT_DATA'] },
    sell_assessment: { type: 'STRING', enum: ['ALLOW', 'BLOCK', 'INSUFFICIENT_DATA'] },
    buy_reason_codes: { type: 'ARRAY', items: { type: 'STRING', enum: [...REASON_CODES] } },
    sell_reason_codes: { type: 'ARRAY', items: { type: 'STRING', enum: [...REASON_CODES] } },
    evidence: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          field: { type: 'STRING' },
          value: { type: 'STRING' },
          why: { type: 'STRING' },
        },
        required: ['field', 'value', 'why'],
      },
    },
    summary: { type: 'STRING' },
  },
  required: ['buy_assessment', 'sell_assessment', 'buy_reason_codes', 'sell_reason_codes', 'evidence', 'summary'],
} as const

// thinking 系の指定はモデルによって受け付けないので、400 のときだけ落としていく
const CONFIG_VARIANTS = [
  {
    name: 'schema+budget0',
    config: { responseMimeType: 'application/json', responseSchema: RESPONSE_SCHEMA, thinkingConfig: { thinkingBudget: 0 } },
  },
  {
    name: 'schema+minimal',
    config: { responseMimeType: 'application/json', responseSchema: RESPONSE_SCHEMA, thinkingConfig: { thinkingLevel: 'minimal' } },
  },
  { name: 'schema', config: { responseMimeType: 'application/json', responseSchema: RESPONSE_SCHEMA } },
  { name: 'json', config: { responseMimeType: 'application/json' } },
] as const
let workingVariant = 0
/** 落ちた書き方を覚えておく期限。過ぎたら先頭（いちばん安い書き方）から試し直す */
let variantUntil = 0
const VARIANT_KEEP_MS = 10 * 60_000

/**
 * いま試しはじめる書き方。
 * 一度 400 が出ると弱い書き方に落ちるが、そのまま戻らないと
 * `thinkingBudget: 0`（思考トークンを使わない指定）や responseSchema が
 * 恒久的に外れて、費用も判定の安定も落ちる。時間が経ったら先頭に戻す。
 */
function currentVariant(): number {
  if (workingVariant !== 0 && Date.now() > variantUntil) workingVariant = 0
  return workingVariant
}

/**
 * responseSchema を受け付けない相手（DeepSeek など）に、同じ形を言葉で伝えるための説明。
 * RESPONSE_SCHEMA と食い違わせないこと。返ってきた中身は結局この後の検証で確かめる。
 */
const JSON_SHAPE_NOTE = `
【返す JSON の形】次のキーだけを持つ JSON オブジェクトを返してください。前置きも解説も付けません。
{
  "buy_assessment":  "ALLOW" | "BLOCK" | "INSUFFICIENT_DATA",
  "sell_assessment": "ALLOW" | "BLOCK" | "INSUFFICIENT_DATA",
  "buy_reason_codes":  [${REASON_CODES.map((c) => `"${c}"`).join(', ')}] のうち該当するものだけ,
  "sell_reason_codes": 同上,
  "evidence": [{ "field": "入力の features に実在する項目名", "value": "入力の値をそのまま文字列で", "why": "理由" }],
  "summary": "日本語1〜2文"
}`

// ────────────────────────────────
// 検証
// ────────────────────────────────
const BUY_CODES: ReasonCode[] = ['NEAR_RESISTANCE', 'OVEREXTENDED_UP', 'BREAKOUT_UNCONFIRMED', 'STRATEGY_CONFLICT']
const SELL_CODES: ReasonCode[] = ['NEAR_SUPPORT', 'OVEREXTENDED_DOWN', 'BREAKOUT_UNCONFIRMED', 'STRATEGY_CONFLICT']

/**
 * 数値として読めるものだけを数値にする。
 *
 * 以前は文字列から数字以外を取り除いていたが、それだと項目名まで数値に化けて
 * 別物どうしが同じ値になっていた（`swing_h1_high` も `swing_h1_low` も 1、
 * `window_high` も `window_low` も 0、`H1` も `M1` も 1）。
 * 結果、AI は「支持の名前は window_low です」という入力に対して
 * 「window_high でした」と言い張れた。名前は名前として比べる。
 */
function num(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string') return null
  const t = value.trim()
  if (!/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(t)) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

/**
 * その方向の停止に使える項目かどうか。
 * 「買いを止める」なら上側（抵抗）と、方向を問わない伸び・かい離の項目だけを根拠にできる。
 * 下側（支持）の数字しか出せていない買い停止は、根拠が方向と噛み合っていない。
 */
const BUY_EVIDENCE_RE =
  /^(nearest_resistance|dist_to_resistance|resistance_|window_high|prev_(day|week)_high|move_|ema_dev_|ema200_|ema_h1_slope|pullback_from_high|htf_align|atr_|adx_|alternation_|price_)/
const SELL_EVIDENCE_RE =
  /^(nearest_support|dist_to_support|support_|window_low|prev_(day|week)_low|move_|ema_dev_|ema200_|ema_h1_slope|pullback_from_low|htf_align|atr_|adx_|alternation_|price_)/

/** 入力に無い項目名や、入力と違う値を根拠にした evidence は捨てる */
export function checkEvidence(
  items: EvidenceItem[],
  features: Record<string, number | string | null>,
): { kept: EvidenceItem[]; dropped: string[] } {
  const kept: EvidenceItem[] = []
  const dropped: string[] = []
  for (const item of items.slice(0, 12)) {
    const field = String(item?.field ?? '').trim()
    if (!field || !(field in features)) {
      dropped.push(`${field || '(空)'}: 入力に無い項目`)
      continue
    }
    const actual = features[field]
    // 計算できなかった項目（null）は根拠にできない。
    // ここを通していたので、AI は空の項目に好きな数字を書けば必ず停止を通せた。
    if (actual === null || actual === undefined || actual === '') {
      dropped.push(`${field}: 入力の値が空（根拠に使えない）`)
      continue
    }
    const wanted = num(item?.value)
    const actualNum = num(actual)
    if (actualNum != null) {
      if (wanted == null) {
        dropped.push(`${field}: 数値の項目に数値以外を書いている（入力 ${actual} / 主張 ${item.value}）`)
        continue
      }
      // 許すのは表示のまるめ差だけ。features は小数3桁に丸めて送っているので、
      // これ以上ゆるめる理由が無い（以前の相対0.5%は、金 3,520 ドルなら $17 ＝ ATR 15個ぶん）。
      const tol = Math.max(Math.abs(actualNum) * 1e-5, 5e-4)
      if (Math.abs(actualNum - wanted) > tol) {
        dropped.push(`${field}: 値が入力と違う（入力 ${actual} / 主張 ${item.value}）`)
        continue
      }
    } else {
      // 文字列の項目。注記付き（"window_low（直近の安値）"）は許すが、別の名前は許さない
      const said = String(item?.value ?? '').trim()
      const real = String(actual).trim()
      if (said !== real && !said.startsWith(real)) {
        dropped.push(`${field}: 値が入力と違う（入力 ${actual} / 主張 ${item.value}）`)
        continue
      }
    }
    kept.push({ field, value: actual as number | string, why: String(item?.why ?? '').slice(0, 200) })
  }
  return { kept, dropped }
}

/** 停止は「その方向で使える理由コード」と「その方向の根拠」がそろって初めて成立する */
export function applyGuards(
  raw: { buy: Assessment; sell: Assessment; buyCodes: ReasonCode[]; sellCodes: ReasonCode[] },
  evidence: EvidenceItem[],
): { buy: Assessment; sell: Assessment; buyCodes: ReasonCode[]; sellCodes: ReasonCode[]; dropped: string[] } {
  const dropped: string[] = []
  const buyCodes = raw.buyCodes.filter((c) => BUY_CODES.includes(c))
  const sellCodes = raw.sellCodes.filter((c) => SELL_CODES.includes(c))
  for (const c of raw.buyCodes) if (!BUY_CODES.includes(c)) dropped.push(`買いの理由コード ${c} は買いに使えない`)
  for (const c of raw.sellCodes) if (!SELL_CODES.includes(c)) dropped.push(`売りの理由コード ${c} は売りに使えない`)

  // 「その方向の根拠」を実際に数える。件数だけ見ていたので、買いを止めるのに
  // 下側の数字しか出していない（＝方向と噛み合わない）停止が通っていた。
  const buyEvidence = evidence.filter((e) => BUY_EVIDENCE_RE.test(String(e?.field ?? '')))
  const sellEvidence = evidence.filter((e) => SELL_EVIDENCE_RE.test(String(e?.field ?? '')))

  let buy = raw.buy
  let sell = raw.sell
  if (buy === 'BLOCK' && (buyCodes.length === 0 || buyEvidence.length === 0)) {
    dropped.push('買い停止：買いの根拠か理由コードが無いので採用しない')
    buy = 'ALLOW'
  }
  if (sell === 'BLOCK' && (sellCodes.length === 0 || sellEvidence.length === 0)) {
    dropped.push('売り停止：売りの根拠か理由コードが無いので採用しない')
    sell = 'ALLOW'
  }
  return { buy, sell, buyCodes: buy === 'BLOCK' ? buyCodes : [], sellCodes: sell === 'BLOCK' ? sellCodes : [], dropped }
}

// ────────────────────────────────
// Gemini 呼び出し
// ────────────────────────────────
export type RiskProvider = 'gemini' | 'deepseek'

export interface RiskEnv {
  provider: RiskProvider
  geminiKey?: string
  geminiBase?: string
  model?: string
  deepseekKey?: string
  deepseekBase?: string
  deepseekModel?: string
  timeoutMs?: number
  bridgeToken?: string
}

export function riskEnvFrom(source: Record<string, string | undefined>): RiskEnv {
  const deepseekKey = (source.DEEPSEEK_API_KEY || '').trim()
  // RISK_PROVIDER の指定が最優先。無ければ DeepSeek の鍵がある側を使う。
  // 黙って別の会社に落とさない（どちらで判定したかは decision.model に残る）。
  const asked = (source.RISK_PROVIDER || '').trim().toLowerCase()
  const provider: RiskProvider = asked === 'deepseek' || asked === 'gemini' ? asked : deepseekKey ? 'deepseek' : 'gemini'
  const timeout = Number((source.RISK_TIMEOUT_MS || '').trim())
  return {
    provider,
    // 見張り専用のキー。研究員のチャットと分けておくと、商談中の会話で
    // 見張りの枠を食い潰さない。未設定なら今までどおり共通のキーを使う。
    geminiKey: (source.GEMINI_RISK_API_KEY || '').trim() || source.GEMINI_API_KEY,
    geminiBase: source.GEMINI_BASE_URL,
    model: (source.GEMINI_RISK_MODEL || '').trim() || DEFAULT_MODEL,
    deepseekKey: deepseekKey || undefined,
    deepseekBase: (source.DEEPSEEK_BASE_URL || '').trim() || undefined,
    deepseekModel: (source.DEEPSEEK_RISK_MODEL || '').trim() || DEEPSEEK_DEFAULT_MODEL,
    timeoutMs: Number.isFinite(timeout) && timeout > 0 ? timeout : undefined,
    bridgeToken: (source.TRELAB_RISK_TOKEN || '').trim(),
  }
}

/** いま判定に使う会社と鍵とモデル。表示・記録・鍵チェックで同じものを見る */
export function activeModel(env: RiskEnv): string {
  return env.provider === 'deepseek' ? env.deepseekModel || DEEPSEEK_DEFAULT_MODEL : env.model || DEFAULT_MODEL
}

function activeKey(env: RiskEnv): string | undefined {
  return env.provider === 'deepseek' ? env.deepseekKey : env.geminiKey
}

/**
 * 実際に使ったトークン数。会社が申告してきた値をそのまま持つ（こちらで数えない）。
 * 費用の見積もりを勘に頼らないために、判定と一緒に持ち帰ってブリッジ側に記録する。
 */
export interface TokenUsage {
  input: number
  output: number
  /** キャッシュが効いた入力ぶん（会社が返してきたときだけ） */
  cached?: number
}

interface RawVerdict {
  buy: Assessment
  sell: Assessment
  buyCodes: ReasonCode[]
  sellCodes: ReasonCode[]
  evidence: EvidenceItem[]
  summary: string
  usage?: TokenUsage
}

function stripFence(text: string): string {
  const m = text.match(/```(?:json)?\s*([\s\S]*?)```/)
  return (m ? m[1] : text).trim()
}

function asAssessment(value: unknown): Assessment {
  const s = String(value ?? '').toUpperCase()
  return s === 'BLOCK' || s === 'INSUFFICIENT_DATA' ? (s as Assessment) : 'ALLOW'
}

/** AI に見せる本文。会社が変わっても同じものを見せる（判定を比べられるように） */
function buildUserPrompt(body: RiskRequest): string {
  // JSON は詰めて書く（整形すると改行とインデントのぶんだけ入力トークンが増える。
  // 1回の判定では小さくても、100人ぶんを毎日続けると効いてくる）。
  return [
    '【戦略プロフィール（EAの実際の設定）】',
    JSON.stringify(body.strategy_profile),
    '',
    '【市場データ（ブリッジが MT5 から計算した数値）】',
    JSON.stringify(body.features),
    '',
    `【銘柄】${body.symbol}  【サーバー時刻】${body.server_time}`,
  ].join('\n')
}

/** 会社ごとに名前が違うトークン数を、こちらの呼び方に揃える。数字が無ければ付けない */
function toUsage(raw: unknown, names: { input: string; output: string; cached?: string }): TokenUsage | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const src = raw as Record<string, unknown>
  const num = (key?: string): number | undefined => {
    if (!key) return undefined
    const v = Number(src[key])
    return Number.isFinite(v) ? v : undefined
  }
  const input = num(names.input)
  const output = num(names.output)
  if (input === undefined && output === undefined) return undefined
  const cached = num(names.cached)
  return { input: input ?? 0, output: output ?? 0, ...(cached !== undefined ? { cached } : {}) }
}

/** 返ってきた JSON を判定の形にする。ここでは形を整えるだけで、中身の検証は後段でやる */
function toVerdict(parsed: Record<string, unknown>, usage?: TokenUsage): RawVerdict {
  const evidence = Array.isArray(parsed.evidence) ? (parsed.evidence as EvidenceItem[]) : []
  return {
    ...(usage ? { usage } : {}),
    buy: asAssessment(parsed.buy_assessment),
    sell: asAssessment(parsed.sell_assessment),
    buyCodes: (Array.isArray(parsed.buy_reason_codes) ? parsed.buy_reason_codes : []).map((c) => String(c) as ReasonCode),
    sellCodes: (Array.isArray(parsed.sell_reason_codes) ? parsed.sell_reason_codes : []).map((c) => String(c) as ReasonCode),
    evidence,
    summary: String(parsed.summary ?? '').slice(0, 300),
  }
}

function parseOrThrow(who: string, text: string): Record<string, unknown> {
  try {
    return JSON.parse(stripFence(text)) as Record<string, unknown>
  } catch {
    throw new Error(`${who}: JSONとして読めない応答（${text.slice(0, 120)}）`)
  }
}

/**
 * DeepSeek（OpenAI 互換）。responseSchema が無いので、形は JSON_SHAPE_NOTE で言葉で伝え、
 * JSON モードだけ指定する。中身は Gemini のときと同じ検証に通す。
 */
async function askDeepSeek(env: RiskEnv, body: RiskRequest): Promise<RawVerdict> {
  const model = env.deepseekModel || DEEPSEEK_DEFAULT_MODEL
  const url = `${env.deepseekBase || DEEPSEEK_BASE}/chat/completions`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), env.timeoutMs ?? TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${env.deepseekKey ?? ''}` },
      signal: controller.signal,
      body: JSON.stringify({
        model,
        messages: [
          { role: 'system', content: `${SYSTEM_PROMPT}\n${JSON_SHAPE_NOTE}` },
          { role: 'user', content: buildUserPrompt(body) },
        ],
        response_format: { type: 'json_object' },
        temperature: 0.1,
        max_tokens: 900,
      }),
    })
  } finally {
    clearTimeout(timer)
  }
  if (!res.ok) throw new Error(`deepseek ${res.status}: ${(await res.text()).slice(0, 200)}`)
  const data = (await res.json()) as { choices?: { message?: { content?: string } }[]; usage?: unknown }
  const text = data.choices?.[0]?.message?.content ?? ''
  return toVerdict(
    parseOrThrow('deepseek', text),
    toUsage(data.usage, {
      input: 'prompt_tokens',
      output: 'completion_tokens',
      cached: 'prompt_cache_hit_tokens',
    }),
  )
}

async function askGemini(env: RiskEnv, body: RiskRequest): Promise<RawVerdict> {
  const model = env.model || DEFAULT_MODEL
  const url = `${env.geminiBase || GEMINI_BASE}/models/${model}:generateContent?key=${encodeURIComponent(env.geminiKey ?? '')}`
  const user = buildUserPrompt(body)

  let lastError = ''
  for (let i = currentVariant(); i < CONFIG_VARIANTS.length; i++) {
    const variant = CONFIG_VARIANTS[i]
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), env.timeoutMs ?? TIMEOUT_MS)
    let res: Response
    try {
      res = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
          contents: [{ role: 'user', parts: [{ text: user }] }],
          generationConfig: { temperature: 0.1, maxOutputTokens: 900, ...variant.config },
        }),
      })
    } finally {
      clearTimeout(timer)
    }
    if (!res.ok) {
      lastError = `gemini ${res.status}: ${(await res.text()).slice(0, 200)}`
      // 400 は「この指定を受け付けないモデル」なので次の書き方を試す。それ以外は素直に諦める
      if (res.status === 400) continue
      throw new Error(lastError)
    }
    if (i !== workingVariant) {
      workingVariant = i
      variantUntil = Date.now() + VARIANT_KEEP_MS
      console.log(`[risk] gemini config -> ${variant.name}`)
    }
    const data = (await res.json()) as {
      candidates?: { content?: { parts?: { text?: string }[] } }[]
      usageMetadata?: unknown
    }
    const text = (data.candidates?.[0]?.content?.parts ?? []).map((p) => p.text ?? '').join('')
    return toVerdict(
      parseOrThrow('gemini', text),
      toUsage(data.usageMetadata, {
        input: 'promptTokenCount',
        output: 'candidatesTokenCount',
        cached: 'cachedContentTokenCount',
      }),
    )
  }
  throw new Error(lastError || 'gemini: no response')
}

/** どちらの会社に聞くかの分かれ道。ここ以外に会社ごとの分岐を作らない */
function askModel(env: RiskEnv, body: RiskRequest): Promise<RawVerdict> {
  return env.provider === 'deepseek' ? askDeepSeek(env, body) : askGemini(env, body)
}

// ────────────────────────────────
// 入口
// ────────────────────────────────
const hits = new Map<string, number[]>()

function tooMany(key: string): boolean {
  const now = Date.now()
  const list = (hits.get(key) ?? []).filter((t) => now - t < RATE_WINDOW_MS)
  list.push(now)
  hits.set(key, list)
  if (hits.size > 2000) for (const [k, v] of hits) if (!v.some((t) => now - t < RATE_WINDOW_MS)) hits.delete(k)
  return list.length > RATE_LIMIT
}

/** features に入れてよい値。数値・短い文字列・null だけ（AI に長文を流し込ませない） */
const MAX_FEATURES = 80
const MAX_PROFILE = 60
const MAX_FEATURE_TEXT = 40

function badFeatures(features: Record<string, unknown>, min: number, max: number, label: string): string | null {
  const keys = Object.keys(features)
  if (keys.length < min) return label
  if (keys.length > max) return `${label}: 項目が多すぎます`
  for (const key of keys) {
    if (!/^[A-Za-z0-9_]{1,40}$/.test(key)) return `${label}: 項目名 ${key.slice(0, 20)}`
    const v = features[key]
    if (v === null || typeof v === 'number' || typeof v === 'boolean') continue
    if (typeof v === 'string' && v.length <= MAX_FEATURE_TEXT) continue
    return `${label}: ${key} の値`
  }
  return null
}

function badRequest(body: RiskRequest | null): string | null {
  if (!body || typeof body !== 'object') return 'body'
  if (!body.symbol || typeof body.symbol !== 'string' || !/^[A-Za-z0-9._#-]{1,20}$/.test(body.symbol)) return 'symbol'
  if (!Number.isFinite(Number(body.seq))) return 'seq'
  if (!body.features || typeof body.features !== 'object') return 'features'
  const badF = badFeatures(body.features as Record<string, unknown>, 5, MAX_FEATURES, 'features')
  if (badF) return badF
  if (!body.strategy_profile || typeof body.strategy_profile !== 'object') return 'strategy_profile'
  const badP = badFeatures(body.strategy_profile as Record<string, unknown>, 1, MAX_PROFILE, 'strategy_profile')
  if (badP) return badP
  return null
}

/** 合言葉の照合は長さと中身で早抜けしない（推測の手がかりを与えない） */
function sameSecret(a: string, b: string): boolean {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i)
  return diff === 0
}

export async function handleRisk(
  body: RiskRequest | null,
  env: RiskEnv,
  authToken: string,
): Promise<{ status: number; body: unknown }> {
  const bad = badRequest(body)
  if (bad) return { status: 400, body: { error: `bad ${bad}` } }
  const req = body as RiskRequest

  // 鍵が無い／合言葉を決めていないときは動かさない（AI の踏み台にしない）
  if (!activeKey(env)) return { status: 503, body: { error: 'NOT_CONFIGURED' } }
  if (!env.bridgeToken) return { status: 503, body: { error: 'NOT_CONFIGURED' } }
  if (!sameSecret(authToken, env.bridgeToken)) return { status: 401, body: { error: 'UNAUTHORIZED' } }
  // 呼び出し回数の数え方。bridge_id は本文の値なので、呼ぶ側が毎回変えれば
  // いくらでもすり抜けられる。数えるのは口座と銘柄（お客様1人が動かせない値）。
  // それでもサーバーレスではインスタンスごとに別勘定になるので、これは
  // 「事故で叩きすぎるのを止める」ためのもので、悪用対策にはならない
  // （悪用対策は合言葉を配布物に焼き込まない設計に変えること。AGENTS.md 参照）。
  if (tooMany(`${req.account ?? '?'}@${req.symbol}`)) return { status: 429, body: { error: 'BUSY' } }

  const model = activeModel(env)
  let raw: RawVerdict
  try {
    raw = await askModel(env, req)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    console.error(`[risk] bridge=${req.bridge_id} ${message}`)
    return { status: 502, body: { error: message.slice(0, 300) } }
  }

  const ev = checkEvidence(raw.evidence, req.features)
  const guarded = applyGuards({ buy: raw.buy, sell: raw.sell, buyCodes: raw.buyCodes, sellCodes: raw.sellCodes }, ev.kept)

  const now = new Date()
  const decision: RiskDecision = {
    // 期限・口座・銘柄・連番・版は AI に作らせず、ここで付ける
    seq: Number(req.seq),
    issued_at: now.toISOString(),
    expires_at: new Date(now.getTime() + TTL_SEC * 1000).toISOString(),
    ttl_sec: TTL_SEC,
    account: req.account,
    symbol: req.symbol,
    bar_time: Number(req.bar_time) || 0,
    model,
    prompt_version: PROMPT_VERSION,
    buy: guarded.buy,
    sell: guarded.sell,
    reason_codes: { buy: guarded.buyCodes, sell: guarded.sellCodes },
    evidence: ev.kept,
    summary: raw.summary,
    dropped: [...ev.dropped, ...guarded.dropped],
  }
  return {
    status: 200,
    body: {
      decision,
      request_hash: createHash('sha256').update(JSON.stringify(req.features)).digest('hex').slice(0, 16),
      // 判定そのものではないので decision には入れない（EA も検証もここは見ない）。
      // ブリッジが記録に残し、あとで実費を数えるために使う。
      ...(raw.usage ? { usage: raw.usage } : {}),
    },
  }
}
