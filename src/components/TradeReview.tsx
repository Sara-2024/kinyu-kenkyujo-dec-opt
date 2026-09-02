// トレードの添削。リンが履歴を読んで、クセを言葉にして返す画面。
// 出しているのは口座の履歴から数えた事実だけで、相場の予想はしない。
import { formatSigned } from '../data/setupFlow'
import { formatHeld, type Bucket, type TradeHistory, type TradeReview } from '../data/tradeReview'
import { Bar, Frame, GREEN, Heading, RED, Row, tone } from './reportBits'

function BucketList({ title, rows, currency }: { title: string; rows: Bucket[]; currency?: string }) {
  if (rows.length === 0) return null
  const peak = Math.max(1, ...rows.map((r) => Math.abs(r.profit)))
  return (
    <div className="mt-4">
      <p className="mb-2 text-[13px] font-bold text-slate-400">{title}</p>
      <div className="max-h-[168px] space-y-1.5 overflow-y-auto pr-1">
        {rows.map((r) => (
          <div key={r.key} className="flex items-center gap-3">
            <span className="font-mono w-[68px] shrink-0 text-[13px] text-slate-300">{r.label}</span>
            <Bar ratio={Math.abs(r.profit) / peak} color={tone(r.profit)} />
            <span className="font-mono ml-auto shrink-0 text-[14px] font-bold" style={{ color: tone(r.profit) }}>
              {formatSigned(r.profit, currency)}
            </span>
            <span className="font-mono w-[76px] shrink-0 text-right text-[12px] text-slate-500">
              {r.trades}回 {Math.round((r.wins / Math.max(r.trades, 1)) * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function TradeReviewView({
  review,
  history,
  currency,
}: {
  review: TradeReview | null
  history: TradeHistory
  currency?: string
}) {
  if (!review) {
    return (
      <Frame>
        <Heading title="トレードの添削" note="MT5の約定履歴より" />
        <p className="py-2 text-[15px] font-bold text-slate-300">
          過去{history.days}日ぶんを見ましたが、決済ずみの取引がまだありません。何回か終わってから見てみましょう。
        </p>
      </Frame>
    )
  }

  const good = review.points.filter((p) => p.tone === 'good')
  const watch = review.points.filter((p) => p.tone === 'watch')

  return (
    <Frame>
      <Heading
        title="トレードの添削"
        note={`過去${review.days}日・${review.count}回${history.truncated ? `（全${history.total}回のうち直近ぶん）` : ''}`}
      />

      <Row label="勝率" value={`${review.winRate ?? 0}%（${review.wins}勝 ${review.losses}敗）`} />
      <Row label="合計の損益" value={formatSigned(review.profit, currency)} color={tone(review.profit)} />
      <Row label="1回の平均利益" value={formatSigned(review.avgWin, currency)} color={GREEN} />
      <Row label="1回の平均損失" value={formatSigned(-review.avgLoss, currency)} color={RED} />
      <Row
        label="利益と損失の比"
        value={review.payoff != null ? `${review.payoff} 倍` : '—'}
        color={review.payoff != null ? tone(review.payoff - 1) : undefined}
      />
      <Row label="保有時間（勝ち／負け）" value={`${formatHeld(review.avgHoldWin)} ／ ${formatHeld(review.avgHoldLoss)}`} />
      <Row label="最大の連勝／連敗" value={`${review.maxWinStreak} ／ ${review.maxLossStreak}`} />

      {/* ── 添削のことば ── */}
      {(watch.length > 0 || good.length > 0) && (
        <div className="mt-4 space-y-2.5">
          <p className="text-[13px] font-bold text-slate-400">ここを見ました</p>
          {[...watch, ...good].map((p) => (
            <div
              key={p.title}
              className="step-in rounded-[5px] border px-4 py-3"
              style={
                p.tone === 'good'
                  ? { borderColor: 'rgba(53,245,138,0.35)', background: 'rgba(53,245,138,0.06)' }
                  : { borderColor: 'rgba(250,204,21,0.4)', background: 'rgba(250,204,21,0.06)' }
              }
            >
              <p className="mb-1 flex items-center gap-2 text-[15px] font-bold text-white">
                <span
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[12px] font-bold"
                  style={
                    p.tone === 'good'
                      ? { background: 'rgba(53,245,138,0.15)', color: GREEN, border: `1px solid ${GREEN}80` }
                      : { background: 'rgba(250,204,21,0.12)', color: '#ffd23e', border: '1px solid rgba(250,204,21,0.5)' }
                  }
                >
                  {p.tone === 'good' ? '✓' : '!'}
                </span>
                {p.title}
              </p>
              <p className="text-[14px] leading-relaxed text-slate-300">{p.detail}</p>
            </div>
          ))}
        </div>
      )}

      <BucketList title="銘柄ごと（回数・勝率つき）" rows={review.bySymbol} currency={currency} />
      <BucketList title="建てた時間帯ごと" rows={review.byHour} currency={currency} />
      <BucketList title="曜日ごと" rows={review.byWeekday} currency={currency} />

      <p className="mt-4 text-[12px] leading-relaxed text-slate-500">
        いずれもお客様の口座の約定履歴から数えたものです。過去の成績は将来の成果を約束するものではありません。
      </p>
    </Frame>
  )
}
