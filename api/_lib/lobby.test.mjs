// ロビーの窓口（/api/lobby）の試験。Supabase もサイトも要らない。返事を身代わりにして、判断だけを見る。
//
// 実行: node --experimental-strip-types api/_lib/lobby.test.mjs
import { clean, errorCodeOf, handleLobby, maskAccount, publicMember, resetRate } from './lobby.ts'

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
const SESSION = '12345678-1234-4234-8234-123456789abc'
const MEMBER_ID = 'abcdefab-1234-4234-8234-abcdefabcdef'
const MEMBER = { id: MEMBER_ID, account: 12345678, name: '山田', plan: 'crystal', role: 'user', status: 'active', can_trade: true, email: null }

function fakeSupabase(response, calls = []) {
  return async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) })
    return typeof response === 'function' ? response(url) : response
  }
}
const okRes = (json) => ({ ok: true, json: async () => json })
const ngRes = (text, status = 400) => ({ ok: false, status, text: async () => text })

// ── 合言葉 → プラン ─────────────────────────────
{
  const calls = []
  const r = await handleLobby({ action: 'plan', entry: ' royal-pass ' }, env, 'ip-plan', fakeSupabase(okRes({ plan: 'crystal' }), calls))
  check('合言葉が合えば 200 とプラン', r.status === 200 && r.body.plan === 'crystal', JSON.stringify(r.body))
  check('聞くのは plan_check', String(calls[0]?.url).endsWith('/rpc/plan_check'))
  check('合言葉は前後の空白を落として渡す', calls[0]?.body?.p_entry === 'royal-pass')
  check('応答に合言葉を含めない', !JSON.stringify(r.body).includes('royal-pass'))
}
{
  const r = await handleLobby({ action: 'plan', entry: 'wrong' }, env, 'ip-plan2', fakeSupabase(okRes({ plan: null })))
  check('合わなければ 401 BAD_ENTRY', r.status === 401 && r.body.error === 'BAD_ENTRY', JSON.stringify(r.body))
}
{
  const calls = []
  const r = await handleLobby({ action: 'plan', entry: '' }, env, 'ip-plan3', fakeSupabase(okRes({ plan: 'first' }), calls))
  check('空の合言葉は問い合わせない', r.status === 400 && calls.length === 0)
}

// ── 会員登録 ───────────────────────────────────
{
  const calls = []
  const r = await handleLobby(
    { action: 'register', account: ' 12345678 ', name: ' 山田 ', password: 'site-pass-1', entry: 'royal-pass' },
    env, 'ip-reg', fakeSupabase(okRes({ token: SESSION, member: MEMBER }), calls),
  )
  check('登録できれば 200', r.status === 200, JSON.stringify(r.body))
  check('呼ぶのは auth_register', String(calls[0]?.url).endsWith('/rpc/auth_register'))
  check('口座番号は数で、お名前は空白を落として渡す', calls[0]?.body?.p_account === 12345678 && calls[0]?.body?.p_name === '山田')
  check('合言葉は入場パスワードとして渡す', calls[0]?.body?.p_entry === 'royal-pass')
  check('セッションの合言葉を返す', r.body.session === SESSION)
  check('会員にはプランが付いている', r.body.member?.plan === 'crystal' && r.body.member?.id === MEMBER_ID)
  check('会員の中身は必要なところだけ（role・can_trade は返さない）', !('role' in r.body.member) && !('can_trade' in r.body.member))
}
{
  const calls = []
  const r = await handleLobby({ action: 'register', account: 1, name: '山田', password: 'short', entry: 'x' }, env, 'ip-reg2', fakeSupabase(okRes({}), calls))
  check('サイトのパスワードが8文字未満なら問い合わせない', r.status === 400 && r.body.error === 'WEAK_PASSWORD' && calls.length === 0)
}
{
  const r = await handleLobby({ action: 'register', account: 1, name: '山田', password: 'site-pass-1', entry: 'x' }, env, 'ip-reg3', fakeSupabase(ngRes('{"message":"ACCOUNT_TAKEN"}')))
  check('登録済みの口座なら 400 ACCOUNT_TAKEN', r.status === 400 && r.body.error === 'ACCOUNT_TAKEN', JSON.stringify(r.body))
}
{
  const r = await handleLobby({ action: 'register', account: 1, name: '山田', password: 'site-pass-1', entry: 'x' }, env, 'ip-reg4', fakeSupabase(ngRes('{"message":"BAD_ENTRY"}')))
  check('合言葉が違えば 401 BAD_ENTRY', r.status === 401 && r.body.error === 'BAD_ENTRY')
}

// ── ログイン ───────────────────────────────────
{
  const calls = []
  const r = await handleLobby({ action: 'login', account: '12345678', password: 'site-pass-1' }, env, 'ip-login', fakeSupabase(okRes({ token: SESSION, member: MEMBER }), calls))
  check('ログインできれば 200 とセッション', r.status === 200 && r.body.session === SESSION)
  check('呼ぶのは auth_login', String(calls[0]?.url).endsWith('/rpc/auth_login'))
}
{
  const r = await handleLobby({ action: 'login', account: 1, password: 'x' }, env, 'ip-login2', fakeSupabase(ngRes('{"message":"BAD_CREDENTIALS"}')))
  check('違えば 401 BAD_CREDENTIALS', r.status === 401 && r.body.error === 'BAD_CREDENTIALS')
}
{
  const r = await handleLobby({ action: 'login', account: 1, password: 'x' }, env, 'ip-login3', fakeSupabase(ngRes('{"message":"SUSPENDED"}')))
  check('止めている会員は 403', r.status === 403 && r.body.error === 'SUSPENDED')
}

