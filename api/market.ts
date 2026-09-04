// Vercel のサーバー関数。中身は _lib/market.ts。
import type { IncomingMessage, ServerResponse } from 'node:http'
import { handleMarket } from './_lib/market'

export default async function handler(req: IncomingMessage, res: ServerResponse) {
  const url = new URL(req.url ?? '/', 'http://localhost')
  const { status, body, maxAge } = await handleMarket(url)
  res.statusCode = status
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.setHeader(
    'cache-control',
    maxAge > 0 ? `public, s-maxage=${maxAge}, stale-while-revalidate=${maxAge * 4}` : 'no-store',
  )
  res.end(JSON.stringify(body))
}
