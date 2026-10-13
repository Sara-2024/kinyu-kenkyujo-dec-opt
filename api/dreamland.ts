// Vercel のサーバー関数。中身は _lib/dreamland.ts。
// ドリームランドのロビー（dreamland/index.html）から、お客様の MT5 口座の申込が届く。
import type { IncomingMessage, ServerResponse } from 'node:http'
import { envFrom, handleDreamland, maskAccount, readJson } from './_lib/dreamland.js'

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
  const { status, body: out } = await handleDreamland(body, env, clientKeyOf(req))
  // パスワードは記録に残さない。口座番号も下2桁だけ
  const acct = body && (typeof body.account === 'number' || typeof body.account === 'string') ? maskAccount(body.account) : '-'
  console.log(`[dreamland] ${acct} ${String(body?.plan ?? '-')} -> ${status}`)
  res.statusCode = status
  res.end(JSON.stringify(out))
}
