// 中継サーバーの通し試験。本物の index.js を起動して、本物の WebSocket で確かめる。
//
//   node server/tests/relay_test.mjs
//
// いちばん大事なのは「会員ごとの部屋が本当に分かれているか」。
// ここが崩れると、他人の MT5 が動く・他人の口座が見える、という事故になる。
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
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
const replacedP = new Promise((resolve) => {
  bridgeA.on('close', (code) => resolve(code))
  setTimeout(() => resolve(0), 1500)
})
// 同じ口座から名乗れば「同じ PC の繋ぎ直し」。古いほうを閉じて新しいほうに入れ替える
bridgeA2.send_({ type: 'hello', account: 987654321, server: 'Demo', balance: 1234, value: 1 })
const replaced = await replacedP
check('同じ口座のブリッジが来たら、古いほうを閉じて入れ替える', replaced === 4001, String(replaced))

bridgeA2.send_({ type: 'status_update', account: 987654321, balance: 1234 })
const afterSwap = await appA.nextWhere((m) => m.type === 'bridge_status')
check('入れ替わったあとも同じ部屋に流れる', afterSwap?.status?.balance === 1234, JSON.stringify(afterSwap))

// 別の口座のブリッジが同じ部屋に来ても、動いているほうは守る（追い出し合いを止める）
const intruder = track(await open(bridge(A)))
const intruderClosed = new Promise((resolve) => {
  intruder.on('close', (code) => resolve(code))
  setTimeout(() => resolve(0), 1500)
})
intruder.send_({ type: 'hello', account: 111222333, server: 'Other', balance: 1, value: 1 })
check('★ 別の口座のブリッジは断る（4002）', (await intruderClosed) === 4002)
check('動いていたブリッジは閉じられていない', bridgeA2.readyState === WebSocket.OPEN)
bridgeA2.send_({ type: 'status_update', account: 987654321, balance: 1235 })
const stillA2 = await appA.nextWhere((m) => m.type === 'bridge_status' && m.status?.balance === 1235)
check('部屋は元のブリッジのまま', stillA2?.status?.account === 987654321, JSON.stringify(stillA2))

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

console.log('\n── 会員の確認（部屋の名前を知っていても、本人でなければ入れない）')

// 偽の Supabase。auth_me だけ答える
const sessions = {
  'session-A': { id: A, status: 'active', can_trade: true },
  'session-B': { id: B, status: 'active', can_trade: true },
  'session-admin': { id: '99999999-9999-4999-8999-999999999999', status: 'active', can_trade: true, role: 'admin' },
  'session-stopped': { id: A, status: 'active', can_trade: false },
  'session-suspended': { id: A, status: 'suspended', can_trade: true },
}
// 「一斉停止を受け付けない」と決めた会員／BAN 中の会員（試験の途中で入れ替える）
let refusing = []
let blocked = []
const supabase = createServer((req, res) => {
  let body = ''
  req.on('data', (c) => (body += c))
  req.on('end', () => {
    const token = JSON.parse(body || '{}').p_token
    res.setHeader('content-type', 'application/json')
    if (String(req.url).includes('bridges_blocked')) {
      // 渡された会員IDのうち、BAN 中のものだけ返す（本物の DB と同じ形）
      const ids = JSON.parse(body || '{}').p_ids ?? []
      res.end(JSON.stringify(ids.filter((id) => blocked.includes(id))))
      return
    }
    if (String(req.url).includes('fleet_optouts')) {
      res.end(JSON.stringify(sessions[token]?.role === 'admin' ? refusing : []))
      return
    }
    const member = sessions[token]
    if (!member) {
      res.statusCode = 401
      res.end(JSON.stringify({ message: 'SESSION_EXPIRED' }))
      return
    }
    res.end(JSON.stringify({ member }))
  })
})
await new Promise((r) => supabase.listen(0, r))

