// 管理者画面「口座と損益」: 口座ごとのトータル損益・入金・出金と、いま持っているポジション。
// 数字はすべてパスポートが MT5 から読んで中継に預けたもの（画面では作らない）。
//   トータル損益 ＝ 有効証拠金 − クレジット − 入金 ＋ 出金（含み損益も入った、いまの時点の損益）
//   入金・出金   ＝ MT5 の履歴の「入出金」の合計（取引の損益・ボーナスは入れない）
// 入金・出金は新しいパスポート（2026-11-19 以降）だけが送る。古いパスポートの口座は「—」。
import type { Member } from '../data/auth'
import type { RoomState } from '../hooks/useFleet'
import { PLAN_NAMES, isSubscriptionAccount, type MemberPlan } from '../data/subscription'

const money = (v: unknown, currency?: string) => {
  if (typeof v !== 'number' || Number.isNaN(v)) return '—'
  const digits = currency === 'JPY' ? 0 : 2
  return v.toLocaleString('ja-JP', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
const signed = (v: unknown, currency?: string) => (typeof v === 'number' && v > 0 ? `+${money(v, currency)}` : money(v, currency))
const tone = (v: unknown) => (typeof v !== 'number' || v === 0 ? '#e2e8f0' : v > 0 ? 'var(--accent)' : '#ff8484')

export function AccountsPnL({ rows, states }: { rows: Member[]; states: Record<string, RoomState> }) {
  const list = rows.filter((r) => r.role !== 'admin')
  return (
    <div className="mt-5 overflow-x-auto rounded-[4px] border" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
      <table className="w-full min-w-[1000px] text-left text-[15px]">
        <thead>
          <tr className="border-b text-[14px] text-slate-400" style={{ borderColor: 'var(--panel-border)' }}>
            <th className="px-3 py-2">お名前・口座</th>
            <th className="px-3 py-2">プラン</th>
            <th className="px-3 py-2 text-right">トータル損益</th>
            <th className="px-3 py-2 text-right">入金</th>
            <th className="px-3 py-2 text-right">出金</th>
            <th className="px-3 py-2 text-right">残高</th>
            <th className="px-3 py-2">ポジション</th>
          </tr>
        </thead>
        <tbody>
          {list.map((row) => {
            const st = states[row.id]
            const s = st?.status ?? null
            const cur = s?.currency
            const funds = s?.funds ?? null
            const positions = s?.positions ?? []
            const sub = isSubscriptionAccount(row.plan, s)
            const plan = (row.plan ?? (sub ? 'subscription' : null)) as MemberPlan | null
            return (
              <tr key={row.id} className="border-b align-top" style={{ borderColor: 'rgba(94,204,255,0.12)', opacity: st?.online ? 1 : 0.6 }}>
                <td className="px-3 py-3">
                  {row.name || '—'}
                  <span className="block font-mono text-[14px] text-slate-400">
                    {row.account ?? (s?.account as number | undefined) ?? '—'}
                    {cur ? `（${cur}）` : ''}
                  </span>
                  {!st?.online && <span className="block text-[13px] text-slate-500">パスポート未接続（最後に届いた値）</span>}
                </td>
                <td className="px-3 py-3 text-[14px]" style={{ color: sub ? '#f4c46a' : '#e2e8f0' }}>
                  {plan ? PLAN_NAMES[plan] : '—'}
                </td>
                <td className="px-3 py-3 text-right font-bold" style={{ color: tone(funds?.total_profit) }}>
                  {funds ? signed(funds.total_profit, cur) : s ? <span className="text-[13px] font-normal text-slate-500">パスポートの更新で表示</span> : '—'}
                </td>
                <td className="px-3 py-3 text-right">{funds ? money(funds.deposit, cur) : '—'}</td>
                <td className="px-3 py-3 text-right">{funds && funds.withdrawal ? money(funds.withdrawal, cur) : funds ? 'なし' : '—'}</td>
                <td className="px-3 py-3 text-right text-slate-300">{money(s?.balance, cur)}</td>
                <td className="px-3 py-3">
                  {positions.length === 0 ? (
                    <span className="text-slate-500">{s ? 'なし' : '—'}</span>
                  ) : (
                    <ul className="space-y-1">
                      {positions.map((p) => (
                        <li key={p.ticket} className="flex flex-wrap items-center gap-2 text-[14px]">
                          <span
                            className="inline-flex h-6 items-center rounded-[3px] px-2 text-[13px] font-bold"
                            style={{ background: p.side === 'buy' ? 'rgba(94,204,255,0.18)' : 'rgba(255,132,132,0.18)', color: p.side === 'buy' ? 'var(--accent)' : '#ff8484' }}
                          >
                            {p.side === 'buy' ? '買い' : '売り'}
                          </span>
                          <span className="font-mono">{p.volume.toFixed(2)}</span>
                          <span className="text-slate-400">{p.symbol}</span>
                          <span className="font-mono" style={{ color: tone(p.profit) }}>{signed(p.profit, cur)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
              </tr>
            )
          })}
          {list.length === 0 && (
            <tr>
              <td colSpan={7} className="px-3 py-6 text-center text-slate-400">該当する口座はありません。</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
