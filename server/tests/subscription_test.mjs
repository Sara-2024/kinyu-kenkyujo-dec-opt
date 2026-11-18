// Yumekku【サブスク版】の利用許可を配る係（server/subscription.js）の試験。Supabase もブリッジも身代わり。
//
//   node server/tests/subscription_test.mjs
import { createSubscriptions } from '../subscription.js'

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

const SUB = '11111111-1111-4111-8111-111111111111'   // サブスクの会員
const FIRST = '22222222-2222-4222-8222-222222222222' // ファーストクラス（DB は返さない）
const UUID = /^[0-9a-f-]{36}$/

let answer = []
let down = false
const asked = []
const fetchImpl = async (url, init) => {
  asked.push({ url, body: JSON.parse(init.body) })
  if (down) throw new Error('down')
  return { ok: true, json: async () => answer.filter((r) => JSON.parse(init.body).p_ids.includes(r.id)) }
}
const bridgeSub = { name: 'sub', got: [] }
const bridgeFirst = { name: 'first', got: [] }
const rooms = new Map([
  [SUB, { bridge: bridgeSub }],
  [FIRST, { bridge: bridgeFirst }],
  ['vps-01', { bridge: { got: [] } }],
])
const subs = createSubscriptions({
  rooms,
  send: (ws, m) => ws.got.push(m),
  log: () => {},
  isMemberRoom: (id) => UUID.test(id),
  supabaseUrl: 'https://x.supabase.co',
  supabaseKey: 'anon',
  fetchImpl,
})

// 審査中：期限 0 を渡す。稼働は断る
answer = [{ id: SUB, status: 'pending', until: 0, sig: 0 }]
await subs.applyRoom(SUB)
check('名乗った部屋に許可を渡す（審査中は期限 0）', bridgeSub.got.at(-1)?.type === 'license' && bridgeSub.got.at(-1)?.until === 0)
check('審査中は稼働・設定変更を断る', subs.allowsWrite(SUB) === false)
check('サブスクでない部屋は止めない', subs.allowsWrite(FIRST) === true)
check('既定の部屋（vps-01）は DB に聞かない', !asked.some((a) => a.body.p_ids.includes('vps-01')))

// 承認：期限と署名が届く
answer = [{ id: SUB, status: 'active', until: 1800000000, sig: 123456789012 }]
await subs.sweep()
check('承認したら期限と署名が届く', bridgeSub.got.at(-1)?.until === 1800000000 && bridgeSub.got.at(-1)?.sig === 123456789012)
check('承認中は稼働を通す', subs.allowsWrite(SUB) === true)
check('サブスクでない会員のパスポートには何も送らない', bridgeFirst.got.length === 0)

// 変わらなければ送らない
const before = bridgeSub.got.length
await subs.sweep()
check('同じ許可は送り直さない', bridgeSub.got.length === before)

// DB に届かない：何も変えない
down = true
await subs.sweep()
check('DB に届かないときは何も送らない（手元の期限まで動く）', bridgeSub.got.length === before && subs.allowsWrite(SUB) === true)
down = false

// 停止：期限 0 がすぐ届く
answer = [{ id: SUB, status: 'stopped', until: 0, sig: 0 }]
await subs.sweep()
check('停止したら期限 0 が届く', bridgeSub.got.at(-1)?.until === 0 && bridgeSub.got.at(-1)?.status === 'stopped')
check('停止中は稼働を断る', subs.allowsWrite(SUB) === false)

// 名乗り直したら（ブリッジが作り直された）同じ内容でも渡す
const n = bridgeSub.got.length
await subs.applyRoom(SUB)
check('名乗り直したら同じ許可でも渡し直す', bridgeSub.got.length === n + 1)

console.log(`\n${pass} ok / ${fail} NG`)
process.exit(fail ? 1 : 0)
