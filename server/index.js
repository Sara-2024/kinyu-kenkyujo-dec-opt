// トレラボ 中継サーバー
//
// ブラウザ（管理画面）と、MT5のそばで動くブリッジ(bridge.py)をつなぐ。
// 会員ごとに room を分け、他人の口座・指令が混ざらないようにする。
//
//   ブラウザ  ──/app?room=<会員ID>───┐
//                                    ├─ このサーバー ─→ 同じ部屋だけ中継
//   bridge.py ─/bridge?id=<会員ID>───┘
//
// 起動:  npm start          （既定 8080番）
//        PORT=9000 npm start

import { createServer } from 'node:http'
import { WebSocketServer } from 'ws'

const PORT = Number(process.env.PORT) || 8080
const TOKEN = (process.env.TRELAB_TOKEN || '').trim() // 空なら認証なし

// 会員の確認先（Supabase）。設定すると、画面は「ログイン中の会員本人」でないと
// 部屋に入れなくなる。設定しないと、部屋の名前（会員UUID）を知っている人は
// 誰でもその部屋に入れる＝他人の MT5 を操作できるので、本番では必ず設定する。
const SUPABASE_URL = (process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || '').trim().replace(/\/$/, '')
const SUPABASE_KEY = (process.env.SUPABASE_ANON_KEY || process.env.VITE_SUPABASE_ANON_KEY || '').trim()
const CHECK_MEMBERS = Boolean(SUPABASE_URL && SUPABASE_KEY)
/** 会員の確認を覚えておく時間。短くしないと、停止した会員がその間だけ操作できる */
const MEMBER_KEEP_MS = 60_000

/** 画面から受け付ける指令。ここに無いものはブリッジへ流さない */
const READ_COMMANDS = new Set(['get_status', 'status', 'get_positions', 'positions', 'get_history', 'history', 'get_trades', 'trades', 'get_ai_gate', 'ping'])
/** 売買の状態を変える指令。`can_trade` が false の会員には通さない */
const WRITE_COMMANDS = new Set(['start_trading', 'set_variable', 'set_ai_gate'])
/** 止める操作だけは、売買を禁止された会員にも許す（安全側にしか動かないため） */
const STOP_COMMANDS = new Set(['stop_trading'])

/** token → { at, member } */
const members = new Map()

/**
 * セッションの合言葉から会員を引く。画面と同じ RPC（auth_me）を使う。
 * 失効・停止はここで弾かれる（Supabase 側が見てくれる）。
 */
async function memberOf(token) {
  if (!token) return null
  const seen = members.get(token)
  if (seen && Date.now() - seen.at < MEMBER_KEEP_MS) return seen.member
  try {
    const res = await fetch(`${SUPABASE_URL}/rest/v1/rpc/auth_me`, {
      method: 'POST',
      headers: { apikey: SUPABASE_KEY, authorization: `Bearer ${SUPABASE_KEY}`, 'content-type': 'application/json' },
      body: JSON.stringify({ p_token: token }),
    })
    if (!res.ok) return null
    const data = await res.json()
    const member = data?.member
    if (!member?.id || member.status === 'suspended') return null
    if (members.size > 5000) {
      const now = Date.now()
      for (const [k, v] of members) if (now - v.at >= MEMBER_KEEP_MS) members.delete(k)
    }
    members.set(token, { at: Date.now(), member })
    return member
  } catch (err) {
    log(`会員を確認できませんでした: ${err.message}`)
    return null
  }
}
const ROOM_RE = /^[A-Za-z0-9._:-]{1,80}$/
// 画面が入れる部屋は会員ID（UUID）だけ。名前を当てて他の部屋に入れないようにする。
const MEMBER_ROOM_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** roomId → { bridge, apps, status } */
const rooms = new Map()

const now = () => new Date().toISOString().slice(11, 19)
const log = (...args) => console.log(`[${now()}]`, ...args)

/**
 * ログに残す用の短縮。部屋の名前は会員ID そのもので、
 * 認証を入れる前は「知っていれば入れる」合言葉でもあった。
 * Render のログは第三者の手にも渡りうるので、そのままは残さない。
 */
const short = (id) => (id ? `${String(id).slice(0, 8)}…` : '(なし)')
/** 口座番号は下4桁だけ */
const tail4 = (n) => (n == null || n === '' ? '?' : `…${String(n).slice(-4)}`)

function send(ws, message) {
  if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(message))
}

function normalizeRoom(raw) {
  const id = String(raw || '').trim()
  if (ROOM_RE.test(id)) return id
  return 'vps-01'
}

function roomOf(id) {
  if (!rooms.has(id)) rooms.set(id, { bridge: null, apps: new Set(), status: null, since: null })
  return rooms.get(id)
}

function pruneRoom(id) {
  const room = rooms.get(id)
  if (!room) return
  if (!room.bridge && room.apps.size === 0) rooms.delete(id)
}

