// 研究員の受け答え（/api/chat）を、偽の Gemini と偽の Supabase を立てて確かめる。
// 鍵は要らない:  node --experimental-strip-types api/_lib/chat.test.mjs
//
// ここで守りたいこと:
//   * 会員でない人に AI を使わせない（鍵の踏み台にしない＝費用が漏れない）
//   * 止められた会員（suspended）を通さない
//   * 担当外は調べずに案内だけ返す（＝余計な費用を使わない）
//   * 長すぎる質問・手元のデータを、そのまま AI に流さない
import { createServer } from 'node:http'
import { handleChat, envFrom, bearerOf } from './chat.ts'

let pass = 0
let fail = 0
function check(name, ok, detail = '') {
  if (ok) {
    pass++
    console.log(`  ok   ${name}`)
  } else {
    fail++
    console.log(`  NG   ${name}${detail ? `  … ${detail}` : ''}`)
  }
}

// ── 偽の Gemini ──
let reply = { answer: 'いまは三角持ち合いです。', redirect: 'none' }
let seen = null
let calls = 0
const gemini = createServer((req, res) => {
  let body = ''
  req.on('data', (c) => (body += c))
  req.on('end', () => {
    calls++
    seen = { url: req.url, body: JSON.parse(body) }
    res.setHeader('content-type', 'application/json')
    if (reply.status && reply.status !== 200) {
      res.statusCode = reply.status
      res.end(JSON.stringify({ error: { message: 'nope' } }))
      return
    }
    res.end(
      JSON.stringify({
        candidates: [{ content: { parts: [{ text: reply.raw ?? JSON.stringify(reply) }] } }],
      }),
    )
  })
})
await new Promise((r) => gemini.listen(0, r))

// ── 偽の Supabase（auth_me だけ）──
let member = { member: { status: 'active' } }
let authCalls = 0
const supabase = createServer((req, res) => {
  let body = ''
  req.on('data', (c) => (body += c))
  req.on('end', () => {
    authCalls++
    const token = JSON.parse(body || '{}').p_token
    res.setHeader('content-type', 'application/json')
    if (token === 'ng') {
      res.statusCode = 401
      res.end(JSON.stringify({ message: 'SESSION_EXPIRED' }))
      return
    }
    res.end(JSON.stringify(member))
  })
})
await new Promise((r) => supabase.listen(0, r))

const env = {
  geminiKey: 'test-key',
  geminiBase: `http://127.0.0.1:${gemini.address().port}/v1beta`,
  model: 'gemini-3.5-flash-lite',
  supabaseUrl: `https://127.0.0.1:${supabase.address().port}`,
  supabaseKey: 'anon',
}
// verifyMember は https:// で始まる URL しか見に行かない（本番の取り違え防止）。
// 試験では平文で立てているので、fetch だけ差し替えて偽 Supabase に向ける。
const realFetch = globalThis.fetch
globalThis.fetch = (url, init) =>
  realFetch(String(url).replace(`https://127.0.0.1:${supabase.address().port}`, `http://127.0.0.1:${supabase.address().port}`), init)

const ask = (over = {}, token = 'token-1', e = env) =>
  handleChat({ role: 'rin', question: 'いまのゴールドの形は？', context: { price: 3320 }, ...over }, token, e)

console.log('── 会員でない人に使わせない')

let r = await ask({}, null)
check('合言葉（セッション）が無ければ401', r.status === 401 && r.body.error === 'UNAUTHORIZED', JSON.stringify(r))
check('そのとき AI は呼ばない', calls === 0, String(calls))

r = await ask({}, 'ng')
check('セッションが切れていれば401', r.status === 401, JSON.stringify(r))

member = { member: { status: 'suspended' } }
r = await ask({}, 'token-suspended')
check('止められた会員は401', r.status === 401, JSON.stringify(r))
member = { member: { status: 'active' } }

console.log('\n── ふつうの受け答え')

r = await ask({}, 'token-1')
check('答えが返る', r.status === 200 && r.body.answer.includes('三角'), JSON.stringify(r.body))
check('AI を1回だけ呼ぶ', calls === 1, String(calls))
check('指定したモデルに聞く', seen.url.includes('gemini-3.5-flash-lite'), seen.url)
check('手元のデータを本文に載せる', seen.body.contents[0].parts[0].text.includes('3320'), seen.body.contents[0].parts[0].text.slice(0, 120))
check('出力の上限を付ける（費用の歯止め）', seen.body.generationConfig.maxOutputTokens > 0, JSON.stringify(seen.body.generationConfig))
check('担当（リン）として名乗らせる', seen.body.systemInstruction.parts[0].text.includes('リン'), seen.body.systemInstruction.parts[0].text.slice(0, 80))

