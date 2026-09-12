// MT5連携の合図（ワンタイム token）を確かめる所の試験。
// Supabase もサイトも要らない。返事を身代わりにして、判断だけを見る。
//
// 実行: node --experimental-strip-types api/_lib/connect.test.mjs
import { envFrom, handleConnect, maskToken } from './connect.ts'

let PASS = 0
let FAIL = 0
function check(name, cond, extra = '') {
  if (cond) {
    PASS += 1
    console.log(`  ok   ${name}`)
  } else {
    FAIL += 1
    console.log(`  NG   ${name} ${extra}`)
  }
}

const env = { supabaseUrl: 'https://example.supabase.co', supabaseKey: 'anon-key' }
const GOOD = 'a'.repeat(64)
const MEMBER = '11111111-2222-4333-8444-555555555555'

/** Supabase の身代わり。呼ばれた回数と中身も覚えておく */
function fakeSupabase(response, calls = []) {
  return async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) })
    return response
  }
}
const okRes = () => ({ ok: true, json: async () => ({ member_id: MEMBER, can_trade: true }) })
const ngRes = () => ({ ok: false, status: 400, text: async () => 'INVALID_TOKEN' })

// ── 正しい合図 ──────────────────────────────────
{
  const calls = []
  const r = await handleConnect({ token: GOOD }, env, 'ip-1', fakeSupabase(okRes(), calls))
  check('正しい合図なら 200', r.status === 200, String(r.status))
  check('部屋（会員ID）を返す', r.body.room === MEMBER, String(r.body.room))
  check('合図は Supabase へそのまま渡す', calls[0]?.body?.p_connect_token === GOOD)
  check('確かめるのは redeem の関数', String(calls[0]?.url).endsWith('/rpc/connect_token_redeem'))
}

// ── 形がおかしい合図は、問い合わせもしない ────────────
for (const [name, token] of [
  ['空', ''],
  ['短い', 'abc'],
  ['16進でない', 'z'.repeat(64)],
  ['長すぎ', 'a'.repeat(65)],
  ['文字列でない', 12345],
  ['無い', undefined],
]) {
  const calls = []
  const r = await handleConnect({ token }, env, `ip-bad-${name}`, fakeSupabase(okRes(), calls))
  check(`合図が${name}なら 400`, r.status === 400, String(r.status))
  check(`合図が${name}なら問い合わせない`, calls.length === 0)
}

// ── Supabase が断ったら 401。理由は返さない ──────────
{
  const r = await handleConnect({ token: GOOD }, env, 'ip-2', fakeSupabase(ngRes()))
  check('使えない合図は 401', r.status === 401, String(r.status))
  check('理由を細かく返さない', r.body.error === 'INVALID_TOKEN' && !('detail' in r.body))
}

// ── 返事に会員IDが無ければ通さない ──────────────────
{
  const empty = { ok: true, json: async () => ({}) }
  const r = await handleConnect({ token: GOOD }, env, 'ip-3', fakeSupabase(empty))
  check('会員IDが無ければ 401', r.status === 401, String(r.status))
}

// ── 設定が無ければ 503（黙って通さない）──────────────
{
  const r = await handleConnect({ token: GOOD }, {}, 'ip-4', fakeSupabase(okRes()))
  check('設定が無ければ 503', r.status === 503, String(r.status))
}
{
  const r = await handleConnect({ token: GOOD }, { supabaseUrl: 'http://x', supabaseKey: 'k' }, 'ip-5', fakeSupabase(okRes()))
  check('https でなければ 503', r.status === 503, String(r.status))
}

// ── 通信できないときは 502（合図は使われたことになる）──
{
  const boom = async () => {
    throw new Error('network')
  }
  const r = await handleConnect({ token: GOOD }, env, 'ip-6', boom)
  check('通信できなければ 502', r.status === 502, String(r.status))
}

// ── 総当たり対策。同じ相手からの連打は止める ─────────
{
  const calls = []
  const fetcher = fakeSupabase(ngRes(), calls)
  let last = 0
  for (let i = 0; i < 12; i++) {
    last = (await handleConnect({ token: GOOD }, env, 'ip-flood', fetcher)).status
  }
  check('連打は 429 で止まる', last === 429, String(last))
  check('止めた分は問い合わせない', calls.length <= 10, String(calls.length))
}

// ── 記録に合図そのものを残さない ────────────────────
{
  const masked = maskToken(GOOD)
  check('合図は伏せて記録する', !masked.includes(GOOD) && masked.length < 20, masked)
  check('短いものも伏せる', maskToken('abcd') === '****')
}

// ── 環境変数の読み取り ──────────────────────────
{
  const e = envFrom({ VITE_SUPABASE_URL: 'https://a.co ', VITE_SUPABASE_ANON_KEY: ' k ' })
  check('前後の空白を落とす', e.supabaseUrl === 'https://a.co' && e.supabaseKey === 'k')
  const none = envFrom({})
  check('未設定なら undefined', none.supabaseUrl === undefined)
}

console.log(`\n${PASS} ok / ${FAIL} NG`)
process.exit(FAIL ? 1 : 0)