// ── セッションが要るもの ─────────────────────────
{
  const calls = []
  const r = await handleLobby({ action: 'me', session: SESSION }, env, 'ip-me', fakeSupabase(okRes({ member: MEMBER }), calls))
  check('me は会員を返す', r.status === 200 && r.body.member?.plan === 'crystal')
  check('呼ぶのは auth_me', String(calls[0]?.url).endsWith('/rpc/auth_me') && calls[0]?.body?.p_token === SESSION)
}
{
  const calls = []
  const r = await handleLobby({ action: 'me', session: 'not-a-uuid' }, env, 'ip-me2', fakeSupabase(okRes({ member: MEMBER }), calls))
  check('セッションの形がおかしければ問い合わせない', r.status === 400 && r.body.error === 'NO_SESSION' && calls.length === 0)
}
{
  const r = await handleLobby({ action: 'me', session: SESSION }, env, 'ip-me3', fakeSupabase(ngRes('{"message":"SESSION_EXPIRED"}')))
  check('切れたセッションは 401', r.status === 401 && r.body.error === 'SESSION_EXPIRED')
}
{
  const calls = []
  const tok = 'a'.repeat(64)
  const r = await handleLobby({ action: 'connect_token', session: SESSION }, env, 'ip-ct', fakeSupabase(okRes({ token: tok, expires_in: 300 }), calls))
  check('接続の合図を返す', r.status === 200 && r.body.token === tok && r.body.expires_in === 300)
  check('呼ぶのは connect_token_issue', String(calls[0]?.url).endsWith('/rpc/connect_token_issue'))
}
{
  const r = await handleLobby({ action: 'connect_token', session: SESSION }, env, 'ip-ct2', fakeSupabase(okRes({ token: 'short' })))
  check('合図の形がおかしければ 502', r.status === 502)
}
{
  const calls = []
  const r = await handleLobby({ action: 'platform', session: SESSION, platform: 'mac' }, env, 'ip-pf', fakeSupabase(okRes({ ok: true }), calls))
  check('OS を記録できる', r.status === 200 && calls[0]?.body?.p_platform === 'mac')
  const r2 = await handleLobby({ action: 'platform', session: SESSION, platform: 'linux' }, env, 'ip-pf2', fakeSupabase(okRes({ ok: true })))
  check('知らない OS は 400', r2.status === 400 && r2.body.error === 'BAD_PLATFORM')
}

// ── 入口の守り ─────────────────────────────────
{
  const r = await handleLobby({ action: 'delete_everything' }, env, 'ip-act', fakeSupabase(okRes({})))
  check('知らない action は 400', r.status === 400 && r.body.error === 'BAD_ACTION')
  const r2 = await handleLobby(null, env, 'ip-null', fakeSupabase(okRes({})))
  check('壊れた JSON は 400', r2.status === 400)
  const r3 = await handleLobby({ action: 'plan', entry: 'x' }, { supabaseUrl: '', supabaseKey: '' }, 'ip-cfg', fakeSupabase(okRes({})))
  check('鍵が無ければ 503', r3.status === 503 && r3.body.error === 'NOT_CONFIGURED')
  const r4 = await handleLobby({ action: 'plan', entry: 'x' }, env, 'ip-down', async () => { throw new Error('down') })
  check('Supabase に届かなければ 502', r4.status === 502 && r4.body.error === 'UPSTREAM_UNAVAILABLE')
  const r5 = await handleLobby({ action: 'plan', entry: 'x' }, env, 'ip-500', fakeSupabase(ngRes('internal', 500)))
  check('知らない失敗は伏せて 502', r5.status === 502 && r5.body.error === 'UPSTREAM_ERROR')
}
{
  resetRate()
  let last = null
  for (let i = 0; i < 31; i += 1) {
    last = await handleLobby({ action: 'plan', entry: `guess-${i}` }, env, 'ip-burst', fakeSupabase(okRes({ plan: null })))
  }
  check('同じ端末から叩きすぎたら 429', last.status === 429 && last.body.error === 'BUSY')
  const other = await handleLobby({ action: 'plan', entry: 'x' }, env, 'ip-other', fakeSupabase(okRes({ plan: 'first' })))
  check('別の端末には効かない', other.status === 200)
}

// ── 小さな道具 ─────────────────────────────────
check('口座番号は下2桁だけ残す', maskAccount(12345678) === '******78' && maskAccount('') === '-' && maskAccount(undefined) === '-')
check('理由コードは知っているものだけ拾う', errorCodeOf('x BAD_ENTRY y') === 'BAD_ENTRY' && errorCodeOf('DROP TABLE') === null)
check('会員の JSON はプランが変でも落とさず null にする', publicMember({ id: MEMBER_ID, plan: 'gold' })?.plan === null)
check('clean: platform にセッションが無ければ NO_SESSION', clean({ action: 'platform', platform: 'mac' }).ok === false)

console.log(`\n${PASS} ok / ${FAIL} NG`)
process.exit(FAIL ? 1 : 0)
