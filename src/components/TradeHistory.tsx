// 取引履歴の画面。
//
// アルゴがその場で残した報告ではなく、MT5 の口座履歴そのものを出す。
// 画面を開いていなかった間の取引も、ここには全部並ぶ。
//
// 数字は作らない。ブリッジが MT5 から返した値だけを並べる。
import { useCallback, useEffect, useRef, useState } from 'react'
import { GREEN, RED, tone } from './reportBits'
import { formatSigned, formatStamp, winRate } from '../data/setupFlow'
import type { Trade, TradeHistory as TradeHistoryData } from '../data/tradeReview'
import type { useBridge } from '../hooks/useBridge'
import { TRADE_HISTORY } from '../data/characters'

/** 一覧に出す日数と件数。増やすと MT5 への問い合わせが重くなる */
const DAYS = 30
const LIMIT = 200

function Cell({
  children,
  className = '',
  style,
}: {
  children: React.ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <td className={`whitespace-nowrap py-2.5 pr-4 text-[15px] ${className}`} style={style}>
      {children}
    </td>
  )
}

function Summary({ history, currency }: { history: TradeHistoryData; currency?: string }) {
  const rows = history.trades
  const profit = rows.reduce((a, t) => a + t.profit, 0)
  const wins = rows.filter((t) => t.profit > 0).length
  const losses = rows.filter((t) => t.profit < 0).length
  const rate = winRate(wins, rows.length)

  return (
    <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 border-b px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.15)' }}>
      <span className="text-[13px] text-slate-400">
        {TRADE_HISTORY.period.replace('{days}', String(history.days))}
        {history.truncated && (
          <span className="ml-2 text-[12px] text-slate-500">
            {TRADE_HISTORY.truncated.replace('{total}', String(history.total)).replace('{shown}', String(rows.length))}
          </span>
        )}
      </span>
      <span className="text-[15px] text-slate-300">
        {TRADE_HISTORY.closedLabel}
        <span className="font-mono ml-2 text-[19px] font-bold text-white tabular-nums">{rows.length}</span>
        <span className="ml-1 text-[13px] text-slate-400">回</span>
      </span>
      <span className="text-[15px] text-slate-300">
        {TRADE_HISTORY.profitLabel}
        <span className="font-mono ml-2 text-[19px] font-bold tabular-nums" style={{ color: tone(profit) }}>
          {formatSigned(profit, currency)}
        </span>
      </span>
      <span className="text-[15px] text-slate-300">
        {TRADE_HISTORY.winLossLabel}
        <span className="font-mono ml-2 text-[17px] font-bold text-white tabular-nums">
          {wins} ／ {losses}
        </span>
        {rate != null && <span className="ml-1 text-[13px] text-slate-400">（勝率 {rate}%）</span>}
      </span>
    </div>
  )
}

