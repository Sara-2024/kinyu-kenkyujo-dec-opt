// 壁の大型ライブチャート、サーバーラック、コードモニター、机まわり。
// パネルはすべて共通トークン（--panel-bg / --panel-border / --panel-glow）で統一。
import type { CSSProperties, ReactNode } from 'react'
import { CHART_SYMBOLS, formatMarketPrice, symbolInfo, type Candle } from '../data/market'

const GREEN = '#2fbf62'
const RED = '#e04b4b'

export function Panel({
  children,
  className = '',
  style,
}: {
  children: ReactNode
  className?: string
  style?: CSSProperties
}) {
  return (
    <div
      className={`absolute rounded-[4px] border backdrop-blur-[2px] ${className}`}
      style={{
        background: 'var(--panel-bg)',
        borderColor: 'var(--panel-border)',
        boxShadow: 'var(--panel-glow)',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/** パネル左肩の見出し。縦線アクセント + モノスペース */
export function PanelLabel({ text, color = 'var(--accent)' }: { text: string; color?: string }) {
  return (
    <span className="flex items-center gap-2">
      <span className="h-3.5 w-[2px]" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
      <span className="font-mono whitespace-nowrap text-[11px] font-bold tracking-[0.3em]" style={{ color }}>
        {text}
      </span>
    </span>
  )
}

/** 壁の大型ライブチャート。足は /api/market（Yahoo Finance）から来た本物 */
export function BigChart({
  candles,
  symbol,
  onSymbol,
  interval,
  price,
  prevClose,
  dir,
  ready,
  shocked,
  style,
}: {
  candles: Candle[]
  symbol: string
  onSymbol: (symbol: string) => void
  interval: string
  price: number
  prevClose: number
  dir: number
  ready: boolean
  shocked: boolean
  style?: CSSProperties
}) {
  const W = 520
  const H = 200
  const info = symbolInfo(symbol)
  const fmt = (v: number) => formatMarketPrice(v, info)
  const priceColor = dir >= 0 ? GREEN : RED
  const changePct = prevClose ? ((price - prevClose) / prevClose) * 100 : 0

  const lows = candles.map((k) => k.l)
  const highs = candles.map((k) => k.h)
  const rawLo = lows.length ? Math.min(...lows) : 0
  const rawHi = highs.length ? Math.max(...highs) : 1
  const pad = Math.max((rawHi - rawLo) * 0.08, 1e-9)
  const lo = rawLo - pad
  const hi = rawHi + pad
  const n = Math.max(candles.length, 1)
  const slot = W / n
  const cw = slot * 0.62
  const x = (i: number) => i * slot + (slot - cw) / 2
  const y = (v: number) => H - ((v - lo) / (hi - lo)) * H

  const ma = (len: number) =>
    candles.map((_, i) => {
      const from = Math.max(0, i - (len - 1))
      const slice = candles.slice(from, i + 1)
      return slice.reduce((a, k) => a + k.c, 0) / slice.length
    })
  const ma20 = ma(20)
  const ma5 = ma(5)
  const labels = [0.85, 0.62, 0.38, 0.15].map((t) => lo + (hi - lo) * t)
  const timeAt = (i: number) => {
    const k = candles[i]
    if (!k) return ''
    return new Date(k.t * 1000).toLocaleTimeString('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit' })
  }
  const timeIdx = n >= 8 ? [Math.floor(n * 0.1), Math.floor(n * 0.37), Math.floor(n * 0.64), Math.floor(n * 0.9)] : []
  const intervalLabel = interval === '1h' ? 'H1' : interval === '5m' ? 'M5' : 'M15'

  return (
    <Panel style={style} className={shocked ? 'anim-alarm-border' : ''}>
      <div className="accent-line anim-neon absolute inset-x-4 top-0 h-px" />
      {/* ヘッダー：銘柄・時間足・現在値 */}
      <div className="flex items-baseline gap-3 px-6 pt-3.5">
        <span className="font-dot text-[22px] font-bold tracking-wider text-slate-100">{info.label}</span>
        <span className="font-mono text-[12px] text-slate-400">{intervalLabel}</span>
        <span className="font-mono hidden text-[11px] tracking-[0.2em] lg:inline" style={{ color: '#ffd23e' }}>
          ─ MA20
        </span>
        <span className="font-mono hidden text-[11px] tracking-[0.2em] lg:inline" style={{ color: 'var(--accent)' }}>
          ─ MA5
        </span>
        {ready && (
          <span className="ml-auto flex items-baseline gap-2.5">
            <span
              className="font-mono text-[13px] font-bold tabular-nums"
              style={{ color: changePct >= 0 ? GREEN : RED }}
            >
              {changePct >= 0 ? '+' : ''}
              {changePct.toFixed(2)}%
            </span>
            <span
              className="font-dot text-[26px] font-bold tabular-nums leading-none"
              style={{ color: priceColor, textShadow: `0 0 10px ${priceColor}55` }}
            >
              {dir >= 0 ? '▲' : '▼'} {fmt(price)}
            </span>
          </span>
        )}
      </div>

      {/* 銘柄の切り替え */}
      <div className="mt-2 flex gap-1.5 px-6">
        {CHART_SYMBOLS.map((s) => {
          const on = s.symbol === symbol
          return (
            <button
              key={s.symbol}
              type="button"
              onClick={() => onSymbol(s.symbol)}
              className="font-mono h-11 flex-1 rounded-[3px] border text-[13px] font-bold tracking-wide transition"
              style={{
                borderColor: on ? 'var(--accent)' : 'rgba(94,204,255,0.18)',
                background: on ? 'rgba(94,204,255,0.16)' : 'rgba(8,14,26,0.5)',
                color: on ? '#eaf6ff' : '#8aa0bf',
                boxShadow: on ? '0 0 10px rgba(94,204,255,0.25)' : undefined,
              }}
            >
              {s.label}
            </button>
          )
        })}
      </div>

      <div className="absolute inset-x-6 bottom-8 top-[7.4rem] flex">
        <div className="relative flex-1">
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
            {[0.15, 0.38, 0.62, 0.85].map((t) => (
              <line key={t} x1={0} x2={W} y1={H * (1 - t)} y2={H * (1 - t)} stroke="rgba(94,204,255,0.1)" strokeWidth={1} />
            ))}
            {timeIdx.map((i) => (
              <line key={i} x1={x(i) + cw / 2} x2={x(i) + cw / 2} y1={0} y2={H} stroke="rgba(94,204,255,0.07)" strokeWidth={1} />
            ))}
            {candles.map((k, i) => {
              const up = k.c >= k.o
              const color = up ? GREEN : RED
              const cx = x(i) + cw / 2
              const top = y(Math.max(k.o, k.c))
              const bodyH = Math.max(Math.abs(y(k.o) - y(k.c)), 1.5)
              return (
                <g key={k.t}>
                  <line x1={cx} x2={cx} y1={y(k.h)} y2={y(k.l)} stroke={color} strokeWidth={1.2} />
                  <rect x={x(i)} y={top} width={cw} height={bodyH} fill={up ? 'rgba(47,191,98,0.85)' : 'rgba(224,75,75,0.9)'} />
                </g>
              )
            })}
            {candles.length > 1 && (
              <>
                <polyline
                  points={candles.map((_, i) => `${x(i) + cw / 2},${y(ma5[i])}`).join(' ')}
                  fill="none"
                  stroke="rgba(94,204,255,0.9)"
                  strokeWidth={1.6}
                  strokeLinejoin="round"
                />
                <polyline
                  points={candles.map((_, i) => `${x(i) + cw / 2},${y(ma20[i])}`).join(' ')}
                  fill="none"
                  stroke="#ffd23e"
                  strokeWidth={2.2}
                  strokeLinejoin="round"
                />
              </>
            )}
            {ready && (
              <line x1={0} x2={W} y1={y(price)} y2={y(price)} stroke={priceColor} strokeWidth={1} strokeDasharray="5 4" />
            )}
          </svg>
          {/* 時刻（日本時間） */}
          {timeIdx.map((i) => (
            <span
              key={i}
              className="font-mono absolute top-full mt-1 -translate-x-1/2 text-[12px] text-slate-500"
              style={{ left: `${((x(i) + cw / 2) / W) * 100}%` }}
            >
              {timeAt(i)}
            </span>
          ))}
          {!ready && (
            <p className="font-mono absolute inset-0 flex items-center justify-center text-[13px] tracking-[0.3em] text-slate-500">
              LOADING
            </p>
          )}
        </div>
        {/* 価格軸 */}
        <div className="relative w-[5.2rem]">
          {ready &&
            labels.map((v, i) => (
              <span
                key={i}
                className="font-mono absolute right-0 -translate-y-1/2 text-[13px] text-slate-400"
                style={{ top: `${(1 - (v - lo) / (hi - lo)) * 100}%` }}
              >
                {fmt(v)}
              </span>
            ))}
          {ready && (
            <span
              className="font-mono absolute right-0 -translate-y-1/2 rounded-[3px] px-1.5 py-0.5 text-[13px] font-bold tabular-nums"
              style={{
                top: `${(1 - (price - lo) / (hi - lo)) * 100}%`,
                color: '#081018',
                background: priceColor,
              }}
            >
              {fmt(price)}
            </span>
          )}
        </div>
      </div>
    </Panel>
  )
}

/** スリムなサーバーラック。エンジンルームの背景に並べる */
export function ServerRack({ shocked, tall }: { shocked: boolean; tall?: boolean }) {
  return (
    <div
      className={`relative rounded-[3px] border ${tall ? 'h-28' : 'h-24'} w-10`}
      style={{
        background: 'rgba(13, 22, 40, 0.85)',
        borderColor: 'rgba(94, 204, 255, 0.22)',
        boxShadow: 'inset 0 0 12px rgba(0,0,0,0.6)',
      }}
    >
      <div className="flex h-full flex-col justify-evenly px-1.5">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-1">
            <div
              className={`h-1.5 w-1.5 rounded-full ${shocked ? 'lamp-red' : 'lamp'}`}
              style={{ background: shocked ? RED : '#4ade80', animationDelay: `${i * 0.3}s` }}
            />
            <div className="h-px flex-1 bg-[rgba(94,204,255,0.15)]" />
          </div>
        ))}
      </div>
    </div>
  )
}