const checked = await startRelayOnFreePort({
  BLOCK_SWEEP_MS: '300', // BAN の見回りを速くする（本番は 60 秒）
  SUPABASE_URL: `http://127.0.0.1:${supabase.address().port}`,
  SUPABASE_ANON_KEY: 'anon',
})
const capp = (room, session) => `ws://127.0.0.1:${checked.port}/app?room=${room}${session ? `&session=${session}` : ''}`

let denied = ''
try {
  await open(capp(A))
} catch (err) {
  denied = String(err.message)
}
check('合言葉（セッション）が無ければ入れない', denied.includes('401'), denied)

denied = ''
try {
  await open(capp(A, 'session-B'))
} catch (err) {
  denied = String(err.message)
}
check('★ 他人の部屋のIDを知っていても、本人でなければ入れない', denied.includes('403'), denied)

denied = ''
try {
  await open(capp(A, 'session-suspended'))
} catch (err) {
  denied = String(err.message)
}
check('止められた会員（suspended）は入れない', denied.includes('401'), denied)

const mine = track(await open(capp(A, 'session-A')))
check('本人なら自分の部屋に入れる', mine.readyState === WebSocket.OPEN)
await mine.next()

// 売買を止めた会員は、稼働・設定変更を通さない（画面のボタンを消すだけでは足りない）
const stopped = track(await open(capp(A, 'session-stopped')))
await stopped.next()
stopped.send_({ id: 'n1', command: 'set_variable', name: 'AI_LOT', value: 3 })
const refusedAck = await stopped.nextWhere((m) => m.type === 'ack')
check('売買を止めた会員のロット変更は通さない', refusedAck?.ok === false, JSON.stringify(refusedAck))
stopped.send_({ id: 'n2', command: 'stop_trading' })
const stopAck = await stopped.nextWhere((m) => m.type === 'ack')
check('止める操作だけは通す（安全側なので）', stopAck?.error === 'ブリッジがつながっていません', JSON.stringify(stopAck))

// 知らない指令はブリッジへ流さない
mine.send_({ id: 'n3', command: 'shutdown_windows' })
const unknownAck = await mine.nextWhere((m) => m.type === 'ack')
check('知らない指令はブリッジへ流さない', unknownAck?.ok === false && unknownAck?.error === 'この操作はできません', JSON.stringify(unknownAck))

mine.close()
stopped.close()

console.log('\n── 一斉制御（管理者だけが、何部屋にも同じ指令を一度に流せる）')

const fleetUrl = (session) => `ws://127.0.0.1:${checked.port}/fleet${session ? `?session=${session}` : ''}`
const cbridge = (id) => `ws://127.0.0.1:${checked.port}/bridge?id=${id}`

denied = ''
try {
  await open(fleetUrl('session-A'))
} catch (err) {
  denied = String(err.message)
}
check('★ 一般の会員は一斉制御に入れない', denied.includes('403'), denied)
denied = ''
try {
  await open(fleetUrl(''))
} catch (err) {
  denied = String(err.message)
}
check('合言葉なしでは入れない', denied.includes('403'), denied)

// 会員A・Bのブリッジ（＝デモ口座2台）が居る。Cはまだ居ない
const C = '33333333-3333-4333-8333-333333333333'
const fbA = track(await open(cbridge(A)))
const fbB = track(await open(cbridge(B)))
fbA.send_({ type: 'hello', account: 111, server: 'Demo', balance: 10, value: 1 })
fbB.send_({ type: 'hello', account: 222, server: 'Demo', balance: 20, value: 1 })
await new Promise((r) => setTimeout(r, 200))

const fleet = track(await open(fleetUrl('session-admin')))
check('管理者は入れる', fleet.readyState === WebSocket.OPEN)

