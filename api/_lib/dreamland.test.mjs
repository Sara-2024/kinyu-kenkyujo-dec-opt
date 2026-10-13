// ドリームランドのロビーから届く MT5 口座の申込（/api/dreamland）の試験。
// Supabase もサイトも要らない。返事を身代わりにして、判断だけを見る。
//
// 実行: node --experimental-strip-types api/_lib/dreamland.test.mjs
import { clean, envFrom, handleDreamland, maskAccount, resetRate } from './dreamland.ts'

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
const GOOD = { account: 12345678, server: 'Exness-MT5Real8', password: 'p@ss-word', plan: 'first', consent: true, name: '山田', email: 'a@b.jp', platform: 'windows' }

function fakeSupabase(response, calls = []) {
  return async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) })
    return response
  }
}
const okRes = (extra = {}) => ({ ok: true, json: async () => ({ application_no: 'DL-004213', plan: 'first', submissions: 1, ...extra }) })
const ngRes = (text) => ({ ok: false, status: 400, text: async () => text })

// ── 正しい申込 ──────────────────────────────────
{
  const calls = []
  const r = await handleDreamland(GOOD, env, 'ip-1', fakeSupabase(okRes(), calls))
  check('正しい申込なら 200', r.status === 200, String(r.status))
  check('受付番号を返す', r.body.application_no === 'DL-004213', String(r.body.application_no))
  check('預かるのは dreamland_apply', String(calls[0]?.url).endsWith('/rpc/dreamland_apply'))
  check('口座番号は数で渡す', calls[0]?.body?.p_account === 12345678)
  check('パスワードはそのまま渡す（ここで伏せると預かれない）', calls[0]?.body?.p_password === 'p@ss-word')
  check('同意は true で渡す', calls[0]?.body?.p_consent === true)
  check('OS も渡す', calls[0]?.body?.p_platform === 'windows')
  check('応答にパスワードを含めない', !JSON.stringify(r.body).includes('p@ss-word'))
}

// ── 文字列の口座番号も受け付ける（フォームから来る形） ──
{
  const calls = []
  const r = await handleDreamland({ ...GOOD, account: ' 987654 ' }, env, 'ip-1b', fakeSupabase(okRes(), calls))
  check('文字列の口座番号は数にして渡す', r.status === 200 && calls[0]?.body?.p_account === 987654, String(calls[0]?.body?.p_account))
}

// ── 同意が無ければ預からない ──────────────────────
for (const [name, consent] of [['false', false], ['無い', undefined], ['文字列', 'true']]) {
  const calls = []
  const r = await handleDreamland({ ...GOOD, consent }, env, `ip-consent-${name}`, fakeSupabase(okRes(), calls))
  check(`同意が${name}なら 400 NO_CONSENT`, r.status === 400 && r.body.error === 'NO_CONSENT', JSON.stringify(r.body))
  check(`同意が${name}なら問い合わせない`, calls.length === 0)
}

// ── 形がおかしい入力は、問い合わせもしない ────────────
for (const [name, patch, code] of [
  ['口座番号が空', { account: '' }, 'BAD_ACCOUNT'],
  ['口座番号が文字', { account: 'abc' }, 'BAD_ACCOUNT'],
  ['口座番号が負', { account: -5 }, 'BAD_ACCOUNT'],
  ['口座番号が小数', { account: 1.5 }, 'BAD_ACCOUNT'],
  ['サーバーが空', { server: '  ' }, 'BAD_SERVER'],
  ['サーバーが長すぎ', { server: 'x'.repeat(81) }, 'BAD_SERVER'],
  ['パスワードが空', { password: '' }, 'BAD_PASSWORD'],
  ['パスワードが長すぎ', { password: 'x'.repeat(201) }, 'BAD_PASSWORD'],
  ['プランが無い', { plan: undefined }, 'BAD_PLAN'],
  ['プランが知らない名前', { plan: 'business' }, 'BAD_PLAN'],
  ['メールの形が違う', { email: 'not-an-email' }, 'BAD_EMAIL'],
]) {
  const calls = []
  const r = await handleDreamland({ ...GOOD, ...patch }, env, `ip-bad-${name}`, fakeSupabase(okRes(), calls))
  check(`${name}なら 400 ${code}`, r.status === 400 && r.body.error === code, JSON.stringify(r.body))
  check(`${name}なら問い合わせない`, calls.length === 0)
}
{
  const r = await handleDreamland(null, env, 'ip-null', fakeSupabase(okRes()))
  check('中身が無ければ 400', r.status === 400, String(r.status))
}