/** エンジンルームの状態チップ */
export function StatusMonitor({ shocked }: { shocked: boolean }) {
  return (
    <span
      className={`rounded-[3px] border px-2 py-0.5 font-mono text-[11px] font-bold tracking-[0.2em] ${
        shocked ? 'anim-alarm' : ''
      }`}
      style={{
        borderColor: shocked ? 'rgba(224,75,75,0.6)' : 'rgba(53,245,138,0.4)',
        color: shocked ? '#ff8484' : '#35f58a',
        background: shocked ? undefined : 'rgba(53,245,138,0.06)',
      }}
    >
      {shocked ? '▼ ALERT' : '▲ RUNNING'}
    </span>
  )
}

/** ガレージのコードモニター */
export function CodePanel({ style }: { style?: CSSProperties }) {
  const lines = ['if (ma20 > ma75) {', '  signal = BUY;', '  alert("GOLDEN");', '}', 'plot(rsi, 14);']
  return (
    <Panel style={style}>
      <div className="accent-line anim-neon absolute inset-x-4 top-0 h-px" />
      <div className="px-5 pt-4">
        <PanelLabel text="INDICATOR.SRC" color="#ff9d4d" />
      </div>
      <div className="px-5 pb-4 pt-2 font-mono text-[12px] leading-6 text-[#35f58a]">
        {lines.map((l, i) => (
          <p key={i} className="whitespace-pre">
            <span className="mr-2 select-none text-[#31527a]">{i + 1}</span>
            {l}
          </p>
        ))}
        <span className="cursor-blink inline-block h-3.5 w-2 bg-[#35f58a] align-middle" />
      </div>
    </Panel>
  )
}