fleet.send_({ type: 'fleet_watch', id: 'w1', rooms: [A, B, C, 'not-a-room'] })
const snap = await fleet.nextWhere((m) => m.type === 'fleet_snapshot')
check('要約が部屋ごとに返る', snap?.rooms?.[A]?.online === true && snap?.rooms?.[B]?.online === true, JSON.stringify(snap))
check('居ない部屋は切断中として返る', snap?.rooms?.[C]?.online === false, JSON.stringify(snap?.rooms?.[C]))
check('会員IDの形でないものは無視する', !snap?.rooms?.['not-a-room'])
check('口座の数字は中継が覚えていたものが返る', snap?.rooms?.[A]?.status?.account === 111, JSON.stringify(snap?.rooms?.[A]))
fleet.send_({ type: 'fleet_watch', id: 'w1b', rooms: [C] })
const snapAll = await fleet.nextWhere((m) => m.type === 'fleet_snapshot' && m.id === 'w1b')
check(
  '頼んでいない部屋でも、つながっていれば要約に入る（登録前の口座を一覧に出すため）',
  snapAll?.rooms?.[A]?.online === true && snapAll?.rooms?.[B]?.online === true && snapAll?.rooms?.[C]?.online === false,
  JSON.stringify(Object.keys(snapAll?.rooms ?? {})),
)

// 見ているあいだは、ブリッジへ「画面が開いている」と伝わる（数字を送ってもらうため）
const appsA = await fbA.nextWhere((m) => m.type === 'apps' && m.count >= 1)
check('見ている部屋のブリッジに、画面が1枚あると伝わる', appsA?.count === 1, JSON.stringify(appsA))

// 一斉停止：居る部屋には届き、居ない部屋は預かる
fleet.send_({ type: 'fleet_send', id: 's1', command: 'stop_trading', rooms: [A, B, C] })
const sent = await fleet.nextWhere((m) => m.type === 'fleet_sent')
check('届いた部屋と預かった部屋が分かる', sent?.delivered?.length === 2 && sent?.waiting?.[0] === C, JSON.stringify(sent))
const toFA = await fbA.nextCommand()
const toFB = await fbB.nextCommand()
check('★ 1回の操作で、2台のブリッジに同じ停止が届く', toFA?.command === 'stop_trading' && toFB?.command === 'stop_trading', JSON.stringify([toFA, toFB]))

// 「受け付けない」と決めた会員（B）には流さない。画面が宛先に入れてきても中継が外す
refusing = [B]
fleet.send_({ type: 'fleet_send', id: 's1r', command: 'stop_trading', rooms: [A, B] })
const sentR = await fleet.nextWhere((m) => m.type === 'fleet_sent' && m.id === 's1r')
check(
  '★ 受け付けない会員の部屋には流さない（中継が外す）',
  sentR?.delivered?.length === 1 && sentR?.delivered?.[0] === A && sentR?.refused?.[0] === B,
  JSON.stringify(sentR),
)
const toFA2 = await fbA.nextCommand()
check('受け付ける部屋には届く', toFA2?.command === 'stop_trading' && toFA2?.id === 's1r', JSON.stringify(toFA2))
check('受け付けない部屋のブリッジには届かない', (await fbB.nextCommand(400)) === null)
refusing = []

// BAN した会員のブリッジは、つないでいても切られ、入り直せない
console.log('\n── BAN（管理者画面で止めた会員のブリッジは、中継が切る）')
const D = '44444444-4444-4444-8444-444444444444'
const fbD = track(await open(cbridge(D)))
fbD.send_({ type: 'hello', account: 444, server: 'Demo', balance: 1, value: 1 })
await new Promise((r) => setTimeout(r, 200))
blocked = [D]
const bannedCode = await new Promise((resolve) => {
  fbD.on('close', (code) => resolve(code))
  setTimeout(() => resolve(0), 2500)
})
check('★ BAN した会員のブリッジは見回りで切られる（4003）', bannedCode === 4003, String(bannedCode))
denied = ''
try {
  await open(cbridge(D))
} catch (err) {
  denied = String(err.message)
}
check('BAN 中は入り直せない', denied.includes('403'), denied)
blocked = []
const fbD2 = track(await open(cbridge(D)))
check('BAN を解くと入れる', fbD2.readyState === WebSocket.OPEN)
fbD2.close()

