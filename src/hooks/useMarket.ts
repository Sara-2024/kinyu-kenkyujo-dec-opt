// 相場データ。/api/market から取った本物の値を土台にして、
//  - ティッカーの現在値は 60 秒ごとに取り直す
//  - チャートは銘柄を切り替えるたび、および 60 秒ごとに取り直す
//  - 次の取得までのあいだ、直近の足だけをごく小さく揺らして「生きている」感じを出す
//    （揺れ幅は直近の値幅の数%以内。次の取得で必ず本物の値に戻る）
// triggerShock() は「急変動シミュレート」ボタン用で、画面上の演出として
// 直近の足だけを一時的に下げる。終わると本物の足に戻る。
//
// お客様が MT5 と連携しているあいだは、ブリッジ経由で MT5 の気配値と
// ローソク足をそのまま使う（業者のレートと一致する）。取れないときは /api/market。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CHART_SYMBOLS,
  TICKER_SYMBOLS,
  loadChart,
  loadQuotes,
  mt5SymbolInfo,
  type Candle,
  type ChartData,
  type MarketSource,
  type Quote,
  type SymbolInfo,
} from '../data/market'
import type { BridgeAck } from './useBridge'

export type { Candle }

export const CANDLE_COUNT = 64
const QUOTES_EVERY = 60_000
const CHART_EVERY = 60_000
const MT5_EVERY = 4_000
const TICK_MS = 450


/** MT5 側のデータ源。連携中の画面だけが渡す */
export interface MarketBridge {
  live: boolean
  send: (command: string, extra?: Record<string, unknown>) => Promise<BridgeAck>
}

type Mt5Quote = Quote & { digits: number }
type Mt5Ack = BridgeAck & { symbols?: string[]; quotes?: Mt5Quote[]; chart?: ChartData | null }

function jitterAmount(candles: Candle[]): number {
  const tail = candles.slice(-12)
  if (tail.length === 0) return 0
  const avgRange = tail.reduce((a, k) => a + (k.h - k.l), 0) / tail.length
  return avgRange * 0.05
}

