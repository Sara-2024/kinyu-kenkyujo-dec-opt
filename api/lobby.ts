// Vercel のサーバー関数。中身は _lib/lobby.ts。
// ドリームランドのロビー（dreamland/index.html）が、会員登録・ログイン・接続の合図をここに頼む。
import type { IncomingMessage, ServerResponse } from 'node:http'
import { envFrom, handleLobby, maskAccount, readJson } from './_lib/lobby.js'

function clientKeyOf(req: IncomingMessage): string {
  const forwarded = req.headers['x-forwarded-for']
  const raw = Array.isArray(forwarded) ? forwarded[0] : forwarded
  return (raw || req.socket?.remoteAddress || 'unknown').split(',')[0].trim()
}

export default async function handler(req: IncomingMessage, res: ServerResponse) {
  const env = envFrom(process.env)
  // ロビーは別のドメインに置かれる。DREAMLAND_ORIGIN を設定すればそこだけに絞れる
  res.setHeader('access-control-allow-origin', env.allowOrigin || '*')
  res.setHeader('access-control-allow-methods', 'POST, OPTIONS')
  res.setHeader('access-control-allow-headers', 'content-type')
  res.setHeader('access-control-max-age', '86400')
  res.setHeader('cache-control', 'no-store')
  if (req.method === 'OPTIONS') {
    res.statusCode = 204
    res.end()
    return
  }
  res.setHeader('content-type', 'application/json; charset=utf-8')
  if (req.method !== 'POST') {
    res.statusCode = 405
    res.end(JSON.stringify({ error: 'POST only' }))
    return
  }
  const body = await readJson(req)
  const { status, body: out } = await handleLobby(body, env, clientKeyOf(req))
  // パスワード・合言葉・セッション・合図は記録に残さない。口座番号も下2桁だけ
  console.log(`[lobby] ${String(body?.action ?? '-')} ${maskAccount(body?.account)} -> ${status}`)
  res.statusCode = status
  res.end(JSON.stringify(out))
}
