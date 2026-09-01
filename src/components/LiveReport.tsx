// 会話ウィンドウの中に出す「実データの表示」。
// 数字はすべてブリッジ（MT5）が返したものをそのまま並べるだけで、ここでは作らない。
import {
  formatDay,
  formatPrice,
  formatSigned,
  formatStamp,
  winRate,
  type HistoryStats,
  type PositionRow,
  type TodayStats,
} from '../data/setupFlow'

export type LiveReport =
  | { kind: 'today'; today: TodayStats; currency?: string }
  | { kind: 'history'; history: HistoryStats; currency?: string }
  | { kind: 'positions'; positions: PositionRow[]; currency?: string }

const GREEN = '#35f58a'
const RED = '#ff8484'

function tone(n: number): string {
  if (n > 0) return GREEN
  if (n < 0) return RED
  return '#cbd5e1'
}

/** 見出し（左に細いシアンの縦棒） */
function Heading({ title, note }: { title: string; note?: string }) {
  return (
    <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="h-3 w-[2px]" style={{ background: 'var(--accent)', boxShadow: '0 0 6px var(--accent)' }} />
      <p className="text-[14px] font-bold text-slate-200">{title}</p>
      {note && <p className="font-mono text-[12px] text-slate-500">{note}</p>}
    </div>
  )
}

/** 「項目 …… 値」の一行 */
function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div
      className="flex items-baseline justify-between gap-4 border-b py-2 last:border-b-0"
      style={{ borderColor: 'rgba(94,204,255,0.12)' }}
    >
      <span className="text-[14px] text-slate-400">{label}</span>
      <span className="font-mono text-[16px] font-bold" style={{ color: color ?? '#e8edf5' }}>
        {value}
      </span>
    </div>
  )
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="step-in rounded-[6px] border px-5 py-4"
      style={{ borderColor: 'rgba(94,204,255,0.28)', background: 'rgba(9,17,31,0.6)' }}
    >
      {children}
    </div>
  )
}

function TodayView({ today, currency }: { today: TodayStats; currency?: string }) {
  const closed = today.today_closed ?? 0
  const profit = today.today_profit ?? 0
  const open = today.open_positions ?? 0
  const floating = today.open_profit ?? 0
  const rate = winRate(today.today_wins ?? 0, closed)
  return (
    <Frame>
      <Heading title="今日の成績" note="MT5の口座履歴より" />
      <Row label="決済した回数" value={`${closed} 回`} />
      <Row label="確定した損益" value={formatSigned(profit, currency)} color={tone(profit)} />
      <Row
        label="勝ち／負け"
        value={`${today.today_wins ?? 0} ／ ${today.today_losses ?? 0}${rate != null ? `（勝率 ${rate}%）` : ''}`}
      />
      <Row label="いまの建玉" value={`${open} 件`} />
      <Row label="建玉の含み損益" value={formatSigned(floating, currency)} color={tone(floating)} />
    </Frame>
  )
}