export function useMarket(bridge?: MarketBridge) {
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [symbol, setSymbol] = useState(CHART_SYMBOLS[0].symbol)
  const [chart, setChart] = useState<ChartData | null>(null)
  const [live, setLive] = useState<Candle[]>([])
  const [shocked, setShocked] = useState(false)
  const shockRef = useRef(0)
  const baseRef = useRef<Candle[]>([])
  // MT5 から取れているあいだだけ 'mt5'
  const [source, setSource] = useState<MarketSource>('web')
  const [mt5Symbols, setMt5Symbols] = useState<SymbolInfo[]>([])

  const bridgeLive = !!bridge?.live
  const send = bridge?.send
  const useMt5 = bridgeLive && source === 'mt5'

  // 表示する銘柄一覧。MT5 から取れたらその気配値、そうでなければ既定
  const chartSymbols = useMt5 && mt5Symbols.length > 0 ? mt5Symbols.slice(0, 6) : CHART_SYMBOLS
  const tickerSymbols = useMt5 && mt5Symbols.length > 0 ? mt5Symbols : TICKER_SYMBOLS
  const activeSymbol = chartSymbols.some((s) => s.symbol === symbol) ? symbol : chartSymbols[0].symbol
  const activeRef = useRef(activeSymbol)
  activeRef.current = activeSymbol

  // ── MT5（連携中） ──
  useEffect(() => {
    if (!bridgeLive || !send) {
      setSource('web')
      return
    }
    let alive = true
    let failures = 0
    const pull = async () => {
      const ack = (await send('get_market', { symbol: activeRef.current, interval: '15m', count: CANDLE_COUNT })) as Mt5Ack
      if (!alive) return
      if (!ack.ok || !ack.quotes || ack.quotes.length === 0) {
        // 3回続けて取れなければ web に戻す（MT5 を閉じたときなど）
        if (++failures >= 3) setSource('web')
        return
      }
      failures = 0
      const infos = ack.quotes.map((q) => mt5SymbolInfo(q.symbol, q.digits))
      setMt5Symbols(infos)
      setQuotes(ack.quotes)
      if (ack.chart && ack.chart.candles.length > 0) {
        const candles = ack.chart.candles.slice(-CANDLE_COUNT)
        baseRef.current = candles
        setChart(ack.chart)
        setLive(candles)
      }
      setSource('mt5')
    }
    void pull()
    const id = setInterval(pull, MT5_EVERY)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [bridgeLive, send])

  // ── ティッカー（web） ──
  useEffect(() => {
    if (useMt5) return
    let alive = true
    const pull = async () => {
      try {
        const q = await loadQuotes()
        if (alive && q.length) setQuotes(q)
      } catch {
        // 取れないときは前回の値を出したままにする
      }
    }
    void pull()
    const id = setInterval(pull, QUOTES_EVERY)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [useMt5])

  // ── チャート（web） ──
  useEffect(() => {
    if (useMt5) return
    let alive = true
    const pull = async () => {
      try {
        const data = await loadChart(activeSymbol)
        if (!alive) return
        const candles = data.candles.slice(-CANDLE_COUNT)
        baseRef.current = candles
        setChart(data)
        setLive(candles)
      } catch {
        // 前回のチャートを出したまま
      }
    }
    void pull()
    const id = setInterval(pull, CHART_EVERY)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [activeSymbol, useMt5])

  // MT5 のときは銘柄を切り替えたらすぐ取り直す
  useEffect(() => {
    if (!useMt5 || !send) return
    let alive = true
    void send('get_market', { symbol: activeSymbol, interval: '15m', count: CANDLE_COUNT }).then((raw) => {
      const ack = raw as Mt5Ack
      if (!alive || !ack.ok || !ack.chart || ack.chart.candles.length === 0) return
      const candles = ack.chart.candles.slice(-CANDLE_COUNT)
      baseRef.current = candles
      setChart(ack.chart)
      setLive(candles)
    })
    return () => {
      alive = false
    }
  }, [activeSymbol, useMt5, send])

  const sourceRef = useRef<MarketSource>('web')
  sourceRef.current = useMt5 ? 'mt5' : 'web'

  // ── 直近の足を小さく揺らす／急変動の演出 ──
  useEffect(() => {
    const id = setInterval(() => {
      const base = baseRef.current
      if (base.length === 0) return
      const inShock = shockRef.current > 0
      if (inShock) {
        shockRef.current--
        if (shockRef.current === 0) {
          setShocked(false)
          setLive(base)
          return
        }
      }
      // MT5 のときは数秒ごとに本物の値が来るので、揺らさない
      if (!inShock && sourceRef.current === 'mt5') return
      const amp = jitterAmount(base)
      setLive((prev) => {
        const src = prev.length === base.length ? prev : base
        const out = src.slice()
        const real = base[base.length - 1]
        const last = { ...out[out.length - 1] }
        if (inShock) {
          last.c = last.c - amp * 1.6 + (Math.random() - 0.5) * amp
        } else {
          // 本物の終値のまわりで揺れる。離れすぎたら引き戻す
          const pull = (real.c - last.c) * 0.35
          last.c = last.c + pull + (Math.random() - 0.5) * amp
        }
        last.h = Math.max(real.h, last.c)
        last.l = Math.min(real.l, last.c)
        out[out.length - 1] = last
        return out
      })
    }, TICK_MS)
    return () => clearInterval(id)
  }, [])

  const triggerShock = useCallback(() => {
    if (shockRef.current > 0) return
    shockRef.current = 16 // 16ティック ≒ 7秒
    setShocked(true)
  }, [])

  const candles = live
  const last = candles[candles.length - 1]
  const prevClose = chart?.prevClose ?? (candles.length > 1 ? candles[candles.length - 2].c : last?.o)
  const price = last?.c ?? chart?.price ?? 0

  const quoteMap = useMemo(() => new Map(quotes.map((q) => [q.symbol, q])), [quotes])

  return {
    candles,
    symbol: activeSymbol,
    setSymbol,
    /** 'mt5' = お客様の MT5 のレート、'web' = 参考レート */
    source: useMt5 ? ('mt5' as const) : ('web' as const),
    chartSymbols,
    tickerSymbols,
    interval: chart?.interval ?? '15m',
    digits: chart?.digits,
    price,
    prevClose: prevClose ?? price,
    dir: prevClose != null && price < prevClose ? -1 : 1,
    ready: candles.length > 0,
    quotes,
    quoteMap,
    shocked,
    triggerShock,
  }
}
