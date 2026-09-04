// 研究所の舞台装置（見た目だけ）。
//  - アルゴ管制室のモニターと司令席
//  - 分析デスクの掲示板・机上モニター
//  - 情報センターのカード（ここだけは Web サービスらしいカード UI にする、と決めた場所）
//  - SYSTEM LAB の設備、部屋をつなぐ扉、オーバーレイ
// 数字はすべて useBridge / useMarket が持っている値をそのまま出す。ここでは作らない。
import type { CSSProperties, ReactNode } from 'react'
import { EXTENSIONS, MARKET_SCHEDULE, NOTICES, SCHEDULE_NOTE, type Notice } from '../data/infoCenter'
import { TICKER_SYMBOLS, formatMarketPrice, type Candle, type Quote } from '../data/market'
import { formatSigned, formatStamp, winRate } from '../data/setupFlow'
import type { AlgoReport } from '../hooks/useAlgoReports'
import type { useBridge } from '../hooks/useBridge'
import { Panel, PanelLabel } from './Panels'

type Bridge = ReturnType<typeof useBridge>

export const GREEN = '#35f58a'
export const RED = '#ff8484'
export const YELLOW = '#ffd23e'
const SLATE = '#8aa0bf'

/** ステージ上の文字は、拡縮されるぶん少し大きめに */
const T = { xs: 'text-[11px]', sm: 'text-[13px]', md: 'text-[15px]', lg: 'text-[18px]' }

// ────────────────────────────────
// システムの状態（管制室・名札・情報センターで共通）
// ────────────────────────────────
export interface SystemState {
  key: 'running' | 'stopped' | 'offline' | 'connecting' | 'alert'
  en: string
  jp: string
  color: string
  /** ラックのランプなどを光らせるか */
  active: boolean
}

export function systemStateOf(bridge: Bridge, shocked: boolean): SystemState {
  if (shocked) return { key: 'alert', en: 'ALERT', jp: '急変動', color: RED, active: true }
  if (bridge.live && bridge.status) {
    const running = typeof bridge.status.value === 'number' ? Number(bridge.status.value) !== 0 : false
    return running
      ? { key: 'running', en: 'RUNNING', jp: '稼働中', color: GREEN, active: true }
      : { key: 'stopped', en: 'STOPPED', jp: '停止中', color: YELLOW, active: false }
  }
  if (bridge.phase === 'connecting') return { key: 'connecting', en: 'CONNECTING', jp: '接続中', color: 'var(--accent)', active: false }
  return { key: 'offline', en: 'OFFLINE', jp: '未接続', color: SLATE, active: false }
}

function tone(n: number): string {
  return n > 0 ? GREEN : n < 0 ? RED : '#e8edf5'
}

