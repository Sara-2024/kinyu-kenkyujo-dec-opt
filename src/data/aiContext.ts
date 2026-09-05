// 研究員ごとに AI へ渡す「手元のデータ」。担当のぶんだけを、短く。
//
//   リン   … 大画面に出ている銘柄のローソク足と、そこから計算した高値・安値・移動平均
//   ジン   … 経済指標カレンダー（これから2日ぶん）と、主要な相場の現在値
//   アルゴ … MT5 の状態・本日の成績・建玉と、システムが行った取引の集計
//   ミオ   … お客様の約定履歴の集計（7日・30日）
//
// 数字は相場 API・カレンダー API・ブリッジが返した値をそのまま並べるだけで、ここでは作らない。
// 担当外のデータは入れない（入れると AI が余計なことまで調べて、費用も増える）。
import type { Candle } from './market'
import { symbolInfo } from './market'
import type { Quote } from './market'
import type { EconomicEvent } from './calendar'
import { eventLabel, formatEventDay, upcoming } from './calendar'
import type { BridgeStatus } from '../hooks/useBridge'
import { reviewTrades, type Trade, type TradeHistory } from './tradeReview'

const JST = 'Asia/Tokyo'

function hhmm(unixSec: number): string {
  return new Date(unixSec * 1000).toLocaleTimeString('ja-JP', { timeZone: JST, hour: '2-digit', minute: '2-digit', hour12: false })
}

function dayTime(unixSec: number): string {
  const d = new Date(unixSec * 1000)
  const md = d.toLocaleDateString('ja-JP', { timeZone: JST, month: 'numeric', day: 'numeric' })
  return `${md} ${hhmm(unixSec)}`
}

