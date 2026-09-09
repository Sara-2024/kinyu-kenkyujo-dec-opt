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
export const PROMPT_VERSION = '2026-09-09.1'

/** 既定のモデル。環境変数 GEMINI_RISK_MODEL で変更できる（黙って別のモデルに落とさない） */
const DEFAULT_MODEL = 'gemini-3.5-flash'
const GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta'

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
- evidence の field には、入力の features に実在する項目名だけを書く。値は入力の値をそのまま写す。
- window_high / window_low は取得できた履歴の中の最高値・最安値であり、史上最高値ではない。そう呼ばない。
- 過去成績のデータは渡していない。「実績上苦手」と書かない。テスト用の仮説として書く。
- summary は日本語で1〜2文。お客様に見せる短い説明。`

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

// ────────────────────────────────
// 検証
// ────────────────────────────────
const BUY_CODES: ReasonCode[] = ['NEAR_RESISTANCE', 'OVEREXTENDED_UP', 'BREAKOUT_UNCONFIRMED', 'STRATEGY_CONFLICT']
const SELL_CODES: ReasonCode[] = ['NEAR_SUPPORT', 'OVEREXTENDED_DOWN', 'BREAKOUT_UNCONFIRMED', 'STRATEGY_CONFLICT']

function num(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const n = Number(value.replace(/[^0-9eE+.\-]/g, ''))
    return Number.isFinite(n) ? n : null
  }
  return null
}

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
    const wanted = num(item?.value)
    const actualNum = num(actual)
    if (actualNum != null && wanted != null) {
      // 表示のまるめ差は許す（相対 0.5%、または絶対 0.01）
      const tol = Math.max(Math.abs(actualNum) * 0.005, 0.01)
      if (Math.abs(actualNum - wanted) > tol) {
        dropped.push(`${field}: 値が入力と違う（入力 ${actual} / 主張 ${item.value}）`)
        continue
      }
    } else if (actual != null && String(actual).trim() !== String(item?.value ?? '').trim()) {
      dropped.push(`${field}: 値が入力と違う（入力 ${actual} / 主張 ${item.value}）`)
      continue
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

  let buy = raw.buy
  let sell = raw.sell
  if (buy === 'BLOCK' && (buyCodes.length === 0 || evidence.length === 0)) {
    dropped.push('買い停止：根拠か理由コードが無いので採用しない')
    buy = 'ALLOW'
  }
  if (sell === 'BLOCK' && (sellCodes.length === 0 || evidence.length === 0)) {
    dropped.push('売り停止：根拠か理由コードが無いので採用しない')
    sell = 'ALLOW'
  }
  return { buy, sell, buyCodes: buy === 'BLOCK' ? buyCodes : [], sellCodes: sell === 'BLOCK' ? sellCodes : [], dropped }
}

// ────────────────────────────────
// Gemini 呼び出し
// ────────────────────────────────
export interface RiskEnv {
  geminiKey?: string
  geminiBase?: string
  model?: string
  bridgeToken?: string
}

export function riskEnvFrom(source: Record<string, string | undefined>): RiskEnv {
  return {
    geminiKey: source.GEMINI_API_KEY,
    geminiBase: source.GEMINI_BASE_URL,
    model: (source.GEMINI_RISK_MODEL || '').trim() || DEFAULT_MODEL,
    bridgeToken: (source.TRELAB_RISK_TOKEN || '').trim(),
  }
}

interface RawVerdict {
  buy: Assessment
  sell: Assessment
  buyCodes: ReasonCode[]
  sellCodes: ReasonCode[]
  evidence: EvidenceItem[]
  summary: string
}

function stripFence(text: string): string {
  const m = text.match(/```(?:json)?\s*([\s\S]*?)```/)
  return (m ? m[1] : text).trim()
}

function asAssessment(value: unknown): Assessment {
  const s = String(value ?? '').toUpperCase()
  return s === 'BLOCK' || s === 'INSUFFICIENT_DATA' ? (s as Assessment) : 'ALLOW'
}

async function askGemini(env: RiskEnv, body: RiskRequest): Promise<RawVerdict> {
  const model = env.model || DEFAULT_MODEL
  const url = `${env.geminiBase || GEMINI_BASE}/models/${model}:generateContent?key=${encodeURIComponent(env.geminiKey ?? '')}`
  const user = [
    '【戦略プロフィール（EAの実際の設定）】',
    JSON.stringify(body.strategy_profile, null, 1),
    '',
    '【市場データ（ブリッジが MT5 から計算した数値）】',
    JSON.stringify(body.features, null, 1),
    '',
    `【銘柄】${body.symbol}  【サーバー時刻】${body.server_time}`,
  ].join('\n')

  let lastError = ''
  for (let i = workingVariant; i < CONFIG_VARIANTS.length; i++) {
    const variant = CONFIG_VARIANTS[i]
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
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
      console.log(`[risk] gemini config -> ${variant.name}`)
    }
    const data = (await res.json()) as { candidates?: { content?: { parts?: { text?: string }[] } }[] }
    const text = (data.candidates?.[0]?.content?.parts ?? []).map((p) => p.text ?? '').join('')
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(stripFence(text)) as Record<string, unknown>
    } catch {
      throw new Error(`gemini: JSONとして読めない応答（${text.slice(0, 120)}）`)
    }
    const evidence = Array.isArray(parsed.evidence) ? (parsed.evidence as EvidenceItem[]) : []
    return {
      buy: asAssessment(parsed.buy_assessment),
      sell: asAssessment(parsed.sell_assessment),
      buyCodes: (Array.isArray(parsed.buy_reason_codes) ? parsed.buy_reason_codes : []).map((c) => String(c) as ReasonCode),
      sellCodes: (Array.isArray(parsed.sell_reason_codes) ? parsed.sell_reason_codes : []).map((c) => String(c) as ReasonCode),
      evidence,
      summary: String(parsed.summary ?? '').slice(0, 300),
    }
  }
  throw new Error(lastError || 'gemini: no response')
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

function badRequest(body: RiskRequest | null): string | null {
  if (!body || typeof body !== 'object') return 'body'
  if (!body.symbol || typeof body.symbol !== 'string') return 'symbol'
  if (!Number.isFinite(Number(body.seq))) return 'seq'
  if (!body.features || typeof body.features !== 'object') return 'features'
  if (Object.keys(body.features).length < 5) return 'features'
  if (!body.strategy_profile || typeof body.strategy_profile !== 'object') return 'strategy_profile'
  return null
}

export async function handleRisk(
  body: RiskRequest | null,
  env: RiskEnv,
  authToken: string,
): Promise<{ status: number; body: unknown }> {
  const bad = badRequest(body)
  if (bad) return { status: 400, body: { error: `bad ${bad}` } }
  const req = body as RiskRequest

  // 鍵が無い／合言葉を決めていないときは動かさない（Gemini の踏み台にしない）
  if (!env.geminiKey) return { status: 503, body: { error: 'NOT_CONFIGURED' } }
  if (!env.bridgeToken) return { status: 503, body: { error: 'NOT_CONFIGURED' } }
  if (authToken !== env.bridgeToken) return { status: 401, body: { error: 'UNAUTHORIZED' } }
  if (tooMany(String(req.bridge_id || 'unknown'))) return { status: 429, body: { error: 'BUSY' } }

  const model = env.model || DEFAULT_MODEL
  let raw: RawVerdict
  try {
    raw = await askGemini(env, req)
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
    },
  }
}
