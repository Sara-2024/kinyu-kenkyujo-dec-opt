// Vercel のサーバー関数。中身は _lib/chat.ts。
import type { IncomingMessage, ServerResponse } from 'node:http'
import { bearerOf, envFrom, handleChat, readJson } from './_lib/chat.js'

export default async function handler(req: IncomingMessage, res: ServerResponse) {
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.setHeader('cache-control', 'no-store')
  if (req.method !== 'POST') {
    res.statusCode = 405
    res.end(JSON.stringify({ error: 'POST only' }))
    return
  }
  const body = await readJson(req)
  const { status, body: out } = await handleChat(body, bearerOf(req.headers.authorization), envFrom(process.env))
  res.statusCode = status
  res.end(JSON.stringify(out))
}
