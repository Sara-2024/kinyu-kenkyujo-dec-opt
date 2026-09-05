// 研究員の受け答え（AI）。Gemini 3.5 Flash-Lite に聞く。
//
//   POST /api/chat  { role, question, context, names }
//   →  { answer, redirect }   redirect は担当外のとき、案内先の研究員の id
//
// 費用を抑えるための決まり:
//   - 研究員ごとに担当を固定し、画面側が「その担当ぶんのデータ」だけを context に入れて送る。
//     サーバーは何も調べに行かない（相場や口座のデータをここで取りに行かない）。
//   - 担当外の質問は答えを作らず redirect だけ返す。中身の調査はしない。
//   - 出力は短く（maxOutputTokens）、思考トークンは使わない（thinkingBudget 0）。
//   - context と質問の長さに上限を置く。
//
// 会員の確認は Supabase の auth_me（画面と同じ RPC）で行う。

export type Role = 'rin' | 'jin' | 'algo' | 'mio'

const ROLES: Role[] = ['rin', 'jin', 'algo', 'mio']

const MODEL = 'gemini-3.5-flash-lite'
const GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta'

const MAX_QUESTION = 300
const MAX_CONTEXT = 9000
const MAX_OUTPUT_TOKENS = 600

/** 担当の説明。担当外の範囲は「誰に案内するか」だけ持たせる */
const ROLE_SPEC: Record<Role, { scope: string; outside: string }> = {
  rin: {
    scope:
      '担当は「チャート分析」。渡された銘柄のローソク足・直近の高値と安値・移動平均・いまの値段から、いまどういう形かを説明する。' +
      '直近の高値・安値がどこか、値段がそこからどれくらい離れているか、移動平均に対して上か下かを、渡された数字で具体的に言う。',
    outside:
      '経済指標・金利・ニュースの背景は jin、自動売買システムの稼働状況や成績は algo、お客様ご自身のトレードの傾向や弱点は mio の担当。',
  },
  jin: {
    scope:
      '担当は「経済指標と金利」。渡された経済指標カレンダー（発表時刻・予想・前回）と主要な相場の現在値から、' +
      'いつ何があるか、それがどの通貨に関わるか、なぜ相場が動きやすいかを説明する。',
    outside:
      'チャートの形や高値・安値の分析は rin、自動売買システムの稼働状況や成績は algo、お客様ご自身のトレードの傾向や弱点は mio の担当。',
  },
  algo: {
    scope:
      '担当は「自動売買システム（EA）」。渡された MT5 の状態・本日の成績・建玉・システムが行った取引の集計から、' +
      'システムがいまどう動いているか、どの取引が一番利益を出したか・損を出したか、どの銘柄で成績が良いかを説明する。',
    outside:
      'チャートの形の分析は rin、経済指標や金利の話は jin、お客様ご自身（手動）のトレードのクセや弱点は mio の担当。',
  },
  mio: {
    scope:
      '担当は「お客様ご自身のトレードの利益分析」。渡された約定履歴の集計（勝率・平均損益・保有時間・時間帯・曜日・銘柄ごとの成績・気づき）から、' +
      '直近1週間や1か月のトレードの弱点と良い点を、数字を示して指摘する。',
    outside:
      'チャートの形の分析は rin、経済指標や金利の話は jin、自動売買システムそのものの稼働や設定は algo の担当。',
  },
}

const COMMON_RULES = `あなたは投資家向けサイト「トレード研究所」の研究員です。40〜50代のお客様に、ていねいな日本語（です・ます調）で話します。
守ること:
1. 渡された「手元のデータ」にある数字だけを使う。データに無い数字・日付・出来事を作らない。データに無いことを聞かれたら「手元のデータにはありません」と言う。
2. 売買の指示や予想をしない。「買いです」「売りです」「上がります」「下がります」と言わない。代わりに「こういう形なので、判断の境目はここです」という説明にとどめる。
3. 担当の範囲だけ答える。担当外の質問は、中身を調べたり答えたりせず、redirect に担当者の id を入れ、answer は空文字にする。担当内なら redirect は "none"。
4. あいさつや雑談（「こんにちは」「ありがとう」など）は担当内として短く返す。
5. answer は 300 文字以内。箇条書きは使わず、話し言葉で。文中で他の研究員を呼ぶときは、渡された名前を使う。
6. 出力は JSON だけ: {"answer": string, "redirect": "none"|"rin"|"jin"|"algo"|"mio"}`

export interface ChatRequest {
  role?: unknown
  question?: unknown
  context?: unknown
  names?: unknown
}

