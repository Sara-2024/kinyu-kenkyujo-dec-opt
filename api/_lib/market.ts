// 相場データの取り次ぎ。ブラウザから直接は取れない（CORS）ので、
// サイト側のサーバー関数（Vercel の /api/market と、開発中は Vite）が
// Yahoo Finance に問い合わせて、画面が使いやすい形に整えて返す。
//
//   /api/market?kind=quotes                       … ティッカー用（複数銘柄の現在値）
//   /api/market?kind=chart&symbol=USDJPY=X        … チャート用（ローソク足）
//
// 銘柄の一覧はここで固定する。画面から任意の銘柄を指定させない。

export interface Quote {
  symbol: string
  price: number
  prevClose: number
  /** 前日終値からの変化率（%） */
  changePct: number
  /** 直近1日の終値の並び（小さなスパークライン用） */
  spark: number[]
  /** 取得した時刻（UNIX秒） */
  at: number
}

export interface Candle {
  t: number
  o: number
  h: number
  l: number
  c: number
}

export interface ChartData {
  symbol: string
  interval: string
  digits: number
  price: number
  prevClose: number
  candles: Candle[]
  at: number
}

/** ティッカーに並べる銘柄（順番どおりに流れる） */
export const QUOTE_SYMBOLS = [
  'USDJPY=X',
  'EURUSD=X',
  'GBPUSD=X',
  'EURJPY=X',
  'AUDJPY=X',
  'GC=F',
  'BTC-USD',
  'ETH-USD',
  'XRP-USD',
  '^N225',
  '^GSPC',
  'CL=F',
] as const

/** チャートで切り替えられる銘柄 */
export const CHART_SYMBOLS = ['USDJPY=X', 'GC=F', 'EURUSD=X', 'EURJPY=X', 'BTC-USD', '^N225'] as const

const CHART_INTERVALS = new Set(['5m', '15m', '1h'])

// ブラウザ風の User-Agent を付けると Yahoo が 429 を返す（cookie を要求する）ので、
// 素の fetch のまま問い合わせる。query1 がだめなら query2 も試す。
async function yahoo(path: string): Promise<unknown> {
  let lastStatus = 0
  for (const host of ['query1', 'query2']) {
    const res = await fetch(`https://${host}.finance.yahoo.com${path}`, { headers: { accept: 'application/json' } })
    if (res.ok) return res.json()
    lastStatus = res.status
  }
  throw new Error(`yahoo ${lastStatus}`)
}

/** 直近に取れた値。取りに行って失敗したときは、これを返して画面を止めない */
const lastGood = new Map<string, unknown>()

async function remember<T>(key: string, load: () => Promise<T>): Promise<T> {
  try {
    const v = await load()
    lastGood.set(key, v)
    return v
  } catch (err) {
    const cached = lastGood.get(key)
    if (cached !== undefined) return cached as T
    throw err
  }
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

interface SparkRow {
  symbol?: string
  close?: Array<number | null>
  previousClose?: number
  chartPreviousClose?: number
  fulldayPrice?: number
}

export async function fetchQuotes(): Promise<Quote[]> {
  const symbols = QUOTE_SYMBOLS.map(encodeURIComponent).join(',')
  const data = (await yahoo(`/v8/finance/spark?symbols=${symbols}&range=1d&interval=15m`)) as Record<string, SparkRow>
  const at = Math.floor(Date.now() / 1000)
  const out: Quote[] = []
  for (const symbol of QUOTE_SYMBOLS) {
    const row = data[symbol]
    if (!row) continue
    const spark = (row.close ?? []).filter((v): v is number => num(v) != null)
    const price = num(row.fulldayPrice) ?? (spark.length ? spark[spark.length - 1] : null)
    const prevClose = num(row.previousClose) ?? num(row.chartPreviousClose) ?? price
    if (price == null || prevClose == null) continue
    out.push({
      symbol,
      price,
      prevClose,
      changePct: prevClose ? ((price - prevClose) / prevClose) * 100 : 0,
      spark: spark.slice(-40),
      at,
    })
  }
  return out
}

interface ChartResponse {
  chart?: {
    result?: Array<{
      meta?: { regularMarketPrice?: number; previousClose?: number; chartPreviousClose?: number; priceHint?: number }
      timestamp?: number[]
      indicators?: { quote?: Array<{ open?: Array<number | null>; high?: Array<number | null>; low?: Array<number | null>; close?: Array<number | null> }> }
    }>
    error?: unknown
  }
}

export async function fetchChart(symbol: string, interval = '15m'): Promise<ChartData> {
  if (!(CHART_SYMBOLS as readonly string[]).includes(symbol)) throw new Error('unknown symbol')
  if (!CHART_INTERVALS.has(interval)) interval = '15m'
  const range = interval === '1h' ? '10d' : interval === '5m' ? '1d' : '3d'
  const data = (await yahoo(
    `/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}`,
  )) as ChartResponse
  const result = data.chart?.result?.[0]
  if (!result) throw new Error('no chart')
  const ts = result.timestamp ?? []
  const q = result.indicators?.quote?.[0] ?? {}
  const candles: Candle[] = []
  for (let i = 0; i < ts.length; i++) {
    const o = num(q.open?.[i])
    const h = num(q.high?.[i])
    const l = num(q.low?.[i])
    const c = num(q.close?.[i])
    if (o == null || h == null || l == null || c == null) continue
    candles.push({ t: ts[i], o, h, l, c })
  }
  const meta = result.meta ?? {}
  const last = candles[candles.length - 1]
  const price = num(meta.regularMarketPrice) ?? last?.c ?? 0
  const prevClose = num(meta.previousClose) ?? num(meta.chartPreviousClose) ?? price
  return {
    symbol,
    interval,
    digits: Math.min(5, Math.max(0, num(meta.priceHint) ?? 2)),
    price,
    prevClose,
    candles: candles.slice(-120),
    at: Math.floor(Date.now() / 1000),
  }
}

/** URL を受け取って JSON を返す。Vercel でも Vite の開発サーバーでも同じ */
export async function handleMarket(url: URL): Promise<{ status: number; body: unknown; maxAge: number }> {
  const kind = url.searchParams.get('kind') ?? 'quotes'
  try {
    if (kind === 'chart') {
      const symbol = url.searchParams.get('symbol') ?? 'USDJPY=X'
      const interval = url.searchParams.get('interval') ?? '15m'
      const body = await remember(`chart:${symbol}:${interval}`, () => fetchChart(symbol, interval))
      return { status: 200, body, maxAge: 60 }
    }
    const quotes = await remember('quotes', fetchQuotes)
    return { status: 200, body: { quotes }, maxAge: 45 }
  } catch (err) {
    return { status: 502, body: { error: err instanceof Error ? err.message : String(err) }, maxAge: 0 }
  }
}
