// 管理者画面: ドリームランドのロビーで預かった MT5 口座の申込の一覧。
// EA の納品（設置）のときに、ここからパスワードを取り出す。
import { useEffect, useState } from 'react'
import type { Member } from '../data/auth'
import {
  DREAMLAND_PLAN_NAMES,
  dreamlandDelete,
  dreamlandErrorMessage,
  dreamlandList,
  dreamlandReveal,
  dreamlandSetNote,
  type DreamlandApplication,
} from '../data/dreamland'

const normAcct = (a: unknown) => String(a ?? '').replace(/\D/g, '')
const normServer = (s: unknown) => String(s ?? '').trim().toLowerCase().replace(/\s+/g, ' ')

/** 申込の口座（番号・サーバー）と、その会員がパスポートでつないでいる口座が同じか */
function matchState(row: DreamlandApplication, member: Member | undefined): 'none' | 'match' | 'mismatch' {
  if (!member || !member.connected_account) return 'none'
  const sameNo = normAcct(member.connected_account) === normAcct(row.account)
  const sameServer = !normServer(member.server) || normServer(member.server) === normServer(row.server)
  return sameNo && sameServer ? 'match' : 'mismatch'
}

export function DreamlandApplications({ token, members = [] }: { token: string | null; members?: Member[] }) {
  const [rows, setRows] = useState<DreamlandApplication[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [shown, setShown] = useState<Record<string, string>>({})
  const [notes, setNotes] = useState<Record<string, string>>({})

  const reload = async () => {
    if (!token) return
    try {
      const list = await dreamlandList(token)
      setRows(list)
      setNotes(Object.fromEntries(list.map((r) => [r.id, r.note])))
      setError(null)
    } catch (err) {
      setError(dreamlandErrorMessage(err))
    }
  }

  useEffect(() => {
    void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const act = async (id: string, run: () => Promise<void>) => {
    if (!token) return
    setBusyId(id)
    setError(null)
    try {
      await run()
    } catch (err) {
      setError(dreamlandErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  const reveal = (row: DreamlandApplication) =>
    act(row.id, async () => {
      if (shown[row.id]) {
        setShown((s) => ({ ...s, [row.id]: '' }))
        return
      }
      const r = await dreamlandReveal(token!, row.id)
      setShown((s) => ({ ...s, [row.id]: r.password }))
    })

  const saveNote = (row: DreamlandApplication) =>
    act(row.id, async () => {
      await dreamlandSetNote(token!, row.id, notes[row.id] ?? '')
      await reload()
    })

  const remove = (row: DreamlandApplication) => {
    if (!window.confirm(`${row.application_no}（口座 ${row.account}）の申込を削除しますか？\n預かったパスワードも消えます。元に戻せません。`)) return
    return act(row.id, async () => {
      await dreamlandDelete(token!, row.id)
      await reload()
    })
  }

  return (
    <div className="mt-5 rounded-[4px] border px-5 py-5" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-[16px] font-bold">ドリームランドの口座申込</p>
        <span className="text-[13px] text-slate-500">{rows.length} 件</span>
        <button type="button" onClick={() => void reload()} className="ml-auto h-9 px-3 text-[14px]" style={{ color: 'var(--accent)' }}>
          更新
        </button>
      </div>
      <p className="mt-1 text-[14px] text-slate-400">
        ロビーのサービスカウンターで記入された MT5 口座です。EA を納品するときに「パスワードを見る」で取り出します。
        「回数」が 2 以上の人は、同じ口座を何度も送っています。「会員」は、同じ口座番号で本体サイトに登録した人、「連携口座」は、その会員がパスポートでつないでいる口座と申込の口座（番号・サーバー）が同じかどうかです。
      </p>
      {error && (
        <p className="mt-3 text-[15px]" style={{ color: '#ff8484' }}>
          {error}
        </p>
      )}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[980px] text-left text-[15px]">
          <thead>
            <tr className="border-b text-slate-400" style={{ borderColor: 'var(--panel-border)' }}>
              <th className="px-3 py-2 font-bold">受付番号</th>
              <th className="px-3 py-2 font-bold">プラン</th>
              <th className="px-3 py-2 font-bold">口座 / サーバー</th>
              <th className="px-3 py-2 font-bold">パスワード</th>
              <th className="px-3 py-2 font-bold">お名前</th>
              <th className="px-3 py-2 font-bold">会員</th>
              <th className="px-3 py-2 font-bold">連携口座</th>
              <th className="px-3 py-2 font-bold">OS</th>
              <th className="px-3 py-2 font-bold">回数</th>
              <th className="px-3 py-2 font-bold">受付日時</th>
              <th className="px-3 py-2 font-bold">覚え書き</th>
              <th className="px-3 py-2 font-bold">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-b align-top" style={{ borderColor: 'rgba(94,204,255,0.12)' }}>
                <td className="px-3 py-3 font-mono">{row.application_no}</td>
                <td className="px-3 py-3">
                  <span style={{ color: row.plan === 'crystal' ? '#e8d8a8' : undefined }}>{DREAMLAND_PLAN_NAMES[row.plan] ?? row.plan}</span>
                </td>
                <td className="px-3 py-3 text-slate-300">
                  {row.account} / {row.server}
                </td>
                <td className="px-3 py-3">
                  {shown[row.id] ? (
                    <span className="font-mono" style={{ color: 'var(--accent)' }}>
                      {shown[row.id]}
                    </span>
                  ) : (
                    <span className="text-slate-500">••••••</span>
                  )}
                </td>
                <td className="px-3 py-3 text-slate-300">{row.name || '—'}</td>
                <td className="px-3 py-3">
                  {row.member_id ? (
                    <span style={{ color: 'var(--accent)' }}>{row.member_name || '登録済み'}</span>
                  ) : (
                    <span className="text-slate-500">未登録</span>
                  )}
                </td>
                <td className="px-3 py-3">
                  {(() => {
                    const member = members.find((m) => m.id === row.member_id)
                    const state = matchState(row, member)
                    if (state === 'none') return <span className="text-slate-500">未連携</span>
                    if (state === 'match') return <span style={{ color: '#35f58a' }}>一致</span>
                    return (
                      <span style={{ color: '#ff8484' }}>
                        一致しない
                        <br />
                        <span className="text-[12px]">連携: {String(member?.connected_account)} / {member?.server ?? ''}</span>
                      </span>
                    )
                  })()}
                </td>
                <td className="px-3 py-3">{row.platform === 'mac' ? 'Mac' : row.platform === 'windows' ? 'Windows' : '—'}</td>
                <td className="px-3 py-3">
                  {row.submissions >= 2 ? <span style={{ color: '#ff8484' }}>{row.submissions}</span> : row.submissions}
                </td>
                <td className="px-3 py-3 text-slate-400">{new Date(row.updated_at).toLocaleString('ja-JP')}</td>
                <td className="px-3 py-3">
                  <input
                    value={notes[row.id] ?? ''}
                    onChange={(e) => setNotes((n) => ({ ...n, [row.id]: e.target.value }))}
                    onBlur={() => {
                      if ((notes[row.id] ?? '') !== row.note) void saveNote(row)
                    }}
                    placeholder="納品日など"
                    className="h-10 w-40 rounded-[4px] border px-2 text-[14px]"
                    style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
                  />
                </td>
                <td className="px-3 py-3">
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={busyId === row.id}
                      onClick={() => void reveal(row)}
                      className="h-10 rounded-[4px] border px-3 text-[14px]"
                      style={{ borderColor: 'var(--panel-border)' }}
                    >
                      {shown[row.id] ? '隠す' : 'パスワードを見る'}
                    </button>
                    <button
                      type="button"
                      disabled={busyId === row.id}
                      onClick={() => void remove(row)}
                      className="h-10 rounded-[4px] border px-3 text-[14px]"
                      style={{ borderColor: 'var(--panel-border)' }}
                    >
                      削除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && !error && (
              <tr>
                <td colSpan={12} className="px-3 py-6 text-center text-slate-500">
                  まだ申込はありません。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