function nowJst(): string {
  return new Date().toLocaleString('ja-JP', { timeZone: JST, month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
}

function round(n: number, digits: number): number {
  return Number(n.toFixed(digits))
}

function sma(values: number[], n: number): number | null {
  if (values.length < n) return null
  const tail = values.slice(-n)
  return tail.reduce((a, b) => a + b, 0) / n
}

// ── リン：チャート ──
export interface RinContext {
  now: string
  symbol: string
  interval: string
  period: string
  price: number
  prevClose: number
  changePct: number | null
  high: { price: number; at: string; distance: number }
  low: { price: number; at: string; distance: number }
  last12: { high: number; low: number }
  ma20: { value: number; priceIs: 'above' | 'below' } | null
  ma50: { value: number; priceIs: 'above' | 'below' } | null
  ma20vs50: string | null
  candles: string[]
}

export function rinContext(market: { symbol: string; candles: Candle[]; interval: string; price: number; prevClose: number }): RinContext | null {
  const candles = market.candles
  if (candles.length < 5) return null
  const info = symbolInfo(market.symbol)
  const d = info.digits
  const closes = candles.map((k) => k.c)
  let hi = candles[0]
  let lo = candles[0]
  for (const k of candles) {
    if (k.h > hi.h) hi = k
    if (k.l < lo.l) lo = k
  }
  const price = market.price
  const ma20 = sma(closes, 20)
  const ma50 = sma(closes, 50)
  const recent = candles.slice(-12)
  const recentHi = Math.max(...recent.map((k) => k.h))
  const recentLo = Math.min(...recent.map((k) => k.l))
  const span = candles[candles.length - 1].t - candles[0].t
  return {
    now: nowJst(),
    symbol: info.label,
    interval: market.interval,
    period: `${dayTime(candles[0].t)}〜${dayTime(candles[candles.length - 1].t)}（約${Math.round(span / 3600)}時間）`,
    price: round(price, d),
    prevClose: round(market.prevClose, d),
    changePct: market.prevClose ? round(((price - market.prevClose) / market.prevClose) * 100, 2) : null,
    high: { price: round(hi.h, d), at: dayTime(hi.t), distance: round(hi.h - price, d) },
    low: { price: round(lo.l, d), at: dayTime(lo.t), distance: round(price - lo.l, d) },
    last12: { high: round(recentHi, d), low: round(recentLo, d) },
    ma20: ma20 != null ? { value: round(ma20, d), priceIs: price >= ma20 ? 'above' : 'below' } : null,
    ma50: ma50 != null ? { value: round(ma50, d), priceIs: price >= ma50 ? 'above' : 'below' } : null,
    ma20vs50: ma20 != null && ma50 != null ? (ma20 >= ma50 ? 'ma20 above ma50' : 'ma20 below ma50') : null,
    // ローソク足は「時刻 始値 高値 安値 終値」を1本1行で（トークンを節約）
    candles: candles.map((k) => `${hhmm(k.t)} ${round(k.o, d)} ${round(k.h, d)} ${round(k.l, d)} ${round(k.c, d)}`),
  }
}

// ── ジン：経済指標と主要レート ──
const JIN_QUOTES = ['USDJPY=X', 'EURUSD=X', 'EURJPY=X', 'GC=F', '^N225', '^GSPC', 'CL=F']
const JIN_HOURS = 48
const JIN_MAX_EVENTS = 24

export function jinContext(calendar: EconomicEvent[] | null, quoteMap: Map<string, Quote>): unknown | null {
  if (!calendar) return null
  const now = Date.now()
  const soon = upcoming(calendar, now).filter((e) => new Date(e.at).getTime() - now < JIN_HOURS * 3600_000)
  // 直近2日に無ければ、その先の重要度「高」を少しだけ
  const list = soon.length ? soon : upcoming(calendar, now).filter((e) => e.impact === 'high').slice(0, 8)
  const quotes: Record<string, string> = {}
  for (const s of JIN_QUOTES) {
    const q = quoteMap.get(s)
    if (!q) continue
    const info = symbolInfo(s)
    quotes[info.label] = `${round(q.price, info.digits)} (${q.changePct >= 0 ? '+' : ''}${round(q.changePct, 2)}%)`
  }
  return {
    now: nowJst(),
    timezone: '日本時間',
    eventsNote: list.length ? undefined : '手元のカレンダーに、この先の指標の予定はまだ入っていない（次の週のぶんは週明けに更新される）',
    events: list.slice(0, JIN_MAX_EVENTS).map((e) => ({
      at: formatEventDay(e.at),
      name: eventLabel(e),
      impact: e.impact === 'high' ? '高' : '中',
      forecast: e.forecast || undefined,
      previous: e.previous || undefined,
    })),
    quotes,
  }
}

// ── アルゴ：MT5 の状態とシステムの取引 ──
function compactTrade(t: Trade): string {
  const d = t.digits ?? 3
  return `${t.closed_at.slice(0, 16)} ${t.symbol} ${t.side} ${t.volume}lot ${round(t.open_price, d)}→${round(t.close_price, d)} ${t.profit >= 0 ? '+' : ''}${t.profit} (${Math.round(t.held_sec / 60)}min)`
}

export function algoContext(status: BridgeStatus | null, history: TradeHistory | null): unknown | null {
  if (!status) return null
  const positions = status.positions ?? []
  const trades = history?.trades ?? []
  const system = trades.filter((t) => t.by_system)
  const manualCount = trades.length - system.length
  const review = reviewTrades(history && system.length ? { ...history, trades: system, total: system.length } : undefined, status.currency)
  const best = system.length ? system.reduce((a, b) => (b.profit > a.profit ? b : a)) : null
  const worst = system.length ? system.reduce((a, b) => (b.profit < a.profit ? b : a)) : null
  return {
    now: nowJst(),
    currency: status.currency,
    account: { server: status.server, balance: status.balance, equity: status.equity },
    system: {
      running: typeof status.value === 'number' ? status.value !== 0 : null,
      eaOnChart: status.ea_alive === true,
      eaState: status.ea_state ?? null,
      autoTradingButton: status.terminal_trade_allowed ?? null,
      settings: status.gate ?? null,
    },
    today: status.today ?? null,
    positions: positions.map((p) => `${p.symbol} ${p.side} ${p.volume}lot open ${p.price_open} now ${p.price_current} ${p.profit >= 0 ? '+' : ''}${p.profit}`),
    systemTrades: history
      ? {
          days: history.days,
          count: system.length,
          manualCountNotCovered: manualCount,
          wins: review?.wins ?? 0,
          losses: review?.losses ?? 0,
          winRate: review?.winRate ?? null,
          profit: review?.profit ?? 0,
          avgWin: review?.avgWin ?? 0,
          avgLoss: review?.avgLoss ?? 0,
          bySymbol: review?.bySymbol.map((b) => `${b.key}: ${b.trades}回 ${b.wins}勝 ${b.profit >= 0 ? '+' : ''}${b.profit}`) ?? [],
          best: best ? compactTrade(best) : null,
          worst: worst ? compactTrade(worst) : null,
          recent: system.slice(0, 12).map(compactTrade),
        }
      : null,
  }
}

// ── ミオ：お客様の履歴の集計 ──
function sliceDays(history: TradeHistory, days: number): TradeHistory {
  const since = Date.now() - days * 86400_000
  const trades = history.trades.filter((t) => new Date(t.closed_at).getTime() >= since)
  return { ...history, days, trades, total: trades.length }
}

function summarize(history: TradeHistory, currency: string | undefined, detail: boolean) {
  const r = reviewTrades(history, currency)
  if (!r) return { days: history.days, count: 0 }
  return {
    days: r.days,
    count: r.count,
    wins: r.wins,
    losses: r.losses,
    winRate: r.winRate,
    profit: r.profit,
    avgWin: r.avgWin,
    avgLoss: r.avgLoss,
    payoff: r.payoff,
    maxWinStreak: r.maxWinStreak,
    maxLossStreak: r.maxLossStreak,
    avgHoldWinMin: Math.round(r.avgHoldWin / 60),
    avgHoldLossMin: Math.round(r.avgHoldLoss / 60),
    medianLot: r.medianVolume,
    maxLot: r.maxVolume,
    bySymbol: r.bySymbol.map((b) => `${b.key}: ${b.trades}回 ${b.wins}勝 ${b.profit >= 0 ? '+' : ''}${b.profit}`),
    byHour: r.byHour.filter((b) => b.trades >= 2).map((b) => `${b.label}: ${b.trades}回 ${b.wins}勝 ${b.profit >= 0 ? '+' : ''}${b.profit}`),
    byWeekday: r.byWeekday.map((b) => `${b.label}: ${b.trades}回 ${b.wins}勝 ${b.profit >= 0 ? '+' : ''}${b.profit}`),
    system: r.system ? `${r.system.trades}回 ${r.system.profit >= 0 ? '+' : ''}${r.system.profit}` : null,
    manual: r.manual ? `${r.manual.trades}回 ${r.manual.profit >= 0 ? '+' : ''}${r.manual.profit}` : null,
    // 気づきの本文は 1 週間ぶんだけ。1 か月ぶんは見出しだけにしてトークンを節約する
    findings: r.points.map((p) => `${p.tone === 'good' ? '良' : '注意'}: ${p.title}${detail ? ` — ${p.detail}` : ''}`),
  }
}

export function mioContext(status: BridgeStatus | null, history: TradeHistory | null): unknown | null {
  if (!history) return null
  const currency = status?.currency
  const ordered = [...history.trades].sort((a, b) => b.closed_at.localeCompare(a.closed_at))
  return {
    now: nowJst(),
    currency,
    week: summarize(sliceDays(history, 7), currency, true),
    month: summarize(sliceDays(history, 30), currency, false),
    recent: ordered.slice(0, 15).map((t) => `${compactTrade(t)}${t.by_system ? ' [system]' : ''}`),
  }
}