function hhmm(d: Date): string {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 状態チップ（● RUNNING） */
export function StateChip({ state, big = false }: { state: SystemState; big?: boolean }) {
  return (
    <span
      className={`font-mono inline-flex items-center gap-2 rounded-[3px] border font-bold tracking-[0.2em] ${
        big ? 'px-3 py-1.5 text-[14px]' : 'px-2 py-0.5 text-[11px]'
      } ${state.key === 'alert' ? 'anim-alarm' : ''}`}
      style={{
        borderColor: state.color,
        color: state.color,
        background: state.key === 'alert' ? undefined : 'rgba(9,17,31,0.7)',
        boxShadow: state.active ? `0 0 12px ${state.color}55` : undefined,
      }}
    >
      <span
        className={`inline-block h-2 w-2 rounded-full ${state.active ? 'soft-blink' : ''}`}
        style={{ background: state.color, boxShadow: state.active ? `0 0 6px ${state.color}` : undefined }}
      />
      {state.en}
    </span>
  )
}

// ────────────────────────────────
// アルゴ管制室
// ────────────────────────────────

/** 壁のモニター1枚。中身は与えられたものをそのまま */
function Monitor({
  label,
  color = 'var(--accent)',
  children,
  style,
  className = '',
}: {
  label: string
  color?: string
  children: ReactNode
  style?: CSSProperties
  className?: string
}) {
  return (
    <div className={`absolute ${className}`} style={style}>
      <div
        className="relative overflow-hidden rounded-[4px] border"
        style={{ background: 'rgba(6,12,24,0.92)', borderColor: `${color}66`, boxShadow: `0 0 16px ${color}22, inset 0 0 20px rgba(0,0,0,0.5)` }}
      >
        <div className="accent-line absolute inset-x-3 top-0 h-px" style={{ background: `linear-gradient(90deg, transparent, ${color} 20%, ${color} 80%, transparent)`, boxShadow: `0 0 8px ${color}` }} />
        <div className="scan-line pointer-events-none absolute inset-x-0 top-0 h-6" style={{ background: `linear-gradient(${color}00, ${color}14, ${color}00)` }} />
        <div className="px-3 pb-2.5 pt-2.5">
          <PanelLabel text={label} color={color} />
          <div className="mt-1.5">{children}</div>
        </div>
      </div>
      {/* 壁の取り付け金具 */}
      <div className="mx-auto h-2 w-6" style={{ background: '#0a1220' }} />
    </div>
  )
}

/** 数字を1つ大きく見せる */
function Big({ value, color = '#e8edf5', sub }: { value: string; color?: string; sub?: string }) {
  return (
    <div>
      <p className="font-dot whitespace-nowrap text-[20px] font-bold leading-none tabular-nums" style={{ color, textShadow: `0 0 10px ${color}55` }}>
        {value}
      </p>
      {sub && <p className={`font-mono mt-1.5 ${T.xs} text-slate-500`}>{sub}</p>}
    </div>
  )
}

/**
 * アルゴの頭上に並ぶモニター群。損益・ポジション・稼働状況・トレード。
 * left/width はステージ%。
 */
export function ConsoleMonitors({
  bridge,
  state,
  style,
  reacting = false,
}: {
  bridge: Bridge
  state: SystemState
  style?: CSSProperties
  reacting?: boolean
}) {
  const s = bridge.live ? bridge.status : null
  const today = s?.today
  const cur = s?.currency
  const positions = s?.positions ?? []
  const floating = s?.positions ? positions.reduce((a, r) => a + (r.profit ?? 0), 0) : (today?.open_profit ?? 0)
  const openCount = s?.positions ? positions.length : (today?.open_positions ?? 0)
  const closed = today?.today_closed ?? 0
  const rate = today ? winRate(today.today_wins ?? 0, closed) : null
  const dash = '—'
  const glow = state.color

  return (
    <div className={`absolute ${reacting ? 'hop' : ''}`} style={style}>
      {/* 中央：稼働状況（いちばん目立つ） */}
      <div className="absolute left-1/2 top-0 w-[44%] -translate-x-1/2">
        <div
          className={`relative overflow-hidden rounded-[5px] border px-4 py-3 text-center ${state.key === 'alert' ? 'anim-alarm-border' : ''}`}
          style={{ background: 'rgba(6,12,24,0.94)', borderColor: `${glow}88`, boxShadow: `0 0 26px ${glow}33, inset 0 0 24px rgba(0,0,0,0.5)` }}
        >
          <div className="scan-line pointer-events-none absolute inset-x-0 top-0 h-8" style={{ background: `linear-gradient(${glow}00, ${glow}18, ${glow}00)` }} />
          <p className={`font-mono whitespace-nowrap ${T.xs} tracking-[0.25em] text-slate-400`}>AUTO TRADING SYSTEM</p>
          <p className="font-dot mt-1 text-[30px] font-bold leading-none tracking-wider" style={{ color: glow, textShadow: `0 0 14px ${glow}88` }}>
            {state.en}
          </p>
          <p className={`mt-1.5 ${T.sm} font-bold text-slate-300`}>
            {state.jp}
            {s?.account != null && (
              <span className="font-mono ml-2 font-normal text-slate-500">
                口座 {s.account}
              </span>
            )}
          </p>
        </div>
        <div className="mx-auto h-2 w-8" style={{ background: '#0a1220' }} />
      </div>

      {/* 左：今日の損益 */}
      <Monitor label="今日の損益" color={glow} style={{ left: 0, top: 26, width: '31%' }}>
        <Big
          value={today ? formatSigned(today.today_profit ?? 0, cur) : dash}
          color={today ? tone(today.today_profit ?? 0) : SLATE}
          sub={today ? `決済 ${closed} 回` : state.jp}
        />
      </Monitor>

      {/* 左内：トレード */}
      <Monitor label="トレード" color={glow} style={{ left: '25%', top: 116, width: '24%' }}>
        <Big
          value={today && closed > 0 ? `${today.today_wins ?? 0}勝${today.today_losses ?? 0}敗` : dash}
          color={today && closed > 0 ? '#e8edf5' : SLATE}
          sub={rate != null ? `勝率 ${rate}%` : today ? '本日の決済なし' : state.jp}
        />
      </Monitor>

      {/* 右内：ポジション */}
      <Monitor label="ポジション" color={glow} style={{ left: '51%', top: 116, width: '24%' }}>
        <Big
          value={s ? `${openCount} 件` : dash}
          color={s ? '#e8edf5' : SLATE}
          sub={s ? (openCount > 0 ? `含み損益 ${formatSigned(floating, cur)}` : '待機中') : state.jp}
        />
      </Monitor>

      {/* 右：口座 */}
      <Monitor label="口座" color={glow} style={{ left: '69%', top: 26, width: '31%' }}>
        <Big
          value={s?.equity != null ? formatSigned(s.equity, cur).replace(/^\+/, '') : dash}
          color={s?.equity != null ? '#e8edf5' : SLATE}
          sub={s?.server ? String(s.server) : state.jp}
        />
      </Monitor>
    </div>
  )
}

/** アルゴの専用司令席。半円形のコンソール（真横から見た形） */
export function ConsoleDesk({ state, style }: { state: SystemState; style?: CSSProperties }) {
  return (
    <div className="pointer-events-none absolute" style={style}>
      {/* 天板：手前にせり出した曲面 */}
      <div
        className="h-4 w-full"
        style={{
          background: 'linear-gradient(#4a5a80, #33405f)',
          borderRadius: '50% 50% 4px 4px / 100% 100% 4px 4px',
          boxShadow: '0 2px 0 rgba(0,0,0,0.5)',
        }}
      />
      {/* 前板：操作面。ランプの列 */}
      <div
        className="relative h-14 w-full overflow-hidden"
        style={{
          background: 'linear-gradient(#24304a, #171f34)',
          borderRadius: '0 0 18px 18px / 0 0 40px 40px',
          boxShadow: `inset 0 6px 12px rgba(0,0,0,0.45), 0 0 24px ${state.color}22`,
        }}
      >
        <div className="absolute inset-x-[10%] top-3 h-px" style={{ background: `${state.color}66` }} />
        <div className="absolute inset-x-[14%] top-5 flex justify-between">
          {Array.from({ length: 12 }).map((_, i) => (
            <span
              key={i}
              className={`h-1.5 w-3 rounded-[2px] ${state.active ? 'soft-blink' : ''}`}
              style={{
                background: state.active ? (i % 4 === 3 ? YELLOW : state.color) : '#3b4a66',
                boxShadow: state.active ? `0 0 6px ${state.color}` : undefined,
                animationDelay: `${(i % 5) * 0.3}s`,
              }}
            />
          ))}
        </div>
        <p className="font-mono absolute inset-x-0 bottom-2 text-center text-[10px] tracking-[0.45em] text-slate-500">
          CONTROL CONSOLE
        </p>
      </div>
      {/* 足元の光の帯 */}
      <div className="mx-auto mt-1 h-1 w-[70%] rounded-full" style={{ background: state.color, opacity: state.active ? 0.7 : 0.25, boxShadow: `0 0 14px ${state.color}` }} />
    </div>
  )
}

// ────────────────────────────────
// 分析デスク
// ────────────────────────────────

/** 机上の小型モニター（枠だけ。中身は役割ごとに渡す） */
export function DeskScreen({ label, color = 'var(--accent)', children }: { label: string; color?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center">
      <div
        className="relative h-16 w-32 overflow-hidden rounded-[3px] border"
        style={{ background: 'rgba(6,12,24,0.92)', borderColor: `${color}66`, boxShadow: `0 0 10px ${color}22` }}
      >
        <p className="font-mono absolute left-1.5 top-1 text-[8px] tracking-[0.25em]" style={{ color }}>
          {label}
        </p>
        <div className="absolute inset-x-1.5 bottom-1.5 top-4">{children}</div>
      </div>
      <div className="h-2 w-3 bg-[#0a1220]" />
    </div>
  )
}

/** リンの机上：いま壁に出している銘柄の終値の線（本物の足） */
export function Sparkline({ candles, color = 'var(--accent)' }: { candles: Candle[]; color?: string }) {
  if (candles.length < 2) return null
  const closes = candles.map((k) => k.c)
  const lo = Math.min(...closes)
  const hi = Math.max(...closes)
  const span = hi - lo || 1
  const W = 100
  const H = 40
  const pts = closes.map((c, i) => `${(i / (closes.length - 1)) * W},${H - ((c - lo) / span) * H}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  )
}

/** ジンの机上：主要レートを2つ */
export function MiniRates({ quotes }: { quotes: Quote[] }) {
  const byId = new Map(quotes.map((q) => [q.symbol, q]))
  const rows = TICKER_SYMBOLS.slice(0, 2).map((info) => ({ info, q: byId.get(info.symbol) })).filter((r) => r.q)
  return (
    <div className="flex h-full flex-col justify-center gap-0.5">
      {rows.map(({ info, q }) => (
        <p key={info.symbol} className="font-mono flex justify-between text-[9px] leading-tight">
          <span className="text-slate-400">{info.label}</span>
          <span className="tabular-nums font-bold" style={{ color: q!.changePct >= 0 ? GREEN : RED }}>
            {formatMarketPrice(q!.price, info)}
          </span>
        </p>
      ))}
    </div>
  )
}

/** ジンの壁：為替レートと、定例イベントの掲示板 */
export function MarketBoard({ quotes, style, color = YELLOW }: { quotes: Quote[]; style?: CSSProperties; color?: string }) {
  const byId = new Map(quotes.map((q) => [q.symbol, q]))
  const rows = TICKER_SYMBOLS.slice(0, 5).map((info) => ({ info, q: byId.get(info.symbol) })).filter((r) => r.q)
  const events = MARKET_SCHEDULE
  return (
    <Panel style={style}>
      <div className="accent-line anim-neon absolute inset-x-4 top-0 h-px" style={{ background: `linear-gradient(90deg, transparent, ${color} 18%, ${color} 82%, transparent)`, boxShadow: `0 0 8px ${color}` }} />
      <div className="px-4 pt-3">
        <PanelLabel text="RATES ／ 為替レート" color={color} />
      </div>
      <div className="px-4 pt-2">
        {rows.length === 0 && <p className={`font-mono ${T.xs} tracking-[0.3em] text-slate-500`}>LOADING</p>}
        {rows.map(({ info, q }) => {
          const up = q!.changePct >= 0
          return (
            <p key={info.symbol} className="font-mono flex items-baseline justify-between border-b py-1 text-[12px] last:border-b-0" style={{ borderColor: 'rgba(94,204,255,0.1)' }}>
              <span className="text-slate-400">{info.label}</span>
              <span className="tabular-nums font-bold text-slate-100">{formatMarketPrice(q!.price, info)}</span>
              <span className="w-14 text-right tabular-nums text-[11px]" style={{ color: up ? GREEN : RED }}>
                {up ? '▲' : '▼'} {Math.abs(q!.changePct).toFixed(2)}%
              </span>
            </p>
          )
        })}
      </div>
      <div className="mt-2 px-4">
        <PanelLabel text="EVENTS ／ 定例の指標" color={color} />
      </div>
      <div className="relative mx-4 mt-1 h-[72px] overflow-hidden">
        <div className="anim-vscroll">
          {[...events, ...events].map((e, i) => (
            <p key={i} className="flex items-baseline gap-2 py-1 text-[12px] leading-tight">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: e.impact === 'high' ? RED : color }} />
              <span className="truncate font-bold text-slate-200">{e.name}</span>
              <span className="font-mono ml-auto shrink-0 text-[11px] text-slate-500">{e.when}</span>
            </p>
          ))}
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-5" style={{ background: 'linear-gradient(transparent, rgba(9,17,31,0.95))' }} />
      </div>
      <div className="h-3" />
    </Panel>
  )
}

/** 各研究員の担当を、機材の上に小さく掲げる札 */
export function RoleTag({ name, role, color, style }: { name: string; role: string; color: string; style?: CSSProperties }) {
  return (
    <div className="absolute z-20 flex items-center gap-2" style={style}>
      <span className="h-3.5 w-[2px]" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
      <span className="font-dot whitespace-nowrap text-[13px] font-bold tracking-wider" style={{ color }}>
        {name}
      </span>
      <span className={`whitespace-nowrap ${T.sm} font-bold text-slate-300`}>{role}</span>
    </div>
  )
}

// ────────────────────────────────
// 情報センター（カード UI）
// ────────────────────────────────

function Card({
  title,
  color = 'var(--accent)',
  onClick,
  children,
  className = '',
}: {
  title: string
  color?: string
  onClick?: () => void
  children: ReactNode
  className?: string
}) {
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      className={`info-card block w-full rounded-[6px] border text-left ${className}`}
      style={{ background: 'rgba(9,17,31,0.9)', borderColor: `${color}55`, boxShadow: `0 0 14px ${color}14` }}
    >
      <div className="flex items-center justify-between px-3 pt-2.5">
        <PanelLabel text={title} color={color} />
        {onClick && <span className="font-mono text-[10px] tracking-[0.2em] text-slate-500">詳しく ▶</span>}
      </div>
      <div className="px-3 pb-2.5 pt-1.5">{children}</div>
    </Tag>
  )
}

const TAG_COLOR: Record<Notice['tag'], string> = { お知らせ: 'var(--accent)', アップデート: GREEN, 予定: YELLOW }

export function InfoCenter({
  bridge,
  state,
  reports,
  quotes,
  onOpen,
  style,
}: {
  bridge: Bridge
  state: SystemState
  reports: AlgoReport[]
  quotes: Quote[]
  onOpen: (what: 'reports' | 'notices' | 'market') => void
  style?: CSSProperties
}) {
  const s = bridge.live ? bridge.status : null
  const positions = s?.positions ?? []
  const trades = reports.filter((r) => r.kind === 'trade').slice(0, 3)
  const byId = new Map(quotes.map((q) => [q.symbol, q]))
  const rates = TICKER_SYMBOLS.slice(0, 3).map((info) => ({ info, q: byId.get(info.symbol) })).filter((r) => r.q)

  return (
    <div className="absolute flex flex-col gap-2" style={style}>
      <Card title="SYSTEM STATUS" color={state.color}>
        <div className="flex items-center justify-between gap-2">
          <p className={`${T.sm} font-bold text-slate-200`}>自動売買 {state.jp}</p>
          <StateChip state={state} />
        </div>
        {s?.account != null ? (
          <p className={`font-mono mt-1 ${T.xs} text-slate-500`}>
            口座 {s.account}{s.server ? ` ／ ${s.server}` : ''}
            {s.version ? ` ／ 版 ${s.version}` : ''}
          </p>
        ) : (
          <p className={`mt-1 ${T.xs} text-slate-500`}>アルゴの「自動売買をはじめる」で接続します</p>
        )}
      </Card>

      <Card title="TRADE LOG" color={GREEN} onClick={() => onOpen('reports')}>
        {trades.length === 0 && positions.length === 0 && (
          <p className={`${T.xs} leading-relaxed text-slate-500`}>
            {!s
              ? 'MT5とつながると、取引がここに並びます。'
              : (s.today?.today_closed ?? 0) > 0
                ? `本日は決済 ${s.today?.today_closed} 回（${formatSigned(s.today?.today_profit ?? 0, s.currency)}）。次の決済からここに並びます。`
                : '本日の決済はまだありません。決済があるとここに並びます。'}
          </p>
        )}
        {positions.slice(0, 2).map((p) => (
          <p key={p.ticket} className="font-mono flex items-baseline gap-2 py-0.5 text-[12px]">
            <span className="text-slate-500">{p.opened_at ? formatStamp(p.opened_at).slice(-5) : '--:--'}</span>
            <span className="font-bold text-slate-100">{p.symbol}</span>
            <span style={{ color: p.side === 'buy' ? GREEN : RED }}>{p.side === 'buy' ? 'BUY' : 'SELL'}</span>
            <span className="ml-auto tabular-nums font-bold" style={{ color: tone(p.profit) }}>
              {formatSigned(p.profit, s?.currency)}
            </span>
          </p>
        ))}
        {trades.map((r) => (
          <p key={r.id} className="flex items-baseline gap-2 py-0.5 text-[12px] leading-tight">
            <span className="font-mono text-slate-500">{hhmm(r.at)}</span>
            <span className="truncate font-bold" style={{ color: r.tone === 'good' ? GREEN : r.tone === 'bad' ? RED : '#e8edf5' }}>
              {r.text}
            </span>
          </p>
        ))}
      </Card>

      <Card title="MARKET" color={YELLOW} onClick={() => onOpen('market')}>
        {rates.map(({ info, q }) => (
          <p key={info.symbol} className="font-mono flex items-baseline justify-between py-0.5 text-[12px]">
            <span className="text-slate-400">{info.label}</span>
            <span className="tabular-nums font-bold text-slate-100">{formatMarketPrice(q!.price, info)}</span>
            <span className="w-12 text-right text-[11px]" style={{ color: q!.changePct >= 0 ? GREEN : RED }}>
              {q!.changePct >= 0 ? '▲' : '▼'}{Math.abs(q!.changePct).toFixed(2)}%
            </span>
          </p>
        ))}
        <p className={`mt-1 flex items-baseline gap-2 ${T.xs} text-slate-400`}>
          <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: RED }} />
          <span className="truncate">{MARKET_SCHEDULE[0].name}</span>
          <span className="font-mono ml-auto shrink-0 text-slate-500">{MARKET_SCHEDULE[0].when}</span>
        </p>
      </Card>

      <Card title="NOTICE" onClick={() => onOpen('notices')}>
        {NOTICES.slice(0, 3).map((n) => (
          <p key={n.title} className="flex items-baseline gap-2 py-0.5 text-[12px] leading-tight">
            <span className="font-mono shrink-0 text-[10px]" style={{ color: TAG_COLOR[n.tag] }}>
              {n.tag}
            </span>
            <span className="truncate text-slate-200">{n.title}</span>
          </p>
        ))}
      </Card>
    </div>
  )
}

// ────────────────────────────────
// 扉（部屋の行き来）
// ────────────────────────────────
export function Door({
  label,
  sub,
  color,
  onClick,
  style,
  arrow = 'right',
}: {
  label: string
  sub: string
  color: string
  onClick: () => void
  style?: CSSProperties
  arrow?: 'left' | 'right'
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="door absolute z-20 flex flex-col items-center border-0 bg-transparent p-0"
      style={style}
      aria-label={label}
    >
      <div
        className={`mb-1.5 whitespace-nowrap rounded-[3px] border px-2.5 py-1 font-mono ${T.xs} font-bold tracking-[0.2em]`}
        style={{ borderColor: color, color, background: 'rgba(9,17,31,0.9)', boxShadow: `0 0 10px ${color}55` }}
      >
        {arrow === 'left' ? '◀ ' : ''}
        {label}
        {arrow === 'right' ? ' ▶' : ''}
      </div>
      <div
        className="relative h-[150px] w-[76px] rounded-t-[6px] border"
        style={{ background: 'linear-gradient(#111a2e, #0b1222)', borderColor: `${color}88`, boxShadow: `inset 0 0 30px ${color}22, 0 0 18px ${color}22` }}
      >
        <div className="absolute inset-x-2 top-2 h-px" style={{ background: `${color}88` }} />
        <div className="absolute inset-x-3 top-5 bottom-3 rounded-[3px]" style={{ background: `linear-gradient(${color}22, transparent 60%)` }} />
        <span className="absolute right-3 top-1/2 h-4 w-1.5 rounded-full" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
      </div>
      <p className={`mt-1.5 whitespace-nowrap ${T.sm} font-bold text-slate-200`}>{sub}</p>
    </button>
  )
}

// ────────────────────────────────
// SYSTEM LAB（ガンツの部屋）
// ────────────────────────────────
const EXT_COLOR: Record<string, string> = { 稼働中: GREEN, 開発中: YELLOW, 予定: SLATE }

/** ブリッジが名乗るシステム名（ea_name が無ければコンパイル済み EA の先頭） */
export function systemName(s: Bridge['status']): string | null {
  if (!s) return null
  if (s.ea_name) return String(s.ea_name)
  if (s.ea_compiled?.length) return s.ea_compiled[0]
  return null
}

export function SystemBoard({
  bridge,
  state,
  style,
  color,
  part,
}: {
  bridge: Bridge
  state: SystemState
  style?: CSSProperties
  color: string
  part: 'system' | 'extensions'
}) {
  const s = bridge.live ? bridge.status : null
  const rows: Array<[string, string]> = [
    ['稼働状況', state.jp],
    ['システム', systemName(s) ?? '—'],
    ['接続ツール', s?.version ? `版 ${s.version}` : '—'],
    ['MT5', s?.build ? `${s.terminal_name ?? 'MetaTrader 5'} build ${s.build}` : '—'],
    ['口座', s?.account != null ? `${s.account}${s.server ? ` ／ ${s.server}` : ''}` : '—'],
  ]
  return (
    <Panel style={style}>
      <div className="accent-line anim-neon absolute inset-x-4 top-0 h-px" style={{ background: `linear-gradient(90deg, transparent, ${color} 18%, ${color} 82%, transparent)`, boxShadow: `0 0 8px ${color}` }} />
      {part === 'system' ? (
        <>
          <div className="px-4 pt-3">
            <PanelLabel text="SYSTEM ／ いまの構成" color={color} />
          </div>
          <div className="px-4 pb-3 pt-1.5">
            {rows.map(([k, v]) => (
              <p key={k} className="flex items-baseline justify-between gap-3 border-b py-2 text-[13px] last:border-b-0" style={{ borderColor: 'rgba(94,204,255,0.1)' }}>
                <span className="shrink-0 text-slate-400">{k}</span>
                <span className="font-mono truncate font-bold text-slate-100">{v}</span>
              </p>
            ))}
          </div>
        </>
      ) : (
        <>
          <div className="px-4 pt-3">
            <PanelLabel text="EXTENSIONS ／ 拡張機能" color={color} />
          </div>
          <div className="px-4 pb-3 pt-1.5">
            {EXTENSIONS.map((e) => (
              <div key={e.name} className="border-b py-2 last:border-b-0" style={{ borderColor: 'rgba(94,204,255,0.1)' }}>
                <p className="flex items-baseline gap-2 text-[13px] leading-tight">
                  <span className="font-mono shrink-0 rounded-[2px] border px-1 text-[10px]" style={{ borderColor: EXT_COLOR[e.state], color: EXT_COLOR[e.state] }}>
                    {e.state}
                  </span>
                  <span className="font-bold text-slate-200">{e.name}</span>
                </p>
                <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{e.desc}</p>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  )
}

// ────────────────────────────────
// オーバーレイ（チャート拡大・通知履歴・お知らせ・相場予定）
// ────────────────────────────────
export function Overlay({
  title,
  sub,
  onClose,
  children,
  width = 'min(92vw, 1100px)',
}: {
  title: string
  sub?: string
  onClose: () => void
  children: ReactNode
  width?: string
}) {
  return (
    <div
      className="fade-in absolute inset-0 z-[45] flex items-center justify-center p-4"
      style={{ background: 'rgba(3,6,13,0.72)', backdropFilter: 'blur(3px)' }}
      onClick={onClose}
      role="presentation"
    >
      <div
        className="pop-in relative flex max-h-[calc(100vh-40px)] flex-col rounded-[8px] border"
        style={{ width, background: 'rgba(7,14,27,0.96)', borderColor: 'var(--panel-border)', boxShadow: '0 0 40px rgba(94,204,255,0.18), 0 20px 60px rgba(0,0,0,0.6)' }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={title}
      >
        <div className="accent-line h-px w-full rounded-t-[8px]" />
        <div className="flex shrink-0 items-center gap-3 border-b px-5 py-3" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
          <span className="h-4 w-[2px]" style={{ background: 'var(--accent)', boxShadow: '0 0 8px var(--accent)' }} />
          <p className="text-[17px] font-bold text-white">{title}</p>
          {sub && <p className="font-mono text-[12px] text-slate-500">{sub}</p>}
          <button
            type="button"
            onClick={onClose}
            aria-label="閉じる"
            className="ml-auto flex h-11 w-11 items-center justify-center rounded-[4px] border text-[18px] font-bold text-slate-300 transition hover:brightness-150"
            style={{ borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.6)' }}
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  )
}

export function ReportsList({ reports, name }: { reports: AlgoReport[]; name: string }) {
  if (reports.length === 0) {
    return (
      <p className="px-6 py-8 text-center text-[16px] font-bold text-slate-400">
        まだ報告はありません。MT5とつながると、{name}がここに運用報告を残していきます。
      </p>
    )
  }
  return (
    <ul className="px-6 py-3">
      {reports.map((r) => (
        <li key={r.id} className="flex items-baseline gap-4 border-b py-3 last:border-b-0" style={{ borderColor: 'rgba(94,204,255,0.12)' }}>
          <span className="font-mono shrink-0 text-[14px] text-slate-500">{hhmm(r.at)}</span>
          <span
            className="font-mono shrink-0 rounded-[3px] border px-1.5 text-[11px]"
            style={{ borderColor: r.kind === 'trade' ? GREEN : r.kind === 'system' ? YELLOW : 'rgba(148,163,184,0.5)', color: r.kind === 'trade' ? GREEN : r.kind === 'system' ? YELLOW : '#94a3b8' }}
          >
            {r.kind === 'trade' ? '決済' : r.kind === 'system' ? 'システム' : '定期'}
          </span>
          <span className="text-[16px] font-bold leading-relaxed" style={{ color: r.tone === 'good' ? GREEN : r.tone === 'bad' ? RED : '#e8edf5' }}>
            {r.text}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function NoticesList() {
  const groups: Notice['tag'][] = ['お知らせ', 'アップデート', '予定']
  return (
    <div className="px-6 py-4">
      {groups.map((tag) => {
        const rows = NOTICES.filter((n) => n.tag === tag)
        if (rows.length === 0) return null
        return (
          <section key={tag} className="mb-5 last:mb-0">
            <PanelLabel text={tag === 'お知らせ' ? 'NOTICE ／ お知らせ' : tag === 'アップデート' ? 'UPDATE ／ アップデート情報' : 'ROADMAP ／ 今後の予定'} color={TAG_COLOR[tag]} />
            <ul className="mt-2">
              {rows.map((n) => (
                <li key={n.title} className="border-b py-3 last:border-b-0" style={{ borderColor: 'rgba(94,204,255,0.12)' }}>
                  <p className="flex items-baseline gap-3">
                    {n.date && <span className="font-mono text-[13px] text-slate-500">{n.date.replace(/-/g, '/')}</span>}
                    <span className="text-[16px] font-bold text-white">{n.title}</span>
                  </p>
                  <p className="mt-1 text-[15px] leading-relaxed text-slate-300">{n.body}</p>
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

export function ScheduleList({ quotes }: { quotes: Quote[] }) {
  const byId = new Map(quotes.map((q) => [q.symbol, q]))
  const rows = TICKER_SYMBOLS.map((info) => ({ info, q: byId.get(info.symbol) })).filter((r) => r.q)
  return (
    <div className="px-6 py-4">
      <PanelLabel text="RATES ／ 為替・指数" color={YELLOW} />
      <div className="mt-2 grid grid-cols-2 gap-x-8 md:grid-cols-3">
        {rows.map(({ info, q }) => {
          const up = q!.changePct >= 0
          return (
            <p key={info.symbol} className="font-mono flex items-baseline justify-between border-b py-2 text-[15px]" style={{ borderColor: 'rgba(94,204,255,0.12)' }}>
              <span className="text-slate-400">{info.label}</span>
              <span className="tabular-nums font-bold text-slate-100">{formatMarketPrice(q!.price, info)}</span>
              <span className="w-16 text-right text-[13px]" style={{ color: up ? GREEN : RED }}>
                {up ? '▲' : '▼'} {Math.abs(q!.changePct).toFixed(2)}%
              </span>
            </p>
          )
        })}
      </div>
      <div className="mt-5">
        <PanelLabel text="EVENTS ／ 定例の経済指標" color={YELLOW} />
      </div>
      <ul className="mt-2">
        {MARKET_SCHEDULE.map((e) => (
          <li key={e.name} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b py-3 last:border-b-0" style={{ borderColor: 'rgba(94,204,255,0.12)' }}>
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: e.impact === 'high' ? RED : YELLOW }} />
            <span className="text-[16px] font-bold text-white">{e.name}</span>
            <span className="font-mono text-[14px] text-slate-400">{e.when}</span>
            <span className="text-[14px] text-slate-500">{e.note}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[13px] text-slate-500">{SCHEDULE_NOTE} 表示レートは配信の都合により実際と異なる場合があります。</p>
    </div>
  )
}
