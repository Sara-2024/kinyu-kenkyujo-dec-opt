// 相場データ。/api/market から取った本物の値を土台にして、
//  - ティッカーの現在値は 60 秒ごとに取り直す
//  - チャートは銘柄を切り替えるたび、および 60 秒ごとに取り直す
//  - 次の取得までのあいだ、直近の足だけをごく小さく揺らして「生きている」感じを出す
//    （揺れ幅は直近の値幅の数%以内。次の取得で必ず本物の値に戻る）
// triggerShock() は「急変動シミュレート」ボタン用で、画面上の演出として
// 直近の足だけを一時的に下げる。終わると本物の足に戻る。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CHART_SYMBOLS, loadChart, loadQuotes, type Candle, type ChartData, type Quote } from '../data/market'

export type { Candle }

export const CANDLE_COUNT = 64
const QUOTES_EVERY = 60_000
const CHART_EVERY = 60_000
const TICK_MS = 450

function jitterAmount(candles: Candle[]): number {
  const tail = candles.slice(-12)
  if (tail.length === 0) return 0
  const avgRange = tail.reduce((a, k) => a + (k.h - k.l), 0) / tail.length
  return avgRange * 0.05
}

export function useMarket() {
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [symbol, setSymbol] = useState(CHART_SYMBOLS[0].symbol)
  const [chart, setChart] = useState<ChartData | null>(null)
  const [live, setLive] = useState<Candle[]>([])
  const [shocked, setShocked] = useState(false)
  const shockRef = useRef(0)
  const baseRef = useRef<Candle[]>([])

  // ── ティッカー ──
  useEffect(() => {
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
  }, [])

  // ── チャート ──
  useEffect(() => {
    let alive = true
    const pull = async () => {
      try {
        const data = await loadChart(symbol)
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
  }, [symbol])

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

  /**
   * 研究員に渡す「本物の相場」。
   *
   * 画面の `candles` は、生きて見えるように直近の足を揺らしてある（急変動の演出もある）。
   * それをそのまま研究員に渡すと、AI が実在しない高値・安値・現在値を事実として説明する。
   * AGENTS.md の「数字は作らない」に反するので、AI と受け答えには取得したままの足を使う。
   */
  const marketForAi = useCallback(() => {
    const base = baseRef.current
    const realLast = base[base.length - 1]
    const realPrev = chart?.prevClose ?? (base.length > 1 ? base[base.length - 2].c : realLast?.o)
    return {
      symbol,
      candles: base,
      interval: chart?.interval ?? '15m',
      price: realLast?.c ?? chart?.price ?? 0,
      prevClose: realPrev ?? realLast?.c ?? 0,
    }
  }, [symbol, chart])

  const candles = live
  const last = candles[candles.length - 1]
  const prevClose = chart?.prevClose ?? (candles.length > 1 ? candles[candles.length - 2].c : last?.o)
  const price = last?.c ?? chart?.price ?? 0

  const quoteMap = useMemo(() => new Map(quotes.map((q) => [q.symbol, q])), [quotes])

  return {
    candles,
    symbol,
    setSymbol,
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
    marketForAi,
  }
}
