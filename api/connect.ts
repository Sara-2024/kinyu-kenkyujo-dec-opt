// Vercel のサーバー関数。中身は _lib/connect.ts。
// お客様のPCの AI Trader Connect だけが呼ぶ（ワンタイムの合図を確かめる）。
import type { IncomingMessage, ServerResponse } from 'node:http'
import { envFrom, handleConnect, maskToken, readJson } from './_lib/connect.js'

function clientKeyOf(req: IncomingMessage): string {
  const forwarded = req.headers['x-forwarded-for']
  const raw = Array.isArray(forwarded) ? forwarded[0] : forwarded
  return (raw || req.socket?.remoteAddress || 'unknown').split(',')[0].trim()
}

export default async function handler(req: IncomingMessage, res: ServerResponse) {
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.setHeader('cache-control', 'no-store')
  if (req.method !== 'POST') {
    res.statusCode = 405
    res.end(JSON.stringify({ error: 'POST only' }))
    return
  }
  const body = await readJson(req)
  const { status, body: out } = await handleConnect(body, envFrom(process.env), clientKeyOf(req))
  if (typeof body?.token === 'string') {
    // 合図そのものは記録に残さない（残すと、記録を見た人が連携できてしまう）
    console.log(`[connect] ${maskToken(body.token)} -> ${status}`)
  }
  res.statusCode = status
  res.end(JSON.stringify(out))
}
