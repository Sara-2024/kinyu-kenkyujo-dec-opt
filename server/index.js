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
const ROOM_RE = /^[A-Za-z0-9._:-]{1,80}$/

/** roomId → { bridge, apps, status } */
const rooms = new Map()

const now = () => new Date().toISOString().slice(11, 19)
const log = (...args) => console.log(`[${now()}]`, ...args)

function send(ws, message) {
  if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(message))
}

function normalizeRoom(raw) {
  const id = String(raw || '').trim()
  if (ROOM_RE.test(id)) return id
  return 'vps-01'
}

function roomOf(id) {
  if (!rooms.has(id)) rooms.set(id, { bridge: null, apps: new Set(), status: null })
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

function roomIdFrom(req, url, isBridge) {
  if (isBridge) {
    return normalizeRoom(req.headers['x-bridge-id'] || url.searchParams.get('id') || url.searchParams.get('room'))
  }
  return normalizeRoom(url.searchParams.get('room') || url.searchParams.get('id'))
}

const server = createServer((req, res) => {
  if (req.url?.startsWith('/health')) {
    const liveRooms = [...rooms.entries()].filter(([, room]) => room.bridge)
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(
      JSON.stringify({
        ok: true,
        bridges: liveRooms.length,
        apps: [...rooms.values()].reduce((n, room) => n + room.apps.size, 0),
        rooms: liveRooms.map(([id]) => id),
      }),
    )
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

  wss.handleUpgrade(req, socket, head, (ws) => {
    if (isBridge) handleBridge(ws, roomId)
    else handleApp(ws, roomId)
  })
})

function handleBridge(ws, roomId) {
  const room = roomOf(roomId)
  if (room.bridge && room.bridge !== ws) {
    log(`部屋 ${roomId} のブリッジが再接続したため、古い接続を閉じます`)
    room.bridge.close(4001, 'replaced')
  }
  room.bridge = ws
  log(`ブリッジ接続: ${roomId}（現在 ${[...rooms.values()].filter((r) => r.bridge).length} 部屋）`)

  const ping = setInterval(() => {
    if (ws.readyState === ws.OPEN) ws.ping()
  }, 30000)

  ws.on('message', (raw) => {
    let payload
    try {
      payload = JSON.parse(raw.toString())
    } catch {
      log(`ブリッジ ${roomId} から読めないデータ`)
      return
    }

    if (payload.type === 'hello') {
      room.status = payload
      log(`ブリッジ ${roomId} 名乗り: 口座=${payload.account} ${payload.server ?? ''}`)
      broadcastToRoom(roomId, { type: 'bridge_online', bridgeId: roomId, status: payload })
      return
    }

    if (payload.type === 'status_update') {
      room.status = { ...(room.status ?? {}), ...payload }
      log(`ブリッジ ${roomId} 口座更新: 口座=${payload.account} ${payload.server ?? ''}`)
      broadcastToRoom(roomId, { type: 'bridge_status', bridgeId: roomId, status: room.status })
      return
    }

    if (payload.type === 'ack') {
      room.status = { ...(room.status ?? {}), ...payload }
      log(`ブリッジ ${roomId} 応答: ${payload.command} ok=${payload.ok} value=${payload.value}`)
    }
    broadcastToRoom(roomId, { ...payload, bridgeId: roomId })
  })

  const drop = (code) => {
    clearInterval(ping)
    if (room.bridge === ws) {
      room.bridge = null
      log(`ブリッジ切断: ${roomId} code=${code ?? ''}`)
      broadcastToRoom(roomId, { type: 'bridge_offline', bridgeId: roomId })
      pruneRoom(roomId)
    }
  }
  ws.on('close', (code) => drop(code))
  ws.on('error', (err) => log(`ブリッジ ${roomId} エラー: ${err.message}`))
}

function handleApp(ws, roomId) {
  const room = roomOf(roomId)
  room.apps.add(ws)
  log(`画面が接続しました room=${roomId}（この部屋 ${room.apps.size} 画面）`)

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

    const target = room.bridge
    if (!target) {
      send(ws, {
        type: 'ack',
        command: payload.command,
        id: payload.id,
        ok: false,
        error: 'ブリッジがつながっていません',
      })
      return
    }

    log(`画面 → 部屋 ${roomId}: ${payload.command} ${payload.name ?? ''} ${payload.value ?? ''}`)
    send(target, { ...payload, bridgeId: roomId })
  })

  const drop = () => {
    room.apps.delete(ws)
    log(`画面が切断しました room=${roomId}（残り ${room.apps.size} 画面）`)
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
  log(TOKEN ? '  認証       : 有効' : '  認証       : なし（ローカル検証用）')
  log('='.repeat(56))
})
