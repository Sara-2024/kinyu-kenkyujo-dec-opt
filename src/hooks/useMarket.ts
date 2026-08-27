// 相場シミュレーション。450msごとに最後のローソクを揺らし、
// 5ティックごとに新しい足を生やす。triggerShock() で急落モードに入る。
import { useCallback, useEffect, useRef, useState } from 'react'

export interface Candle {
  o: number
  c: number
  h: number
  l: number
}

function mulberry32(seed: number) {
  let a = seed
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export const CANDLE_COUNT = 48

function seedCandles(): Candle[] {
  const rnd = mulberry32(20261212)
  const out: Candle[] = []
  let price = 157.1
  for (let i = 0; i < CANDLE_COUNT; i++) {
    const trend = i < 22 ? 0.004 : 0.045
    const drift = (rnd() - 0.48) * 0.2 + trend
    const o = price
    const c = price + drift
    out.push({ o, c, h: Math.max(o, c) + rnd() * 0.08, l: Math.min(o, c) - rnd() * 0.08 })
    price = c
  }
  return out
}

export function useMarket() {
  const [candles, setCandles] = useState<Candle[]>(seedCandles)
  const [shocked, setShocked] = useState(false)
  const shockRef = useRef(0)
  const tickRef = useRef(0)

  useEffect(() => {
    const id = setInterval(() => {
      tickRef.current++
      const inShock = shockRef.current > 0
      if (inShock) {
        shockRef.current--
        if (shockRef.current === 0) setShocked(false)
      }
      setCandles((prev) => {
        const out = prev.slice()
        const last = { ...out[out.length - 1] }
        const vol = inShock ? 0.15 : 0.03
        const drift = inShock ? -0.09 : (Math.random() - 0.47) * 0.045
        last.c = last.c + drift + (Math.random() - 0.5) * vol
        last.h = Math.max(last.h, last.c)
        last.l = Math.min(last.l, last.c)
        out[out.length - 1] = last
        if (tickRef.current % 5 === 0) {
          out.push({ o: last.c, c: last.c, h: last.c + 0.012, l: last.c - 0.012 })
          if (out.length > CANDLE_COUNT) out.shift()
        }
        return out
      })
    }, 450)
    return () => clearInterval(id)
  }, [])

  const triggerShock = useCallback(() => {
    if (shockRef.current > 0) return
    shockRef.current = 16 // 16ティック ≒ 7秒
    setShocked(true)
  }, [])

  const last = candles[candles.length - 1]
  const prevClose = candles.length > 1 ? candles[candles.length - 2].c : last.o
  return {
    candles,
    price: last.c,
    dir: last.c >= prevClose ? 1 : -1,
    shocked,
    triggerShock,
  }
}