function HistoryView({ history, currency }: { history: HistoryStats; currency?: string }) {
  const rate = winRate(history.wins, history.closed)
  const daily = history.daily ?? []
  const peak = Math.max(1, ...daily.map((d) => Math.abs(d.profit)))
  const period = history.from && history.to ? `${formatDay(history.from)} 〜 ${formatDay(history.to)}` : undefined

  return (
    <Frame>
      <Heading title={`過去 ${history.days} 日の成績`} note={period} />
      <Row label="決済した回数" value={`${history.closed} 回`} />
      <Row label="確定した損益" value={formatSigned(history.profit, currency)} color={tone(history.profit)} />
      <Row
        label="勝ち／負け"
        value={`${history.wins} ／ ${history.losses}${rate != null ? `（勝率 ${rate}%）` : ''}`}
      />
      <Row label="いちばん取れた取引" value={formatSigned(history.best ?? 0, currency)} color={tone(history.best ?? 0)} />
      <Row label="いちばん損した取引" value={formatSigned(history.worst ?? 0, currency)} color={tone(history.worst ?? 0)} />

      {daily.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-[13px] font-bold text-slate-400">1日ごとの損益</p>
          <div className="max-h-[188px] space-y-1.5 overflow-y-auto pr-1">
            {daily
              .slice()
              .reverse()
              .map((d) => (
                <div key={d.date} className="flex items-center gap-3">
                  <span className="font-mono w-[52px] shrink-0 text-[13px] text-slate-400">{formatDay(d.date)}</span>
                  <span className="h-2 min-w-[2px] rounded-full"
                        style={{
                          width: `${Math.max(2, (Math.abs(d.profit) / peak) * 58)}%`,
                          background: tone(d.profit),
                          boxShadow: `0 0 8px ${tone(d.profit)}55`,
                        }} />
                  <span className="font-mono ml-auto shrink-0 text-[14px] font-bold" style={{ color: tone(d.profit) }}>
                    {formatSigned(d.profit, currency)}
                  </span>
                  <span className="font-mono w-[46px] shrink-0 text-right text-[12px] text-slate-500">{d.closed}回</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </Frame>
  )
}

function PositionsView({ positions, currency }: { positions: PositionRow[]; currency?: string }) {
  if (positions.length === 0) {
    return (
      <Frame>
        <Heading title="いまのポジション" note="MT5の建玉より" />
        <p className="py-2 text-[15px] font-bold text-slate-300">建玉はありません。次の条件がそろうまで待っています。</p>
      </Frame>
    )
  }

  const floating = positions.reduce((sum, r) => sum + (r.profit ?? 0), 0)

  return (
    <Frame>
      <Heading title="いまのポジション" note={`${positions.length} 件・MT5の建玉より`} />
      <div className="max-h-[240px] overflow-y-auto pr-1">
        {positions.map((p) => {
          const buy = p.side === 'buy'
          return (
            <div
              key={p.ticket}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b py-2.5 last:border-b-0"
              style={{ borderColor: 'rgba(94,204,255,0.12)' }}
            >
              <span
                className="rounded-[3px] border px-2 py-0.5 text-[12px] font-bold"
                style={
                  buy
                    ? { borderColor: 'rgba(53,245,138,0.5)', background: 'rgba(53,245,138,0.1)', color: GREEN }
                    : { borderColor: 'rgba(255,132,132,0.5)', background: 'rgba(255,132,132,0.1)', color: RED }
                }
              >
                {buy ? '買い' : '売り'}
              </span>
              <span className="font-mono text-[16px] font-bold text-white">{p.symbol}</span>
              <span className="font-mono text-[14px] text-slate-400">{p.volume} ロット</span>
              <span className="font-mono text-[14px] text-slate-300">
                {formatPrice(p.price_open, p.digits)}
                <span className="mx-1.5 text-slate-500">→</span>
                {formatPrice(p.price_current, p.digits)}
              </span>
              <span className="font-mono ml-auto text-[16px] font-bold" style={{ color: tone(p.profit) }}>
                {formatSigned(p.profit, currency)}
              </span>
              <span className="font-mono w-full text-[12px] text-slate-500">
                {formatStamp(p.opened_at)} に建てた分
                {p.sl ? ` ／ 損切り ${formatPrice(p.sl, p.digits)}` : ''}
                {p.tp ? ` ／ 利確 ${formatPrice(p.tp, p.digits)}` : ''}
              </span>
            </div>
          )
        })}
      </div>
      <div className="mt-3 flex items-baseline justify-between gap-4 border-t pt-3" style={{ borderColor: 'rgba(94,204,255,0.2)' }}>
        <span className="text-[14px] text-slate-400">合計の含み損益</span>
        <span className="font-mono text-[18px] font-bold" style={{ color: tone(floating) }}>
          {formatSigned(floating, currency)}
        </span>
      </div>
    </Frame>
  )
}

export function LiveReportView({ report }: { report: LiveReport }) {
  if (report.kind === 'today') return <TodayView today={report.today} currency={report.currency} />
  if (report.kind === 'history') return <HistoryView history={report.history} currency={report.currency} />
  return <PositionsView positions={report.positions} currency={report.currency} />
}
