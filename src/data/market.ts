// 画面に出す相場銘柄の名前と桁数。数字そのものは /api/market が
// Yahoo Finance から取ってきたものだけを使い、ここでは作らない。
import type { Candle, ChartData, Quote } from '../../api/_lib/market'

export type { Candle, ChartData, Quote }

/** 'mt5' = お客様の MT5 のレート、'web' = 参考レート */
export type MarketSource = 'mt5' | 'web'

export interface SymbolInfo {
  /** Yahoo Finance の記号 */
  symbol: string
  /** 画面に出す名前 */
  label: string
  /** 小数の桁 */
  digits: number
  /** 3桁区切りを付けるか */
  group?: boolean
}

/** ティッカー（画面上部）に流す銘柄。順番どおりに流れる */
export const TICKER_SYMBOLS: SymbolInfo[] = [
  { symbol: 'USDJPY=X', label: 'USD/JPY', digits: 3 },
  { symbol: 'EURUSD=X', label: 'EUR/USD', digits: 4 },
  { symbol: 'GBPUSD=X', label: 'GBP/USD', digits: 4 },
  { symbol: 'EURJPY=X', label: 'EUR/JPY', digits: 3 },
  { symbol: 'AUDJPY=X', label: 'AUD/JPY', digits: 3 },
  { symbol: 'GC=F', label: 'GOLD', digits: 1, group: true },
  { symbol: 'BTC-USD', label: 'BTC/USD', digits: 0, group: true },
  { symbol: 'ETH-USD', label: 'ETH/USD', digits: 1, group: true },
  { symbol: 'XRP-USD', label: 'XRP/USD', digits: 4 },
  { symbol: '^N225', label: 'NIKKEI 225', digits: 0, group: true },
  { symbol: '^GSPC', label: 'S&P 500', digits: 0, group: true },
  { symbol: 'CL=F', label: 'WTI OIL', digits: 2 },
]

/** 大画面チャートで切り替えられる銘柄 */
// 主役はドル円とゴールド。残りは切り替え用
export const CHART_SYMBOLS: SymbolInfo[] = [
  { symbol: 'USDJPY=X', label: 'USD/JPY', digits: 3 },
  { symbol: 'GC=F', label: 'GOLD', digits: 1, group: true },
  { symbol: 'EURUSD=X', label: 'EUR/USD', digits: 4 },
  { symbol: 'EURJPY=X', label: 'EUR/JPY', digits: 3 },
  { symbol: 'BTC-USD', label: 'BTC/USD', digits: 0, group: true },
  { symbol: '^N225', label: 'NIKKEI', digits: 0, group: true },
]

/** MT5 の銘柄名から表示名を作る（"USDJPY.m" → "USD/JPY"、"XAUUSD" → "GOLD"） */
export function mt5SymbolInfo(name: string, digits: number): SymbolInfo {
  const head = name.split('.')[0].split('-')[0].split('_')[0].toUpperCase()
  const core = head.length > 6 && /^[A-Z]+$/.test(head) ? head.slice(0, 6) : head
  let label = name
  if (core === 'XAUUSD' || core === 'GOLD') label = 'GOLD'
  else if (core === 'XAGUSD') label = 'SILVER'
  else if (/^[A-Z]{6}$/.test(core)) label = `${core.slice(0, 3)}/${core.slice(3)}`
  return { symbol: name, label, digits, group: digits <= 2 && !/^[A-Z]{6}$/.test(core) }
}

export function symbolInfo(symbol: string): SymbolInfo {
  return (
    CHART_SYMBOLS.find((s) => s.symbol === symbol) ??
    TICKER_SYMBOLS.find((s) => s.symbol === symbol) ?? { symbol, label: symbol, digits: 2 }
  )
}

export function formatMarketPrice(value: number, info: SymbolInfo): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: info.digits,
    maximumFractionDigits: info.digits,
    useGrouping: !!info.group,
  })
}

export async function loadQuotes(): Promise<Quote[]> {
  const res = await fetch('/api/market?kind=quotes')
  if (!res.ok) throw new Error(`quotes ${res.status}`)
  const data = (await res.json()) as { quotes?: Quote[] }
  return data.quotes ?? []
}

export async function loadChart(symbol: string, interval = '15m'): Promise<ChartData> {
  const res = await fetch(`/api/market?kind=chart&symbol=${encodeURIComponent(symbol)}&interval=${interval}`)
  if (!res.ok) throw new Error(`chart ${res.status}`)
  return (await res.json()) as ChartData
}
