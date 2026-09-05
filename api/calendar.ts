// Vercel のサーバー関数。中身は _lib/calendar.ts。
import type { IncomingMessage, ServerResponse } from 'node:http'
import { handleCalendar } from './_lib/calendar.js'

export default async function handler(_req: IncomingMessage, res: ServerResponse) {
  const { status, body, maxAge } = await handleCalendar()
  res.statusCode = status
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.setHeader(
    'cache-control',
    maxAge > 0 ? `public, s-maxage=${maxAge}, stale-while-revalidate=${maxAge * 4}` : 'no-store',
  )
  res.end(JSON.stringify(body))
}
