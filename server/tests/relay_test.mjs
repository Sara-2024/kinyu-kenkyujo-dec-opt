// 中継サーバーの通し試験。本物の index.js を起動して、本物の WebSocket で確かめる。
//
//   node server/tests/relay_test.mjs
//
// いちばん大事なのは「会員ごとの部屋が本当に分かれているか」。
// ここが崩れると、他人の MT5 が動く・他人の口座が見える、という事故になる。
import { spawn } from 'node:child_process'
import { WebSocket } from 'ws'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const entry = join(here, '..', 'index.js')

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

const A = '11111111-1111-4111-8111-111111111111' // 会員A
const B = '22222222-2222-4222-8222-222222222222' // 会員B

/** 本物の中継を、他とぶつからないポートで起動する */
async function startRelayOnFreePort(env = {}) {
  const port = 18000 + Math.floor(Math.random() * 1000)
  const proc = spawn(process.execPath, [entry], { env: { ...process.env, PORT: String(port), ...env } })
  const ready = await new Promise((resolve) => {
    let out = ''
    proc.stdout.on('data', (c) => {
      out += c.toString()
      if (out.includes('起動')) resolve(true)
    })
    setTimeout(() => resolve(false), 5000)
  })
  if (!ready) {
    proc.kill()
    throw new Error('中継が起動しません')
  }
  return { proc, port }
}

/**
 * つないで、届いた通知を溜めておく。
 * `next()` は次の1通、`nextWhere(fn)` は条件に合う1通が来るまで待つ
 * （中継は画面の枚数 `apps` を随時流してくるので、指令を待つときは読み飛ばす必要がある）。
 */
function open(url, opts = {}) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url, opts)
    const inbox = []
    const waiters = []
    const deliver = (msg) => {
      const i = waiters.findIndex((w) => w.pred(msg))
      if (i >= 0) {
        const [w] = waiters.splice(i, 1)
        w.hit(msg)
      } else inbox.push(msg)
    }
    ws.on('message', (raw) => deliver(JSON.parse(raw.toString())))
    ws.nextWhere = (pred, ms = 1500) =>
      new Promise((res) => {
        const i = inbox.findIndex(pred)
        if (i >= 0) return res(inbox.splice(i, 1)[0])
        const entry = {
          pred,
          hit: (msg) => {
            clearTimeout(timer)
            res(msg)
          },
        }
        const timer = setTimeout(() => {
          const j = waiters.indexOf(entry)
          if (j >= 0) waiters.splice(j, 1)
          res(null)
        }, ms)
        waiters.push(entry)
      })
    ws.next = (ms = 1500) => ws.nextWhere(() => true, ms)
    /** 中継が随時流してくる「画面の枚数」を読み飛ばして待つ */
    ws.nextCommand = (ms = 1500) => ws.nextWhere((m) => m.type !== 'apps', ms)
    ws.send_ = (obj) => ws.send(JSON.stringify(obj))
    ws.on('open', () => resolve(ws))
    ws.on('unexpected-response', (_req, res) => reject(new Error(`HTTP ${res.statusCode}`)))
    ws.on('error', (err) => reject(err))
  })
}

const closed = []
function track(ws) {
  closed.push(ws)
  return ws
}

const { proc, port } = await startRelayOnFreePort()
const app = (room) => `ws://127.0.0.1:${port}/app?room=${room}`
const bridge = (id) => `ws://127.0.0.1:${port}/bridge?id=${id}`

console.log('── 部屋の分離（他人の MT5 が動かないこと）')

// 会員AとBが、それぞれ自分のブリッジと画面をつなぐ
const bridgeA = track(await open(bridge(A)))
const bridgeB = track(await open(bridge(B)))
const appA = track(await open(app(A)))
const appB = track(await open(app(B)))

await appA.next()
await appB.next()

bridgeA.send_({ type: 'hello', account: 987654321, server: 'BrokerA', balance: 1000 })
bridgeB.send_({ type: 'hello', account: 555000555, server: 'BrokerB', balance: 2000 })

const gotA = await appA.next()
const gotB = await appB.next()
check('Aの画面にはAの口座だけが届く', gotA?.status?.account === 987654321, JSON.stringify(gotA))
check('Bの画面にはBの口座だけが届く', gotB?.status?.account === 555000555, JSON.stringify(gotB))
check('Aの画面にBの口座は流れてこない', (await appA.next(400)) === null)

// Aの画面から「自動売買をはじめる」相当の指令
appA.send_({ id: 'x1', command: 'set_variable', name: 'AI_TRADING_ALLOWED', value: 1 })
const toA = await bridgeA.nextCommand()
check('Aの指令はAのブリッジに届く', toA?.command === 'set_variable' && toA?.value === 1, JSON.stringify(toA))
check('Aの指令はBのブリッジには届かない', (await bridgeB.nextCommand(400)) === null)