function broadcastToRoom(roomId, message) {
  const room = rooms.get(roomId)
  if (!room) return
  for (const ws of room.apps) send(ws, message)
}

/**
 * その部屋の画面が何枚開いているかを、部屋のブリッジへ伝える。
 * 誰も見ていない間、ブリッジは口座の数字を送らなくてよい（無駄な通信を止める）。
 */
function notifyWatchers(roomId) {
  const room = rooms.get(roomId)
  if (!room || !room.bridge) return
  send(room.bridge, { type: 'apps', count: room.apps.size })
}

function roomIdFrom(req, url, isBridge) {
  if (isBridge) {
    return normalizeRoom(req.headers['x-bridge-id'] || url.searchParams.get('id') || url.searchParams.get('room'))
  }
  return normalizeRoom(url.searchParams.get('room') || url.searchParams.get('id'))
}

const server = createServer((req, res) => {
  if (req.url?.startsWith('/health')) {
    // 部屋の一覧（＝会員ID）は外に出さない。知っている部屋についてだけ答える。
    const url = new URL(req.url, `http://${req.headers.host}`)
    const asked = url.searchParams.get('room')
    const liveRooms = [...rooms.values()].filter((room) => room.bridge)
    const body = {
      ok: true,
      bridges: liveRooms.length,
      apps: [...rooms.values()].reduce((n, room) => n + room.apps.size, 0),
    }
    // 画面は、初回起動で既定の部屋に入ったブリッジを「いるか／いつ来たか」だけ見に来る。
    // 口座の中身は返さないので、どこからでも読める（CORS）。
    if (asked && ROOM_RE.test(asked)) {
      const room = rooms.get(asked)
      body.room = { id: asked, bridge: Boolean(room?.bridge), since: room?.bridge ? room.since : null }
    }
    res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' })
    res.end(JSON.stringify(body))
    return
  }
  res.writeHead(404)
  res.end('not found')
})

const wss = new WebSocketServer({ noServer: true })

server.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url, `http://${req.headers.host}`)
  const path = url.pathname

  if (path !== '/bridge' && path !== '/app') {
    socket.destroy()
    return
  }

  if (TOKEN) {
    const header = (req.headers.authorization || '').replace(/^Bearer\s+/i, '')
    const query = url.searchParams.get('token') || ''
    if (header !== TOKEN && query !== TOKEN) {
      log(`認証に失敗しました (${path})`)
      socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n')
      socket.destroy()
      return
    }
  }

  const isBridge = path === '/bridge'
  const roomId = roomIdFrom(req, url, isBridge)
  if (!isBridge && !MEMBER_ROOM_RE.test(roomId)) {
    log(`画面の部屋が会員IDではないので断りました: ${short(roomId)}`)
    socket.write('HTTP/1.1 403 Forbidden\r\n\r\n')
    socket.destroy()
    return
  }

  if (isBridge) {
    wss.handleUpgrade(req, socket, head, (ws) => handleBridge(ws, roomId))
    return
  }

  // 画面は「ログイン中の会員本人か」を確かめてから入れる。
  // 部屋の名前はクライアントの言い分ではなく、確かめた会員のIDを使う。
  if (!CHECK_MEMBERS) {
    wss.handleUpgrade(req, socket, head, (ws) => handleApp(ws, roomId, null))
    return
  }
  const sessionToken = url.searchParams.get('session') || ''
  memberOf(sessionToken).then((member) => {
    if (!member) {
      log(`会員を確認できないので断りました room=${short(roomId)}`)
      socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n')
      socket.destroy()
      return
    }
    if (String(member.id) !== roomId) {
      log(`他人の部屋に入ろうとしたので断りました room=${short(roomId)}`)
      socket.write('HTTP/1.1 403 Forbidden\r\n\r\n')
      socket.destroy()
      return
    }
    wss.handleUpgrade(req, socket, head, (ws) => handleApp(ws, String(member.id), member))
  })
})

