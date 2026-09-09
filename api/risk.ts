// Vercel のサーバー関数。中身は _lib/risk.ts。
// お客様のPCのブリッジだけが呼ぶ（合言葉 TRELAB_RISK_TOKEN）。ブラウザからは呼ばない。
import type { IncomingMessage, ServerResponse } from 'node:http'
import { handleRisk, riskEnvFrom, type RiskRequest } from './_lib/risk.js'

async function readJson(req: IncomingMessage): Promise<RiskRequest | null> {
  const chunks: Buffer[] = []
  for await (const chunk of req) chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : Buffer.from(chunk))
  const raw = Buffer.concat(chunks).toString('utf8')
  if (!raw) return null
  try {
    return JSON.parse(raw) as RiskRequest
  } catch {
    return null
  }
}

export default async function handler(req: IncomingMessage, res: ServerResponse) {
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.setHeader('cache-control', 'no-store')
  if (req.method !== 'POST') {
    res.statusCode = 405
    res.end(JSON.stringify({ error: 'POST only' }))
    return
  }
  const token = String(req.headers['x-trelab-bridge'] ?? '')
  const { status, body } = await handleRisk(await readJson(req), riskEnvFrom(process.env), token)
  res.statusCode = status
  res.end(JSON.stringify(body))
}