// 最初から BAN 中の会員（削除済みの会員の PC に、ブリッジだけ残っているとき）。
// 門前払い（HTTP 403）だとブリッジは「中継に繋がらない」としか分からず、60 秒おきに叩き直して
// そのたびにログが増える。最初の 1 回は WebSocket を開いてから 4003 で閉じ、ブリッジに
// 「利用を止められている」と伝えて自分から終了させる。
console.log('\n── BAN（最初から止まっている会員のブリッジは、4003 を伝えて終わらせる）')
const E = '55555555-5555-4555-8555-555555555555'
blocked = [E]
let firstKnock = null
try {
  const fbE = track(await open(cbridge(E)))
  firstKnock = await new Promise((resolve) => {
    fbE.on('close', (code) => resolve(code))
    setTimeout(() => resolve(0), 2500)
  })
} catch (err) {
  firstKnock = String(err.message)
}
check('★ 最初の 1 回は 4003（利用停止）で閉じる', firstKnock === 4003, String(firstKnock))
denied = ''
try {
  await open(cbridge(E))
} catch (err) {
  denied = String(err.message)
}
check('4003 を知らない古い版が叩き直しても、黙って 403（ログに残さない）', denied.includes('403'), denied)
blocked = []
const fbE2 = track(await open(cbridge(E)))
check('BAN を解いた瞬間に入れる（黙っているあいだも会員の確認はしている）', fbE2.readyState === WebSocket.OPEN)
fbE2.close()

// ブリッジの返事が、部屋つきで一斉制御の画面に届く
fbA.send_({ type: 'ack', id: 's1', command: 'stop_trading', ok: true, value: 0 })
const ackEv = await fleet.nextWhere((m) => m.type === 'fleet_event' && m.message?.type === 'ack')
check('返事はどの部屋のものか分かる', ackEv?.room === A && ackEv?.message?.ok === true, JSON.stringify(ackEv))

// 居なかった部屋Cのブリッジが名乗った瞬間、預かっていた停止が渡る
const fbC = track(await open(cbridge(C)))
fbC.send_({ type: 'hello', account: 333, server: 'Demo', value: 1 })
const late = await fbC.nextWhere((m) => m.command === 'stop_trading')
check('★ あとからつながった部屋にも、預かっていた停止が渡る', late?.command === 'stop_trading', JSON.stringify(late))

// 全決済も一斉制御から流せる。ロット変更などは流せない
fleet.send_({ type: 'fleet_send', id: 's2', command: 'close_all', rooms: [A] })
const toClose = await fbA.nextCommand()
check('全決済を流せる', toClose?.command === 'close_all', JSON.stringify(toClose))
fleet.send_({ type: 'fleet_send', id: 's2b', command: 'stop_system', rooms: [A] })
const toHalt = await fbA.nextCommand()
check('システム停止を流せる', toHalt?.command === 'stop_system', JSON.stringify(toHalt))
fleet.send_({ type: 'fleet_send', id: 's3', command: 'set_variable', name: 'AI_LOT', value: 9, rooms: [A] })
const refusedFleet = await fleet.nextWhere((m) => m.type === 'fleet_refused')
check('一斉制御からロット変更は流せない', Boolean(refusedFleet), JSON.stringify(refusedFleet))
check('断られた指令はブリッジに届かない', (await fbA.nextCommand(300)) === null)

fleet.close()
fbA.close()
fbB.close()
fbC.close()

// 会員の確認が無い中継では、一斉制御そのものが閉じている
const openRelay = await startRelayOnFreePort()
denied = ''
try {
  await open(`ws://127.0.0.1:${openRelay.port}/fleet?session=anything`)
} catch (err) {
  denied = String(err.message)
}
check('会員の確認が無い中継では一斉制御に入れない', denied.includes('403'), denied)
openRelay.proc.kill()

supabase.close()
checked.proc.kill()

console.log(`\n${pass} ok / ${fail} NG`)
process.exit(fail ? 1 : 0)