// ── 任意の項目は無くてもよい ────────────────────────
{
  const calls = []
  const r = await handleDreamland({ account: 1, server: 'S', password: 'p', plan: 'crystal', consent: true }, env, 'ip-min', fakeSupabase(okRes({ plan: 'crystal' }), calls))
  check('名前・メール・OS が無くても 200', r.status === 200, String(r.status))
  check('無い項目は空で渡す', calls[0]?.body?.p_name === '' && calls[0]?.body?.p_email === '' && calls[0]?.body?.p_platform === null)
  check('知らない OS は null', clean({ ...GOOD, platform: 'linux' }).value?.platform === null)
}

// ── Supabase が断ったら、理由コードだけ通す ──────────
{
  const r = await handleDreamland(GOOD, env, 'ip-2', fakeSupabase(ngRes('{"message":"BAD_SERVER"}')))
  check('Supabase の BAD_SERVER は 400 で返す', r.status === 400 && r.body.error === 'BAD_SERVER', JSON.stringify(r.body))
  const r2 = await handleDreamland(GOOD, env, 'ip-2b', fakeSupabase(ngRes('{"message":"Could not find the function public.dreamland_apply"}')))
  check('関数が無い（migration 未適用）なら 502 で理由は伏せる', r2.status === 502 && r2.body.error === 'UPSTREAM_ERROR', JSON.stringify(r2.body))
  const r3 = await handleDreamland(GOOD, env, 'ip-2c', async () => { throw new Error('down') })
  check('Supabase に届かなければ 502', r3.status === 502 && r3.body.error === 'UPSTREAM_UNAVAILABLE', JSON.stringify(r3.body))
  const r4 = await handleDreamland(GOOD, env, 'ip-2d', fakeSupabase({ ok: true, json: async () => ({}) }))
  check('受付番号が返ってこなければ 502', r4.status === 502, String(r4.status))
}

// ── 鍵が無ければ 503（問い合わせない） ───────────────
{
  const calls = []
  const r = await handleDreamland(GOOD, {}, 'ip-3', fakeSupabase(okRes(), calls))
  check('鍵が無ければ 503', r.status === 503 && r.body.error === 'NOT_CONFIGURED', JSON.stringify(r.body))
  check('鍵が無ければ問い合わせない', calls.length === 0)
  const r2 = await handleDreamland(GOOD, { supabaseUrl: 'http://insecure', supabaseKey: 'k' }, 'ip-3b', fakeSupabase(okRes(), calls))
  check('https でなければ 503', r2.status === 503)
}

// ── 叩きすぎは 429 ──────────────────────────────
{
  resetRate()
  let last
  for (let i = 0; i < 7; i += 1) last = await handleDreamland(GOOD, env, 'ip-rate', fakeSupabase(okRes()))
  check('7回目は 429', last.status === 429 && last.body.error === 'BUSY', String(last.status))
  const other = await handleDreamland(GOOD, env, 'ip-rate-other', fakeSupabase(okRes()))
  check('別の端末は数えない', other.status === 200)
}

// ── 環境変数の読み方 ────────────────────────────
{
  const e = envFrom({ VITE_SUPABASE_URL: ' https://x.supabase.co ', VITE_SUPABASE_ANON_KEY: 'k', DREAMLAND_ORIGIN: 'https://lobby.example' })
  check('VITE_ の環境変数を使う', e.supabaseUrl === 'https://x.supabase.co' && e.supabaseKey === 'k')
  check('ロビーのドメインを読む', e.allowOrigin === 'https://lobby.example')
  const e2 = envFrom({ SUPABASE_URL: 'https://y.supabase.co', SUPABASE_ANON_KEY: 'k2' })
  check('SUPABASE_ でも読める', e2.supabaseUrl === 'https://y.supabase.co' && e2.allowOrigin === undefined)
}

// ── 記録に残す形 ────────────────────────────────
{
  check('口座番号は下2桁だけ残す', maskAccount(12345678) === '******78', maskAccount(12345678))
  check('短い番号は全部伏せる', maskAccount(5) === '**')
}

console.log(`\n${PASS} ok / ${FAIL} NG`)
process.exit(FAIL ? 1 : 0)
