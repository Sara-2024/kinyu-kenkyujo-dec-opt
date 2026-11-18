// 管理者画面: Yumekku【サブスク版】の申請と承認。
// 承認しているあいだだけ、その口座の Yumekku【サブスク版】が新規エントリーする（サブスク）。
// ご解約などで「停止」にすると、パスポートがつながっていれば 1 分ほどで新規が止まる
// （つながっていなくても、手元の利用許可が切れる最長 25 時間で止まる）。保有中の建玉は通常どおり決済される。
import { useEffect, useState } from 'react'
import {
  SUBSCRIPTION_STATUS_NAMES,
  subscriptionErrorMessage,
  subscriptionList,
  subscriptionSet,
  type SubscriptionRow,
  type SubscriptionStatus,
} from '../data/subscription'

const STATUS_COLOR: Record<SubscriptionStatus, string> = {
  pending: '#f4c46a',
  active: 'var(--accent)',
  stopped: '#ff8484',
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString('ja-JP', { dateStyle: 'short', timeStyle: 'short' }) : '—')

export function SubscriptionApprovals({ token }: { token: string | null }) {
  const [rows, setRows] = useState<SubscriptionRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notes, setNotes] = useState<Record<string, string>>({})

  const reload = async () => {
    if (!token) return
    try {
      const list = await subscriptionList(token)
      setRows(list)
      setNotes(Object.fromEntries(list.map((r) => [r.member_id, r.note])))
      setError(null)
    } catch (err) {
      setError(subscriptionErrorMessage(err))
    }
  }

  useEffect(() => {
    void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const set = async (row: SubscriptionRow, status: SubscriptionStatus) => {
    if (!token) return
    const who = `${row.name || '（お名前なし）'}（口座 ${row.account ?? '—'}）`
    const ask =
      status === 'active'
        ? `${who} のご利用を承認します。承認しているあいだ、Yumekku【サブスク版】が新規エントリーします。よろしいですか？`
        : status === 'stopped'
          ? `${who} のご利用を停止します。新規エントリーが止まります（保有中のポジションは通常どおり決済されます）。よろしいですか？`
          : `${who} を審査中に戻します。新規エントリーは止まります。よろしいですか？`
    if (!window.confirm(ask)) return
    setBusyId(row.member_id)
    setError(null)
    try {
      await subscriptionSet(token, row.member_id, status, notes[row.member_id] ?? row.note)
      await reload()
    } catch (err) {
      setError(subscriptionErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  const saveNote = async (row: SubscriptionRow) => {
    if (!token) return
    setBusyId(row.member_id)
    try {
      await subscriptionSet(token, row.member_id, row.status, notes[row.member_id] ?? '')
      await reload()
    } catch (err) {
      setError(subscriptionErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  const pending = rows.filter((r) => r.status === 'pending').length
  const active = rows.filter((r) => r.status === 'active').length

  return (
    <div className="mt-5 rounded-[4px] border px-5 py-5" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="text-[16px] font-bold">Yumekku【サブスク版】の申請</p>
        <p className="text-[15px] text-slate-300">
          審査中 <b style={{ color: STATUS_COLOR.pending }}>{pending}</b> 件 ／ 承認中 <b style={{ color: STATUS_COLOR.active }}>{active}</b> 件
        </p>
      </div>
      <p className="mt-1 text-[14px] text-slate-400">
        お客様は特別ゲート（ロビーの yumekku-sub/）から申請します。「承認」しているあいだだけ、その口座の Yumekku【サブスク版】が新規エントリーします。
        「停止」にすると、パスポートがつながっていれば 1 分ほどで新規が止まり、つながっていなくても最長 25 時間で止まります。
      </p>
      <div className="mt-3 flex gap-3">
        <button
          type="button"
          onClick={() => void reload()}
          className="h-11 rounded-[4px] border px-4 text-[15px]"
          style={{ borderColor: 'var(--panel-border)' }}
        >
          一覧を読み直す
        </button>
      </div>
      {error && <p className="mt-3 text-[15px] text-[#ff8484]">{error}</p>}
      {rows.length === 0 && !error ? (
        <p className="mt-4 text-[15px] text-slate-400">まだ申請はありません。</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-[15px]">
            <thead>
              <tr className="border-b text-[14px] text-slate-400" style={{ borderColor: 'var(--panel-border)' }}>
                <th className="px-3 py-2">お名前</th>
                <th className="px-3 py-2">口座番号</th>
                <th className="px-3 py-2">状態</th>
                <th className="px-3 py-2">申請</th>
                <th className="px-3 py-2">承認／停止</th>
                <th className="px-3 py-2">メモ</th>
                <th className="px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const busy = busyId === row.member_id
                return (
                  <tr key={row.member_id} className="border-b align-top" style={{ borderColor: 'rgba(94,204,255,0.12)' }}>
                    <td className="px-3 py-3">
                      {row.name || '—'}
                      {row.member_status !== 'active' && <span className="ml-2 text-[13px] text-[#ff8484]">（会員は利用停止中）</span>}
                    </td>
                    <td className="px-3 py-3 font-mono">{row.account ?? '—'}</td>
                    <td className="px-3 py-3 font-bold" style={{ color: STATUS_COLOR[row.status] }}>
                      {SUBSCRIPTION_STATUS_NAMES[row.status]}
                    </td>
                    <td className="px-3 py-3 text-[14px] text-slate-300">
                      {when(row.applied_at)}
                      {row.submissions > 1 && <span className="block text-[13px] text-slate-400">申請 {row.submissions} 回目</span>}
                    </td>
                    <td className="px-3 py-3 text-[14px] text-slate-300">
                      {row.status === 'active' ? `承認 ${when(row.approved_at)}` : row.status === 'stopped' ? `停止 ${when(row.stopped_at)}` : '—'}
                    </td>
                    <td className="px-3 py-3">
                      <input
                        value={notes[row.member_id] ?? ''}
                        onChange={(e) => setNotes((n) => ({ ...n, [row.member_id]: e.target.value }))}
                        onBlur={() => {
                          if ((notes[row.member_id] ?? '') !== row.note) void saveNote(row)
                        }}
                        maxLength={200}
                        placeholder="お支払い・解約の記録など"
                        className="h-11 w-56 rounded-[4px] border px-3 text-[15px]"
                        style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
                      />
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-wrap gap-2">
                        {row.status !== 'active' && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void set(row, 'active')}
                            className="h-11 rounded-[4px] px-4 text-[15px] font-bold text-[#081018]"
                            style={{ background: 'var(--accent)' }}
                          >
                            承認する
                          </button>
                        )}
                        {row.status !== 'stopped' && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void set(row, 'stopped')}
                            className="h-11 rounded-[4px] border px-4 text-[15px] font-bold"
                            style={{ borderColor: '#ff8484', color: '#ff8484' }}
                          >
                            {row.status === 'active' ? '停止する（解約）' : '見送る'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