function handleBridge(ws, roomId) {
  const room = roomOf(roomId)
  if (room.bridge && room.bridge !== ws) {
    log(`部屋 ${short(roomId)} のブリッジが再接続したため、古い接続を閉じます`)
    room.bridge.close(4001, 'replaced')
  }
  room.bridge = ws
  room.since = Date.now()
  log(`ブリッジ接続: ${short(roomId)}（現在 ${[...rooms.values()].filter((r) => r.bridge).length} 部屋）`)
  notifyWatchers(roomId)

  const ping = setInterval(() => {
    if (ws.readyState === ws.OPEN) ws.ping()
  }, 30000)

  ws.on('message', (raw) => {
    let payload
    try {
      payload = JSON.parse(raw.toString())
    } catch {
      log(`ブリッジ ${short(roomId)} から読めないデータ`)
      return
    }

    if (payload.type === 'hello') {
      room.status = payload
      log(`ブリッジ ${short(roomId)} 名乗り: 口座=${tail4(payload.account)} ${payload.server ?? ''}`)
      broadcastToRoom(roomId, { type: 'bridge_online', bridgeId: roomId, status: payload })
      return
    }

    if (payload.type === 'status_update') {
      room.status = { ...(room.status ?? {}), ...payload }
      log(`ブリッジ ${short(roomId)} 口座更新: 口座=${tail4(payload.account)} ${payload.server ?? ''}`)
      broadcastToRoom(roomId, { type: 'bridge_status', bridgeId: roomId, status: room.status })
      return
    }

    if (payload.type === 'ack') {
      // set_variable の応答の value は「書き込んだ変数の読み返し」で、
      // 売買フラグ（status.value）ではない。混ぜると、あとから開いた画面が
      // ロット値を稼働状態として受け取ってしまう（welcome に room.status を載せるため）。
      const { value, ...rest } = payload
      const isVariableAck = payload.command === 'set_variable' || typeof payload.name === 'string'
      room.status = { ...(room.status ?? {}), ...(isVariableAck ? rest : payload) }
      log(`ブリッジ ${short(roomId)} 応答: ${payload.command} ok=${payload.ok} value=${value}`)
    }
    broadcastToRoom(roomId, { ...payload, bridgeId: roomId })
  })

  const drop = (code) => {
    clearInterval(ping)
    if (room.bridge === ws) {
      room.bridge = null
      room.since = null
      log(`ブリッジ切断: ${short(roomId)} code=${code ?? ''}`)
      broadcastToRoom(roomId, { type: 'bridge_offline', bridgeId: roomId })
      pruneRoom(roomId)
    }
  }
  ws.on('close', (code) => drop(code))
  ws.on('error', (err) => log(`ブリッジ ${short(roomId)} エラー: ${err.message}`))
}

function handleApp(ws, roomId, member) {
  const room = roomOf(roomId)
  room.apps.add(ws)
  log(`画面が接続しました room=${short(roomId)}（この部屋 ${room.apps.size} 画面）`)
  notifyWatchers(roomId)

  send(ws, {
    type: 'welcome',
    room: roomId,
    bridges: room.bridge ? [{ bridgeId: roomId, online: true, ...(room.status ?? {}) }] : [],
  })

  ws.on('message', (raw) => {
    let payload
    try {
      payload = JSON.parse(raw.toString())
    } catch {
      return
    }

    const command = String(payload.command ?? '')
    const refuse = (error) => send(ws, { type: 'ack', command, id: payload.id, ok: false, error })

    // 知らない指令はブリッジへ流さない（ブリッジは届いた指令をそのまま実行する）
    if (!READ_COMMANDS.has(command) && !WRITE_COMMANDS.has(command) && !STOP_COMMANDS.has(command)) {
      log(`知らない指令を止めました room=${short(roomId)}: ${command.slice(0, 40)}`)
      refuse('この操作はできません')
      return
    }
    // 管理画面で「売買を止める」にした会員は、稼働・設定変更を通さない。
    // 画面のボタンを消すだけでは、中継に直接つないだ相手を止められない。
    if (member && member.can_trade === false && WRITE_COMMANDS.has(command)) {
      log(`売買を止めている会員の操作を断りました room=${short(roomId)}: ${command}`)
      refuse('この口座では自動売買の操作ができません。運営にお問い合わせください')
      return
    }

    const target = room.bridge
    if (!target) {
      refuse('ブリッジがつながっていません')
      return
    }

    log(`画面 → 部屋 ${short(roomId)}: ${command} ${payload.name ?? ''} ${payload.value ?? ''}`)
    send(target, { ...payload, bridgeId: roomId })
  })

  const drop = () => {
    room.apps.delete(ws)
    log(`画面が切断しました room=${short(roomId)}（残り ${room.apps.size} 画面）`)
    notifyWatchers(roomId)
    pruneRoom(roomId)
  }
  ws.on('close', drop)
  ws.on('error', drop)
}

server.listen(PORT, () => {
  log('='.repeat(56))
  log(`トレラボ中継サーバー 起動  ポート ${PORT}`)
  log(`  ブリッジ用 : ws://localhost:${PORT}/bridge`)
  log(`  画面用     : ws://localhost:${PORT}/app?room=<会員ID>`)
  log(`  死活確認   : http://localhost:${PORT}/health`)
  log(TOKEN ? '  合言葉     : 有効' : '  合言葉     : なし')
  if (CHECK_MEMBERS) {
    log('  会員の確認 : 有効（ログイン中の本人だけが自分の部屋に入れます）')
  } else {
    log('  会員の確認 : ★なし★ 部屋の名前（会員ID）を知っていれば誰でも入れます')
    log('               本番では SUPABASE_URL と SUPABASE_ANON_KEY を設定してください')
  }
  log('='.repeat(56))
})