export interface ChatEnv {
  geminiKey?: string
  /** テストで差し替える。既定は本物の Gemini */
  geminiBase?: string
  supabaseUrl?: string
  supabaseKey?: string
}

export interface ChatResult {
  status: number
  body: { answer: string; redirect: Role | null } | { error: string }
}

// ── 会員の確認（5分だけ覚えて RPC を減らす） ──
const verified = new Map<string, number>()
const VERIFY_KEEP_MS = 5 * 60 * 1000

async function verifyMember(token: string | null, env: ChatEnv): Promise<'ok' | 'unauthorized' | 'skip'> {
  const url = env.supabaseUrl?.trim()
  const key = env.supabaseKey?.trim()
  if (!url || !key || !url.startsWith('https://') || url.includes('xxxxxxxx')) return 'skip'
  if (!token) return 'unauthorized'
  const seen = verified.get(token)
  if (seen && Date.now() - seen < VERIFY_KEEP_MS) return 'ok'
  const res = await fetch(`${url}/rest/v1/rpc/auth_me`, {
    method: 'POST',
    headers: { apikey: key, authorization: `Bearer ${key}`, 'content-type': 'application/json' },
    body: JSON.stringify({ p_token: token }),
  })
  if (!res.ok) return 'unauthorized'
  const data = (await res.json().catch(() => null)) as { member?: { status?: string } } | null
  if (!data?.member || data.member.status === 'suspended') return 'unauthorized'
  verified.set(token, Date.now())
  return 'ok'
}

// ── 同じ人からの連打を抑える（1分に 20 回まで。関数ごとの目安） ──
const hits = new Map<string, number[]>()
function tooMany(who: string): boolean {
  const now = Date.now()
  const list = (hits.get(who) ?? []).filter((t) => now - t < 60_000)
  list.push(now)
  hits.set(who, list)
  return list.length > 20
}

function str(v: unknown, max: number): string {
  return typeof v === 'string' ? v.trim().slice(0, max) : ''
}

function namesOf(v: unknown): Record<Role, string> {
  const base: Record<Role, string> = { rin: 'リン', jin: 'ジン', algo: 'アルゴ', mio: 'ミオ' }
  if (v && typeof v === 'object') {
    for (const id of ROLES) {
      const n = (v as Record<string, unknown>)[id]
      if (typeof n === 'string' && n.trim()) base[id] = n.trim().slice(0, 20)
    }
  }
  return base
}

function contextText(v: unknown): string {
  if (typeof v === 'string') return v.slice(0, MAX_CONTEXT)
  if (v && typeof v === 'object') return JSON.stringify(v).slice(0, MAX_CONTEXT)
  return ''
}

function systemPrompt(role: Role, names: Record<Role, string>): string {
  const spec = ROLE_SPEC[role]
  const others = ROLES.filter((r) => r !== role)
    .map((r) => `${r}=${names[r]}`)
    .join(', ')
  return (
    `${COMMON_RULES}\n\n` +
    `あなたの名前は「${names[role]}」（id: ${role}）。${spec.scope}\n` +
    `担当外: ${spec.outside}\n` +
    `研究員の id と名前: ${others}`
  )
}

interface GeminiResponse {
  candidates?: Array<{ content?: { parts?: Array<{ text?: string }> }; finishReason?: string }>
  error?: { message?: string }
}

/**
 * generationConfig の書き方はモデルの版で変わる（思考の指定・JSON スキーマの扱い）。
 * 上から順に試し、通った形を覚えておく。400 で弾かれたときだけ次を試すので、ふだんは 1 回で済む。
 */
const RESPONSE_SCHEMA = {
  type: 'OBJECT',
  properties: {
    answer: { type: 'STRING' },
    redirect: { type: 'STRING', enum: ['none', ...ROLES] },
  },
  required: ['answer', 'redirect'],
}
const CONFIG_VARIANTS: Array<{ name: string; config: Record<string, unknown> }> = [
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
  { name: 'plain', config: {} },
]
let workingVariant = 0

