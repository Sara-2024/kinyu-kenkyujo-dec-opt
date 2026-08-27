// トレラボ 中継サーバー
//
// ブラウザ（管理画面）と、MT5のそばで動くブリッジ(bridge.py)をつなぐ。
// 両者は別々のWebSocket接続なので、このサーバーが間に立って指令と応答を橋渡しする。
//
//   ブラウザ  ──/app───┐
//                      ├─ このサーバー ─→ 指令の中継
//   bridge.py ─/bridge─┘
//
// 起動:  npm start          （既定 8080番）
//        PORT=9000 npm start

import { createServer } from 'node:http'
import { WebSocketServer } from 'ws'

const PORT = Number(process.env.PORT) || 8080
const TOKEN = (process.env.TRELAB_TOKEN || '').trim() // 空なら認証なし

/** bridgeId → WebSocket */
const bridges = new Map()
/** ブラウザ側の接続 */
const apps = new Set()
/** 各ブリッジが最後に伝えてきた状態（新しく開いたブラウザに即座に見せるため） */
const lastStatus = new Map()

const now = () => new Date().toISOString().slice(11, 19)
const log = (...args) => console.log(`[${now()}]`, ...args)

function send(ws, message) {
  if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(message))
}

/** ブラウザ全員に配る */
function broadcastToApps(message) {
  for (const ws of apps) send(ws, message)
}

/** いまつながっているブリッジの一覧 */
function bridgeList() {
  return [...bridges.keys()].map((id) => ({
    bridgeId: id,
    online: true,
    ...(lastStatus.get(id) ?? {}),
  }))
}

const server = createServer((req, res) => {
  // 死活確認用（Renderなどのヘルスチェックにも使える）
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ ok: true, bridges: bridges.size, apps: apps.size }))
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

  // トークンを設定している場合だけ確認する（ヘッダーでもクエリでも可）
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

  wss.handleUpgrade(req, socket, head, (ws) => {
    if (path === '/bridge') {
      const id = req.headers['x-bridge-id'] || url.searchParams.get('id') || 'bridge-1'
      handleBridge(ws, String(id))
    } else {
      handleApp(ws)
    }
  })
})

// ────────────────────────────────
// ブリッジ側（MT5のそば）
// ────────────────────────────────
function handleBridge(ws, bridgeId) {
  const previous = bridges.get(bridgeId)
  if (previous && previous !== ws) {
    log(`ブリッジ ${bridgeId} が再接続したため、古い接続を閉じます`)
    previous.close()
  }
  bridges.set(bridgeId, ws)
  log(`ブリッジ接続: ${bridgeId}（現在 ${bridges.size} 台）`)

  ws.on('message', (raw) => {
    let payload
    try {
      payload = JSON.parse(raw.toString())
    } catch {
      log(`ブリッジ ${bridgeId} から読めないデータ`)
      return
    }

    // 名乗り（口座情報など）は覚えておき、ブラウザ全員に配る
    if (payload.type === 'hello') {
      lastStatus.set(bridgeId, payload)
      log(`ブリッジ ${bridgeId} 名乗り: 口座=${payload.account} ${payload.server ?? ''}`)
      broadcastToApps({ type: 'bridge_online', bridgeId, status: payload })
      return
    }

    // 指令への応答。状態も更新しておく
    if (payload.type === 'ack') {
      const merged = { ...(lastStatus.get(bridgeId) ?? {}), ...payload }
      lastStatus.set(bridgeId, merged)
      log(`ブリッジ ${bridgeId} 応答: ${payload.command} ok=${payload.ok} value=${payload.value}`)
    }
    broadcastToApps({ ...payload, bridgeId })
  })

  const drop = () => {
    if (bridges.get(bridgeId) === ws) {
      bridges.delete(bridgeId)
      log(`ブリッジ切断: ${bridgeId}`)
      broadcastToApps({ type: 'bridge_offline', bridgeId })
    }
  }
  ws.on('close', drop)
  ws.on('error', drop)
}

// ────────────────────────────────
// ブラウザ側（管理画面）
// ────────────────────────────────
function handleApp(ws) {
  apps.add(ws)
  log(`画面が接続しました（現在 ${apps.size} 画面）`)

  // つないだ直後に、いまの状況を渡す
  send(ws, { type: 'welcome', bridges: bridgeList() })

  ws.on('message', (raw) => {
    let payload
    try {
      payload = JSON.parse(raw.toString())
    } catch {
      return
    }

    const targetId = payload.bridgeId || [...bridges.keys()][0]
    const target = targetId ? bridges.get(targetId) : null

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

    log(`画面 → ブリッジ ${targetId}: ${payload.command} ${payload.name ?? ''} ${payload.value ?? ''}`)
    send(target, payload)
  })

  const drop = () => {
    apps.delete(ws)
    log(`画面が切断しました（残り ${apps.size} 画面）`)
  }
  ws.on('close', drop)
  ws.on('error', drop)
}

server.listen(PORT, () => {
  log('='.repeat(56))
  log(`トレラボ中継サーバー 起動  ポート ${PORT}`)
  log(`  ブリッジ用 : ws://localhost:${PORT}/bridge`)
  log(`  画面用     : ws://localhost:${PORT}/app`)
  log(`  死活確認   : http://localhost:${PORT}/health`)
  log(TOKEN ? '  認証       : 有効' : '  認証       : なし（ローカル検証用）')
  log('='.repeat(56))
})