/** 机の上の小型モニター */
export function DeskMonitor({ bars }: { bars: number[] }) {
  return (
    <div className="flex flex-col items-center">
      <div
        className="flex h-14 w-28 items-end gap-1 rounded-[3px] border px-2 pb-1.5 pt-2"
        style={{ background: 'var(--panel-bg)', borderColor: 'var(--panel-border)' }}
      >
        {bars.map((h, i) => (
          <div
            key={i}
            className="flex-1"
            style={{ height: `${h}%`, background: i % 3 === 1 ? 'rgba(47,191,98,0.8)' : 'rgba(224,75,75,0.8)' }}
          />
        ))}
      </div>
      <div className="h-2 w-3 bg-[#0a1220]" />
    </div>
  )
}

/** 机。天板＋前板 */
export function Desk({
  style,
  children,
  align = 'center',
}: {
  style?: CSSProperties
  children?: ReactNode
  align?: 'center' | 'right'
}) {
  return (
    <div className="absolute" style={style}>
      {children && (
        <div className={align === 'right' ? 'flex justify-end pr-6' : 'flex justify-center'}>{children}</div>
      )}
      <div className="h-2.5 w-full rounded-t-[3px]" style={{ background: '#33405a', boxShadow: '0 1px 0 rgba(0,0,0,0.5)' }} />
      <div
        className="h-12 w-full"
        style={{ background: '#232d42', backgroundImage: 'linear-gradient(rgba(255,255,255,0.04), transparent 30%)' }}
      />
    </div>
  )
}

/** 工具箱 */
export function ToolBox() {
  return (
    <div className="relative h-9 w-14 rounded-[3px] border border-[#3a1610] bg-[#a03528]">
      <div className="absolute -top-2 left-1/2 h-2 w-7 -translate-x-1/2 rounded-t-[3px] border border-b-0 border-[#3a1610] bg-[#a03528]" />
      <div className="absolute inset-x-2 top-1.5 h-1 bg-[#6b2318]" />
    </div>
  )
}