const before = authCalls
await ask({}, 'token-1')
check('同じ人の確認は覚えておく（Supabase を毎回叩かない）', authCalls === before, `${before} → ${authCalls}`)

console.log('\n── 担当外は調べずに案内だけ')

reply = { answer: '', redirect: 'jin' }
r = await ask({ question: '次の雇用統計はいつ？' }, 'token-1')
check('案内先を返す', r.status === 200 && r.body.redirect === 'jin', JSON.stringify(r.body))

reply = { answer: 'これはわたしの担当です', redirect: 'rin' }
r = await ask({}, 'token-1')
check('自分あての案内は消す', r.body.redirect === null, JSON.stringify(r.body))

reply = { answer: '', redirect: 'none' }
r = await ask({}, 'token-1')
check('空で返ってきたら一言添える', r.body.answer.length > 0 && r.body.redirect === null, JSON.stringify(r.body))
reply = { answer: 'ふつうの答え', redirect: 'none' }

console.log('\n── 入力の上限と、おかしな指定')

r = await handleChat({ role: 'nazo', question: 'x' }, 'token-1', env)
check('知らない担当は400', r.status === 400, JSON.stringify(r))

r = await handleChat({ role: 'rin', question: '   ' }, 'token-1', env)
check('空の質問は400', r.status === 400, JSON.stringify(r))

await ask({ question: 'あ'.repeat(5000), context: 'い'.repeat(50000) }, 'token-1')
const sent = seen.body.contents[0].parts[0].text
check('長すぎる質問は切り詰める', sent.length < 12000, String(sent.length))

console.log('\n── 鍵と外部の故障')

r = await handleChat({ role: 'rin', question: 'x' }, 'token-1', { ...env, geminiKey: '' })
check('鍵が無ければ503（定型文に落ちる合図）', r.status === 503 && r.body.error === 'NOT_CONFIGURED', JSON.stringify(r))

reply = { status: 500 }
r = await ask({}, 'token-1')
check('AI が落ちていたら502', r.status === 502, JSON.stringify(r))
reply = { answer: 'ふつうの答え', redirect: 'none' }

reply = { raw: 'JSONではない生の文章' }
r = await ask({}, 'token-1')
check('JSON で返ってこなくても本文を答えにする', r.status === 200 && r.body.answer.includes('生の文章'), JSON.stringify(r.body))
reply = { answer: 'ふつうの答え', redirect: 'none' }

console.log('\n── 連打を止める')

let busy = null
for (let i = 0; i < 25; i++) {
  const res = await ask({}, 'token-renda')
  if (res.status === 429) {
    busy = i
    break
  }
}
check('同じ人が連打したら429で止める', busy !== null && busy <= 21, String(busy))

console.log('\n── 設定の読み取り')

const e = envFrom({ GEMINI_API_KEY: ' k ', GEMINI_CHAT_MODEL: 'x', VITE_SUPABASE_URL: 'https://a.co', VITE_SUPABASE_ANON_KEY: 'z' })
check('環境変数の前後の空白を落とす', e.geminiKey === 'k' && e.model === 'x', JSON.stringify(e))
check('Supabase の設定も拾う', e.supabaseUrl === 'https://a.co' && e.supabaseKey === 'z', JSON.stringify(e))
check('Bearer から合言葉を取り出す', bearerOf('Bearer  abc ') === 'abc', String(bearerOf('Bearer  abc ')))
check('Bearer でなければ取らない', bearerOf('abc') === null)

// Supabase の設定が無ければ、誰も通さない（＝Gemini の踏み台にされない）。
const noAuth = await handleChat({ role: 'rin', question: 'x' }, 'token-1', { ...env, supabaseUrl: '', supabaseKey: '' })
check('Supabase 未設定なら会員を確認できないので通さない', noAuth.status === 503, JSON.stringify(noAuth))

globalThis.fetch = realFetch
gemini.close()
supabase.close()
console.log(`\n${pass} ok / ${fail} NG`)
process.exit(fail ? 1 : 0)