function Rows({ trades, currency }: { trades: Trade[]; currency?: string }) {
  return (
    // 横に広い表なので、狭い画面では表だけ横に流す（画面そのものは横に動かさない）
    <div className="overflow-x-auto px-6 pb-4">
      <table className="w-full min-w-[620px] border-collapse text-left">
        <thead>
          <tr className="border-b" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            {TRADE_HISTORY.columns.map((c, i) => (
              <th
                key={c}
                className={`whitespace-nowrap pb-2 pr-4 text-[13px] font-bold text-slate-400 ${i >= 4 ? 'text-right' : ''}`}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id} className="border-b last:border-b-0" style={{ borderColor: 'rgba(94,204,255,0.09)' }}>
              <Cell className="font-mono text-slate-400">{formatStamp(t.closed_at)}</Cell>
              <Cell className="font-bold text-slate-100">{t.symbol}</Cell>
              <Cell>
                <span className="font-mono font-bold" style={{ color: t.side === 'buy' ? GREEN : RED }}>
                  {t.side === 'buy' ? '買い' : '売り'}
                </span>
              </Cell>
              <Cell className="font-mono text-slate-300 tabular-nums">{t.volume.toFixed(2)}</Cell>
              <Cell className="font-mono text-right text-slate-400 tabular-nums">
                {t.open_price > 0 ? t.open_price.toFixed(t.digits ?? 2) : '—'}
              </Cell>
              <Cell className="font-mono text-right text-slate-400 tabular-nums">
                {t.close_price > 0 ? t.close_price.toFixed(t.digits ?? 2) : '—'}
              </Cell>
              <Cell className="font-mono text-right font-bold tabular-nums" style={{ color: tone(t.profit) }}>
                {formatSigned(t.profit, currency)}
              </Cell>
              <Cell className="text-right text-[13px] text-slate-500">
                {t.by_system ? TRADE_HISTORY.bySystem : TRADE_HISTORY.byHand}
              </Cell>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function TradeHistoryView({ bridge }: { bridge: ReturnType<typeof useBridge> }) {
  const [history, setHistory] = useState<TradeHistoryData | null>(null)
  const [currency, setCurrency] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  // useBridge は再描画のたびに新しい入れ物を返す。そのまま useCallback の
  // 依存に置くと、Lab が 450ms ごとに描き直す都合で load が作り直され、
  // MT5 へ問い合わせ続けてしまう。中身は ref 越しに見る。
  const bridgeRef = useRef(bridge)
  bridgeRef.current = bridge

  const load = useCallback(async () => {
    const b = bridgeRef.current
    if (!b.live) return
    setLoading(true)
    setFailed(null)
    const ack = await b.send('get_trades', { days: DAYS, limit: LIMIT })
    setLoading(false)
    if (!ack.ok || !ack.trades) {
      setFailed(ack.error ?? TRADE_HISTORY.failed)
      return
    }
    setHistory(ack.trades)
    setCurrency(ack.currency)
  }, [])

  // 開いたときに一度だけ取りに行く。あとは「最新にする」を押したときだけ。
  // （つながっていない状態で開いたときのために、つながった瞬間も一度取る）
  useEffect(() => {
    if (!bridge.live) return
    void load()
  }, [bridge.live, load])

  if (!bridge.live) {
    return <p className="px-6 py-10 text-center text-[16px] font-bold text-slate-400">{TRADE_HISTORY.offline}</p>
  }
  if (loading && !history) {
    return <p className="px-6 py-10 text-center text-[16px] font-bold text-slate-400">{TRADE_HISTORY.loading}</p>
  }
  if (failed && !history) {
    return (
      <div className="px-6 py-10 text-center">
        <p className="text-[16px] font-bold text-[#ff8484]">⚠ {failed}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-4 h-11 rounded-[5px] border px-6 text-[15px] font-bold text-slate-100 transition hover:brightness-150"
          style={{ borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.8)' }}
        >
          {TRADE_HISTORY.retry}
        </button>
      </div>
    )
  }
  if (!history || history.trades.length === 0) {
    return (
      <div className="px-6 py-10 text-center">
        <p className="text-[16px] font-bold text-slate-400">
          {TRADE_HISTORY.empty.replace('{days}', String(history?.days ?? DAYS))}
        </p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-4 h-11 rounded-[5px] border px-6 text-[15px] font-bold text-slate-100 transition hover:brightness-150"
          style={{ borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.8)' }}
        >
          {TRADE_HISTORY.reload}
        </button>
      </div>
    )
  }

  return (
    <div>
      <Summary history={history} currency={currency} />
      <Rows trades={history.trades} currency={currency} />
      <div className="px-6 pb-5">
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="h-11 rounded-[5px] border px-6 text-[15px] font-bold text-slate-100 transition hover:brightness-150 disabled:opacity-40"
          style={{ borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.8)' }}
        >
          {loading ? TRADE_HISTORY.loading : TRADE_HISTORY.reload}
        </button>
      </div>
    </div>
  )
}
