// ドリームランド渡航手続き: ロビー（dreamland/index.html）が本体サイトの会員のしくみを使うための窓口。
//
// ロビーは Supabase を直接叩かない（鍵を配らない）。ここが取り次ぐ。
//
//   plan          … 合言葉がどのプランか（登録の前に案内を振り分ける）
//   register      … 会員登録（口座番号・お名前・サイトのパスワード・合言葉）→ セッションの合言葉
//   login         … すでに登録した口座でログイン → セッションの合言葉
//   me            … セッションの合言葉から会員（プランを含む）
//   connect_token … 接続ツールを呼び出すための短命の合図（connect_token_issue）
//   platform      … お使いのパソコン（windows / mac）を記録する
//
//   ・ロビーは別のドメインに置かれるので CORS を開ける（DREAMLAND_ORIGIN で絞れる）
//   ・1台あたりの回数を数えて、合言葉やパスワードの総当たりを止める（サーバーレスなので目安）
//   ・パスワード・合言葉・セッション・合図は、ログにも応答の記録にも出さない

// 回数の上限は「当てにいく操作」と「つなぐ操作」で分ける。
//   合言葉・パスワードの確認（plan / register / login）… 総当たり対策で少なめ
//   会員の確認・合図の発行・OS の記録（me / connect_token / platform）… 設置をやり直すたびに何度も呼ぶので多め
//   （一緒に数えていたら、ダウンロードとやり直しを繰り返したお客様が合言葉を打てなくなった）
const RATE_LIMIT_GUESS = 20
const RATE_LIMIT_SESSION = 200
const RATE_WINDOW_MS = 10 * 60_000
const GUESS_ACTIONS = new Set(['plan', 'register', 'login'])
const ACTIONS = ['plan', 'register', 'login', 'me', 'connect_token', 'platform'] as const
const PLATFORMS = ['windows', 'mac'] as const
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export type LobbyAction = (typeof ACTIONS)[number]

export interface LobbyEnv {
  supabaseUrl?: string
  supabaseKey?: string
  allowOrigin?: string
}

export interface LobbyRequest {
  action?: unknown
  entry?: unknown
  account?: unknown
  name?: unknown
  password?: unknown
  session?: unknown
  platform?: unknown
}

export interface LobbyResult {
  status: number
  body: Record<string, unknown>
}

export function envFrom(source: Record<string, string | undefined>): LobbyEnv {
  return {
    supabaseUrl: (source.VITE_SUPABASE_URL || source.SUPABASE_URL || '').trim() || undefined,
    supabaseKey: (source.VITE_SUPABASE_ANON_KEY || source.SUPABASE_ANON_KEY || '').trim() || undefined,
    allowOrigin: (source.DREAMLAND_ORIGIN || '').trim() || undefined,
  }
}

const hits = new Map<string, number[]>()

export function tooMany(key: string, now = Date.now(), action = 'plan'): boolean {
  const guess = GUESS_ACTIONS.has(action)
  const bucket = `${key}:${guess ? 'guess' : 'session'}`
  const list = (hits.get(bucket) ?? []).filter((t) => now - t < RATE_WINDOW_MS)
  list.push(now)
  hits.set(bucket, list)
  return list.length > (guess ? RATE_LIMIT_GUESS : RATE_LIMIT_SESSION)
}

/** 試験用。回数の記録を消す */
export function resetRate(): void {
  hits.clear()
}

/** 記録に残してよい形。口座番号は下2桁だけ */
export function maskAccount(account: unknown): string {
  if (typeof account !== 'number' && typeof account !== 'string') return '-'
  const s = String(account).trim()
  if (!s) return '-'
  return s.length <= 2 ? '**' : `${'*'.repeat(s.length - 2)}${s.slice(-2)}`
}

/** 会員の JSON のうち、ロビーに返してよいところだけ */
export function publicMember(raw: unknown): Record<string, unknown> | null {
  if (!raw || typeof raw !== 'object') return null
  const m = raw as Record<string, unknown>
  if (typeof m.id !== 'string') return null
  return {
    id: m.id,
    account: m.account ?? null,
    name: typeof m.name === 'string' ? m.name : '',
    plan: m.plan === 'first' || m.plan === 'crystal' ? m.plan : null,
    status: m.status ?? 'active',
  }
}

type Clean =
  | { ok: true; action: LobbyAction; rpc: string; args: Record<string, unknown> }
  | { ok: false; error: string }

function str(v: unknown, max: number): string {
  return typeof v === 'string' ? v.slice(0, max) : ''
}