export async function callGemini(
  env: ChatEnv,
  system: string,
  user: string,
): Promise<{ answer: string; redirect: Role | null }> {
  const base = env.geminiBase || GEMINI_BASE
  const url = `${base}/models/${MODEL}:generateContent?key=${encodeURIComponent(env.geminiKey ?? '')}`
  let data: GeminiResponse | null = null
  let lastError = ''
  for (let i = workingVariant; i < CONFIG_VARIANTS.length; i++) {
    const variant = CONFIG_VARIANTS[i]
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: system }] },
        contents: [{ role: 'user', parts: [{ text: user }] }],
        generationConfig: { temperature: 0.3, maxOutputTokens: MAX_OUTPUT_TOKENS, ...variant.config },
      }),
    })
    data = (await res.json().catch(() => null)) as GeminiResponse | null
    if (res.ok) {
      if (i !== workingVariant) console.log(`[chat] gemini config -> ${variant.name}`)
      workingVariant = i
      break
    }
    lastError = `gemini ${res.status}: ${data?.error?.message ?? ''}`
    // 形が合わない（400）ときだけ次の形を試す。鍵や上限のエラーは試しても変わらない
    if (res.status !== 400) throw new Error(lastError)
    console.warn(`[chat] ${variant.name} rejected: ${lastError}`)
    data = null
  }
  if (!data) throw new Error(lastError || 'gemini: no response')
  const text = data.candidates?.[0]?.content?.parts?.map((p) => p.text ?? '').join('') ?? ''
  let parsed: { answer?: unknown; redirect?: unknown } = {}
  try {
    parsed = JSON.parse(stripFence(text)) as { answer?: unknown; redirect?: unknown }
  } catch {
    // JSON で返ってこなかったときは本文をそのまま答えにする
    parsed = { answer: text, redirect: 'none' }
  }
  const redirect = ROLES.includes(parsed.redirect as Role) ? (parsed.redirect as Role) : null
  const answer = typeof parsed.answer === 'string' ? parsed.answer.trim() : ''
  return { answer, redirect }
}

/** ```json … ``` で包んで返ってきたときに中身だけにする */
function stripFence(text: string): string {
  const m = /^\s*```(?:json)?\s*([\s\S]*?)\s*```\s*$/.exec(text)
  return m ? m[1] : text
}

export async function handleChat(req: ChatRequest, token: string | null, env: ChatEnv): Promise<ChatResult> {
  const role = str(req.role, 10) as Role
  if (!ROLES.includes(role)) return { status: 400, body: { error: 'bad role' } }
  const question = str(req.question, MAX_QUESTION)
  if (!question) return { status: 400, body: { error: 'empty' } }
  if (!env.geminiKey) return { status: 503, body: { error: 'NOT_CONFIGURED' } }

  const auth = await verifyMember(token, env)
  if (auth === 'unauthorized') return { status: 401, body: { error: 'UNAUTHORIZED' } }
  if (tooMany(token ?? 'anonymous')) return { status: 429, body: { error: 'BUSY' } }

  const names = namesOf(req.names)
  const context = contextText(req.context)
  const user = `【手元のデータ】\n${context || '（なし）'}\n\n【お客様の質問】\n${question}`
  try {
    const out = await callGemini(env, systemPrompt(role, names), user)
    // 担当内なのに空で返ってきたときは、ひとこと添える
    if (!out.redirect && !out.answer) out.answer = 'いまは手元のデータからお答えできる材料がありません。'
    // 自分宛ての redirect は意味がないので消す
    if (out.redirect === role) out.redirect = null
    return { status: 200, body: out }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    // Vercel のログで原因が追えるように残す（鍵そのものは出さない）
    console.error(`[chat] role=${role} gemini failed: ${message}`)
    return { status: 502, body: { error: message } }
  }
}

/** 生の HTTP から JSON 本文を読む（Vercel と Vite の両方で使う） */
export async function readJson(req: AsyncIterable<Uint8Array | string>): Promise<ChatRequest> {
  const chunks: Buffer[] = []
  for await (const chunk of req) chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : Buffer.from(chunk))
  const raw = Buffer.concat(chunks).toString('utf8')
  if (!raw) return {}
  try {
    return JSON.parse(raw) as ChatRequest
  } catch {
    return {}
  }
}

export function bearerOf(header: string | string[] | undefined): string | null {
  const h = Array.isArray(header) ? header[0] : header
  if (!h) return null
  const m = /^Bearer\s+(.+)$/i.exec(h.trim())
  return m ? m[1].trim() : null
}

export function envFrom(source: Record<string, string | undefined>): ChatEnv {
  return {
    geminiKey: source.GEMINI_API_KEY?.trim() || undefined,
    geminiBase: source.GEMINI_BASE_URL?.trim() || undefined,
    supabaseUrl: source.VITE_SUPABASE_URL || source.SUPABASE_URL,
    supabaseKey: source.VITE_SUPABASE_ANON_KEY || source.SUPABASE_ANON_KEY,
  }
}
