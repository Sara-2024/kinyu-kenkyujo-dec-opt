// MT5連携のワンタイム合図を確かめる。
//
// お客様のPCの MT5 Automatic が、aitrader://connect?token=... で受け取った
// 合図をここへ送ってくる。正しければ、その会員の部屋（会員ID）を返す。
//
//   ・合図を作れるのはサイトだけ（ログイン中のセッションが要る）
//   ・アプリ単体では作れない＝サイトから始めない限り連携できない
//   ・使えるのは一度だけ。数分で切れる
//   ・確かめるのは Supabase 側（connect_token_redeem）。ここは取り次ぐだけ
//
// 既存の認証（members / sessions）はそのまま使う。新しい認証は作らない。

/** 1台あたりの呼び出し回数の上限（合図の総当たり対策） */
const RATE_LIMIT = 10
const RATE_WINDOW_MS = 60_000
/** 合図の見た目。gen_random_bytes(32) の16進なので64文字 */
const TOKEN_RE = /^[0-9a-f]{64}$/i

export interface ConnectEnv {
  supabaseUrl?: string
  supabaseKey?: string
}

export interface ConnectRequest {
  token?: unknown
  /** どの端末から来たか。記録に残すだけで、判定には使わない */
  bridge_id?: unknown
}

export interface ConnectResult {
  status: number
  body: Record<string, unknown>
}

export function envFrom(source: Record<string, string | undefined>): ConnectEnv {
  return {
    supabaseUrl: (source.VITE_SUPABASE_URL || source.SUPABASE_URL || '').trim() || undefined,
    supabaseKey: (source.VITE_SUPABASE_ANON_KEY || source.SUPABASE_ANON_KEY || '').trim() || undefined,
  }
}

const hits = new Map<string, number[]>()

export function tooMany(key: string): boolean {
  const now = Date.now()
  const list = (hits.get(key) ?? []).filter((t) => now - t < RATE_WINDOW_MS)
  list.push(now)
  hits.set(key, list)
  return list.length > RATE_LIMIT
}

/** 記録に残してよい形。合図そのものはログにも応答にも出さない */
export function maskToken(token: string): string {
  return token.length <= 8 ? '****' : `${token.slice(0, 4)}…${token.slice(-4)}`
}

export async function handleConnect(
  req: ConnectRequest | null,
  env: ConnectEnv,
  clientKey: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ConnectResult> {
  const url = env.supabaseUrl
  const key = env.supabaseKey
  if (!url || !key || !url.startsWith('https://')) {
    return { status: 503, body: { error: 'NOT_CONFIGURED' } }
  }

  const token = typeof req?.token === 'string' ? req.token.trim() : ''
  if (!TOKEN_RE.test(token)) {
    return { status: 400, body: { error: 'INVALID_TOKEN' } }
  }
  if (tooMany(clientKey)) {
    return { status: 429, body: { error: 'BUSY' } }
  }

  let res: Response
  try {
    res = await fetchImpl(`${url}/rest/v1/rpc/connect_token_redeem`, {
      method: 'POST',
      headers: { apikey: key, authorization: `Bearer ${key}`, 'content-type': 'application/json' },
      body: JSON.stringify({ p_connect_token: token }),
    })
  } catch {
    return { status: 502, body: { error: 'UPSTREAM_UNAVAILABLE' } }
  }

  if (!res.ok) {
    // 「無い／切れた／使用済み」を区別して返さない（総当たりの手がかりにしない）
    return { status: 401, body: { error: 'INVALID_TOKEN' } }
  }

  const data = (await res.json().catch(() => null)) as { member_id?: string; can_trade?: boolean } | null
  if (!data?.member_id) {
    return { status: 401, body: { error: 'INVALID_TOKEN' } }
  }

  // 部屋の名前は会員ID。中継はこの部屋以外へ指令を流さない（既存のしくみ）
  return {
    status: 200,
    body: { ok: true, room: data.member_id, can_trade: data.can_trade !== false },
  }
}

export async function readJson(req: {
  on: (event: string, cb: (chunk?: unknown) => void) => void
}): Promise<ConnectRequest | null> {
  return await new Promise((resolve) => {
    let raw = ''
    req.on('data', (chunk) => {
      raw += String(chunk)
      if (raw.length > 8192) raw = raw.slice(0, 8192)
    })
    req.on('end', () => {
      try {
        resolve(JSON.parse(raw) as ConnectRequest)
      } catch {
        resolve(null)
      }
    })
    req.on('error', () => resolve(null))
  })
}