/** 入力を整え、呼ぶ RPC と引数に直す。駄目なものは理由コードを返す */
export function clean(req: LobbyRequest | null): Clean {
  if (!req || typeof req !== 'object') return { ok: false, error: 'BAD_REQUEST' }
  const actionRaw = typeof req.action === 'string' ? req.action : ''
  if (!(ACTIONS as readonly string[]).includes(actionRaw)) return { ok: false, error: 'BAD_ACTION' }
  const action = actionRaw as LobbyAction

  const session = str(req.session, 64).trim()
  const needSession = () => (UUID_RE.test(session) ? null : 'NO_SESSION')

  if (action === 'plan') {
    const entry = str(req.entry, 200).trim()
    if (!entry) return { ok: false, error: 'BAD_ENTRY' }
    return { ok: true, action, rpc: 'plan_check', args: { p_entry: entry } }
  }
  if (action === 'register' || action === 'login') {
    const accountRaw = typeof req.account === 'number' ? req.account : typeof req.account === 'string' ? req.account.trim() : ''
    const account = Number(accountRaw)
    if (!Number.isInteger(account) || account <= 0 || account > 9_999_999_999_999) return { ok: false, error: 'BAD_ACCOUNT' }
    const password = str(req.password, 200)
    if (!password) return { ok: false, error: 'BAD_PASSWORD' }
    if (action === 'login') {
      return { ok: true, action, rpc: 'auth_login', args: { p_account: account, p_password: password } }
    }
    if (password.length < 8) return { ok: false, error: 'WEAK_PASSWORD' }
    const name = str(req.name, 80).trim()
    if (!name) return { ok: false, error: 'BAD_NAME' }
    const entry = str(req.entry, 200).trim()
    if (!entry) return { ok: false, error: 'BAD_ENTRY' }
    return { ok: true, action, rpc: 'auth_register', args: { p_account: account, p_name: name, p_password: password, p_entry: entry } }
  }
  const missing = needSession()
  if (missing) return { ok: false, error: missing }
  if (action === 'me') return { ok: true, action, rpc: 'auth_me', args: { p_token: session } }
  if (action === 'connect_token') return { ok: true, action, rpc: 'connect_token_issue', args: { p_token: session } }
  // platform
  const platform = str(req.platform, 16).trim()
  if (!(PLATFORMS as readonly string[]).includes(platform)) return { ok: false, error: 'BAD_PLATFORM' }
  return { ok: true, action, rpc: 'member_platform_set', args: { p_token: session, p_platform: platform } }
}

/** Supabase が raise した理由コードを、そのまま返してよいものだけ拾う */
const KNOWN_ERRORS = ['BAD_ENTRY', 'ACCOUNT_TAKEN', 'WEAK_PASSWORD', 'BAD_NAME', 'BAD_ACCOUNT', 'BAD_CREDENTIALS', 'SUSPENDED', 'SESSION_EXPIRED', 'FORBIDDEN', 'BAD_PLATFORM']

export function errorCodeOf(text: string): string | null {
  const m = text.match(new RegExp(`\\b(${KNOWN_ERRORS.join('|')})\\b`))
  return m ? m[1] : null
}

function statusOf(code: string): number {
  if (code === 'BAD_CREDENTIALS' || code === 'SESSION_EXPIRED' || code === 'BAD_ENTRY') return 401
  if (code === 'SUSPENDED' || code === 'FORBIDDEN') return 403
  return 400
}

export async function handleLobby(
  req: LobbyRequest | null,
  env: LobbyEnv,
  clientKey: string,
  fetchImpl: typeof fetch = fetch,
): Promise<LobbyResult> {
  const url = env.supabaseUrl
  const key = env.supabaseKey
  if (!url || !key || !url.startsWith('https://')) {
    return { status: 503, body: { error: 'NOT_CONFIGURED' } }
  }
  const input = clean(req)
  if (!input.ok) return { status: 400, body: { error: input.error } }
  if (tooMany(clientKey, Date.now(), input.action)) return { status: 429, body: { error: 'BUSY' } }

  let res: Response
  try {
    res = await fetchImpl(`${url}/rest/v1/rpc/${input.rpc}`, {
      method: 'POST',
      headers: { apikey: key, authorization: `Bearer ${key}`, 'content-type': 'application/json' },
      body: JSON.stringify(input.args),
    })
  } catch {
    return { status: 502, body: { error: 'UPSTREAM_UNAVAILABLE' } }
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    const code = errorCodeOf(text)
    if (code) return { status: statusOf(code), body: { error: code } }
    return { status: 502, body: { error: 'UPSTREAM_ERROR' } }
  }

  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null

  if (input.action === 'plan') {
    const plan = data?.plan
    if (plan !== 'first' && plan !== 'crystal') return { status: 401, body: { error: 'BAD_ENTRY' } }
    return { status: 200, body: { ok: true, plan } }
  }
  if (input.action === 'register' || input.action === 'login') {
    const token = typeof data?.token === 'string' ? data.token : ''
    const member = publicMember(data?.member)
    if (!UUID_RE.test(token) || !member) return { status: 502, body: { error: 'UPSTREAM_ERROR' } }
    return { status: 200, body: { ok: true, session: token, member } }
  }
  if (input.action === 'me') {
    const member = publicMember(data?.member)
    if (!member) return { status: 401, body: { error: 'SESSION_EXPIRED' } }
    return { status: 200, body: { ok: true, member } }
  }
  if (input.action === 'connect_token') {
    const token = typeof data?.token === 'string' ? data.token : ''
    if (!/^[0-9a-f]{64}$/i.test(token)) return { status: 502, body: { error: 'UPSTREAM_ERROR' } }
    return { status: 200, body: { ok: true, token, expires_in: typeof data?.expires_in === 'number' ? data.expires_in : 300 } }
  }
  return { status: 200, body: { ok: true } }
}

export async function readJson(req: {
  on: (event: string, cb: (chunk?: unknown) => void) => void
}): Promise<LobbyRequest | null> {
  return await new Promise((resolve) => {
    let raw = ''
    req.on('data', (chunk) => {
      raw += String(chunk)
      if (raw.length > 8192) raw = raw.slice(0, 8192)
    })
    req.on('end', () => {
      try {
        resolve(JSON.parse(raw) as LobbyRequest)
      } catch {
        resolve(null)
      }
    })
    req.on('error', () => resolve(null))
  })
}
