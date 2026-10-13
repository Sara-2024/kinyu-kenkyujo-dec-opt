// ドリームランド渡航手続き: MT5 口座の申込を預かる。
//
// ロビー（dreamland/index.html）のサービスカウンターから、お客様が記入した
// 口座番号・サーバー・パスワード・プランがここへ送られてくる。
// Supabase の dreamland_apply に取り次ぎ、受付番号を返す。
//
//   ・ロビーは別のドメインに置かれるので CORS を開ける（送るのはお客様自身の情報。
//     合言葉や会員の情報は返さない）
//   ・1台あたりの回数を数えて、叩きすぎを止める（サーバーレスなので目安）
//   ・パスワードは記録に残さない（ログにも応答にも出さない）
//   ・鍵（Supabase）が無ければ 503。ロビーは「サポートへ」の案内に切り替える

/** 1台あたりの申込回数の上限（連打・いたずら対策） */
const RATE_LIMIT = 6
const RATE_WINDOW_MS = 10 * 60_000
const PLANS = ['first', 'crystal'] as const
const PLATFORMS = ['windows', 'mac'] as const

export type DreamlandPlan = (typeof PLANS)[number]

export interface DreamlandEnv {
  supabaseUrl?: string
  supabaseKey?: string
  /** ロビーを置いたドメイン。空なら「どこからでも」 */
  allowOrigin?: string
}

export interface DreamlandRequest {
  account?: unknown
  server?: unknown
  password?: unknown
  plan?: unknown
  name?: unknown
  email?: unknown
  platform?: unknown
  consent?: unknown
}

export interface DreamlandResult {
  status: number
  body: Record<string, unknown>
}

export function envFrom(source: Record<string, string | undefined>): DreamlandEnv {
  return {
    supabaseUrl: (source.VITE_SUPABASE_URL || source.SUPABASE_URL || '').trim() || undefined,
    supabaseKey: (source.VITE_SUPABASE_ANON_KEY || source.SUPABASE_ANON_KEY || '').trim() || undefined,
    allowOrigin: (source.DREAMLAND_ORIGIN || '').trim() || undefined,
  }
}

const hits = new Map<string, number[]>()

export function tooMany(key: string, now = Date.now()): boolean {
  const list = (hits.get(key) ?? []).filter((t) => now - t < RATE_WINDOW_MS)
  list.push(now)
  hits.set(key, list)
  return list.length > RATE_LIMIT
}

/** 試験用。回数の記録を消す */
export function resetRate(): void {
  hits.clear()
}

export interface CleanInput {
  account: number
  server: string
  password: string
  plan: DreamlandPlan
  name: string
  email: string
  platform: (typeof PLATFORMS)[number] | null
  consent: true
}

/** 入力を整える。駄目なものは理由コードを返す（Supabase と同じ名前） */
export function clean(req: DreamlandRequest | null): { ok: true; value: CleanInput } | { ok: false; error: string } {
  if (!req || typeof req !== 'object') return { ok: false, error: 'BAD_REQUEST' }
  if (req.consent !== true) return { ok: false, error: 'NO_CONSENT' }

  const accountRaw = typeof req.account === 'number' ? req.account : typeof req.account === 'string' ? req.account.trim() : ''
  const account = Number(accountRaw)
  if (!Number.isInteger(account) || account <= 0 || account > 9_999_999_999_999) return { ok: false, error: 'BAD_ACCOUNT' }

  const server = typeof req.server === 'string' ? req.server.trim() : ''
  if (!server || server.length > 80) return { ok: false, error: 'BAD_SERVER' }

  const password = typeof req.password === 'string' ? req.password : ''
  if (!password || password.length > 200) return { ok: false, error: 'BAD_PASSWORD' }

  const plan = typeof req.plan === 'string' ? req.plan.trim() : ''
  if (!(PLANS as readonly string[]).includes(plan)) return { ok: false, error: 'BAD_PLAN' }

  const name = typeof req.name === 'string' ? req.name.trim().slice(0, 80) : ''
  const email = typeof req.email === 'string' ? req.email.trim().toLowerCase().slice(0, 200) : ''
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return { ok: false, error: 'BAD_EMAIL' }

  const platformRaw = typeof req.platform === 'string' ? req.platform.trim() : ''
  const platform = (PLATFORMS as readonly string[]).includes(platformRaw) ? (platformRaw as CleanInput['platform']) : null

  return { ok: true, value: { account, server, password, plan: plan as DreamlandPlan, name, email, platform, consent: true } }
}

/** 記録に残してよい形。口座番号は下2桁だけ */
export function maskAccount(account: number | string): string {
  const s = String(account)
  return s.length <= 2 ? '**' : `${'*'.repeat(s.length - 2)}${s.slice(-2)}`
}

export async function handleDreamland(
  req: DreamlandRequest | null,
  env: DreamlandEnv,
  clientKey: string,
  fetchImpl: typeof fetch = fetch,
): Promise<DreamlandResult> {
  const url = env.supabaseUrl
  const key = env.supabaseKey
  if (!url || !key || !url.startsWith('https://')) {
    return { status: 503, body: { error: 'NOT_CONFIGURED' } }
  }

  const input = clean(req)
  if (!input.ok) {
    return { status: 400, body: { error: input.error } }
  }
  if (tooMany(clientKey)) {
    return { status: 429, body: { error: 'BUSY' } }
  }

  const v = input.value
  let res: Response
  try {
    res = await fetchImpl(`${url}/rest/v1/rpc/dreamland_apply`, {
      method: 'POST',
      headers: { apikey: key, authorization: `Bearer ${key}`, 'content-type': 'application/json' },
      body: JSON.stringify({
        p_account: v.account,
        p_server: v.server,
        p_password: v.password,
        p_plan: v.plan,
        p_name: v.name,
        p_email: v.email,
        p_platform: v.platform,
        p_consent: true,
      }),
    })
  } catch {
    return { status: 502, body: { error: 'UPSTREAM_UNAVAILABLE' } }
  }

  if (!res.ok) {
    // Supabase の理由コード（BAD_ACCOUNT など）はそのまま返す。それ以外は伏せる
    const text = await res.text().catch(() => '')
    const code = (text.match(/\b(NO_CONSENT|BAD_ACCOUNT|BAD_SERVER|BAD_PASSWORD|BAD_PLAN)\b/) || [])[1]
    if (code) return { status: 400, body: { error: code } }
    // 関数がまだ無い（migration を流していない）ときは、ロビーに「準備中」を出させない
    return { status: 502, body: { error: 'UPSTREAM_ERROR' } }
  }

  const data = (await res.json().catch(() => null)) as { application_no?: string; plan?: string; submissions?: number } | null
  if (!data?.application_no) {
    return { status: 502, body: { error: 'UPSTREAM_ERROR' } }
  }

  return {
    status: 200,
    body: { ok: true, application_no: data.application_no, plan: data.plan ?? v.plan, submissions: data.submissions ?? 1 },
  }
}

export async function readJson(req: {
  on: (event: string, cb: (chunk?: unknown) => void) => void
}): Promise<DreamlandRequest | null> {
  return await new Promise((resolve) => {
    let raw = ''
    req.on('data', (chunk) => {
      raw += String(chunk)
      if (raw.length > 8192) raw = raw.slice(0, 8192)
    })
    req.on('end', () => {
      try {
        resolve(JSON.parse(raw) as DreamlandRequest)
      } catch {
        resolve(null)
      }
    })
  })
}