// 部屋を偽っても、届く先は接続した部屋のまま
appB.send_({ id: 'x2', command: 'set_variable', name: 'AI_TRADING_ALLOWED', value: 0, bridgeId: A })
const toB = await bridgeB.nextCommand()
check('bridgeId を書き換えても他人の部屋には届かない', toB?.command === 'set_variable' && toB?.bridgeId === B, JSON.stringify(toB))
check('偽装された宛先のブリッジ（A）は受け取らない', (await bridgeA.nextCommand(400)) === null)

console.log('\n── 部屋の名前を当てられないこと')

let refused = ''
try {
  await open(`ws://127.0.0.1:${port}/app?room=vps-01`)
} catch (err) {
  refused = String(err.message)
}
check('会員IDでない部屋に画面は入れない（既定の部屋も不可）', refused.includes('403'), refused)

refused = ''
try {
  await open(`ws://127.0.0.1:${port}/app?room=${A.toUpperCase()}xx`)
} catch (err) {
  refused = String(err.message)
}
check('UUIDに似せた文字列でも入れない', refused.includes('403'), refused)

refused = ''
try {
  await open(`ws://127.0.0.1:${port}/somewhere?room=${A}`)
} catch (err) {
  refused = String(err.message)
}
check('/app と /bridge 以外の入口は開かない', refused !== '', refused)

console.log('\n── 死活確認（/health）から中身が漏れないこと')

const health = await fetch(`http://127.0.0.1:${port}/health`).then((r) => r.json())
check('部屋の一覧（会員ID）を出さない', !JSON.stringify(health).includes(A), JSON.stringify(health))
check('つないでいる数だけを返す', health.bridges === 2 && health.apps === 2, JSON.stringify(health))

const asked = await fetch(`http://127.0.0.1:${port}/health?room=${A}`).then((r) => r.json())
check('聞かれた部屋は「居るか」だけ答える', asked.room?.bridge === true && typeof asked.room?.since === 'number', JSON.stringify(asked))
check('口座番号や残高は返さない', !JSON.stringify(asked).includes('987654321'), JSON.stringify(asked))

console.log('\n── ブリッジの入れ替わり（二重起動の交代）')

const bridgeA2 = track(await open(bridge(A)))
const replaced = await new Promise((resolve) => {
  bridgeA.on('close', (code) => resolve(code))
  setTimeout(() => resolve(0), 1500)
})
check('同じ部屋に来た新しいブリッジが古いほうを閉じる', replaced === 4001, String(replaced))

bridgeA2.send_({ type: 'status_update', account: 987654321, balance: 1234 })
const afterSwap = await appA.nextWhere((m) => m.type === 'bridge_status')
check('入れ替わったあとも同じ部屋に流れる', afterSwap?.status?.balance === 1234, JSON.stringify(afterSwap))

console.log('\n── 画面の枚数がブリッジに伝わる（見ていない間は数字を送らない仕組み）')

const appA2 = track(await open(app(A)))
await appA2.next()
const appsMsg = await bridgeA2.nextWhere((m) => m.type === 'apps' && m.count === 2, 2000)
check('画面が増えたらブリッジに枚数が届く', appsMsg?.count === 2, JSON.stringify(appsMsg))

console.log('\n── ブリッジが落ちたとき')

bridgeB.close()
const offline = await appB.nextWhere((m) => m.type === 'bridge_offline', 2000)
check('同じ部屋の画面にだけ切断が伝わる', offline?.type === 'bridge_offline' && offline?.bridgeId === B, JSON.stringify(offline))
check('他の部屋の画面には伝わらない', (await appA.nextWhere((m) => m.type === 'bridge_offline', 400)) === null)

for (const ws of closed) {
  try {
    ws.close()
  } catch {}
}
proc.kill()

console.log('\n── 合言葉（TRELAB_TOKEN）を設定したとき')

const secured = await startRelayOnFreePort({ TRELAB_TOKEN: 'aikotoba' })
let deniedMsg = ''
try {
  await open(`ws://127.0.0.1:${secured.port}/app?room=${A}`)
} catch (err) {
  deniedMsg = String(err.message)
}
check('合言葉が無い接続は断られる', deniedMsg.includes('401'), deniedMsg)

const okWs = await open(`ws://127.0.0.1:${secured.port}/app?room=${A}&token=aikotoba`)
check('合言葉があれば入れる', okWs.readyState === WebSocket.OPEN)
okWs.close()
secured.proc.kill()

console.log(`\n${pass} ok / ${fail} NG`)
process.exit(fail ? 1 : 0)
