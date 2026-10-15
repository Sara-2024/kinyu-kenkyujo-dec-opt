import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import {
  adminDeleteMember,
  adminListMembers,
  adminSetEntryPassword,
  adminSetOperatorPassword,
  adminSetPlanPassword,
  adminSetPassword,
  adminUpdateMember,
  authErrorMessage,
  memberLabel,
  type Member,
  type MemberRole,
  type MemberStatus,
} from '../data/auth'
import { useAuth } from '../hooks/AuthContext'
import { useFleet, type FleetCommand } from '../hooks/useFleet'
import { useSiteSettings } from '../hooks/SiteSettingsContext'
import { CHARACTERS } from '../data/characters'
import { DreamlandApplications } from '../components/DreamlandApplications'
import { DREAMLAND_PLAN_NAMES } from '../data/dreamland'

export function Admin() {
  const { member, token, ready } = useAuth()
  const [rows, setRows] = useState<Member[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [entry, setEntry] = useState('')
  const [pwTarget, setPwTarget] = useState<Member | null>(null)
  const [pw1, setPw1] = useState('')
  const [pw2, setPw2] = useState('')
  // 会員ごとのパスポート（接続ツール）へ、停止・稼働・全決済を送る。中継の /fleet を使う
  // （一斉制御と同じ道。部屋＝会員ID を名指しして 1 件だけ送る）
  const fleet = useFleet(member?.role === 'admin' ? token : null, rows.map((r) => r.id))
  // 中継につながっているのに一覧に無い口座（登録が遅れている・読み直し前）も、行として出す
  const shownRows: Member[] = [
    ...rows,
    ...Object.entries(fleet.states)
      .filter(([room, st]) => st.online && !rows.some((r) => r.id === room))
      .map(([room, st]) => {
        const acct = Number((st.status as { account?: unknown } | null)?.account) || null
        return { id: room, name: '（連携のみ）', account: acct, server: String((st.status as { server?: unknown } | null)?.server ?? ''), role: 'user', status: 'active', can_trade: true } as unknown as Member
      }),
  ]
  const [sent, setSent] = useState<Record<string, string>>({})
  const sendTo = async (row: Member, command: FleetCommand) => {
    const label: Record<FleetCommand, string> = { stop_trading: '停止', start_trading: '稼働', close_all: '全決済', stop_system: 'システム停止' }
    if (command === 'close_all' && !window.confirm(`${memberLabel(row)} の建玉と待機注文をすべて閉じます。よろしいですか？`)) return
    setBusyId(row.id)
    setError(null)
    try {
      const r = await fleet.send(command, [row.id], '管理者画面')
      setSent((prev) => ({
        ...prev,
        [row.id]: r.delivered.includes(row.id) ? `${label[command]}を送りました（${new Date().toLocaleTimeString('ja-JP')}）` : r.refused?.includes(row.id) ? '本人が一斉停止を受け付けない設定です' : 'パスポートが中継に居ません（預かり）',
      }))
    } catch (err) {
      setError(err instanceof Error ? err.message : '送れませんでした')
    } finally {
      setBusyId(null)
    }
  }

  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'auto'
    return () => {
      document.body.style.overflow = prev
    }
  }, [])

  const reload = async () => {
    if (!token) return
    try {
      setRows(await adminListMembers(token))
    } catch (err) {
      setError(authErrorMessage(err))
    }
  }

  useEffect(() => {
    if (ready && member?.role === 'admin' && token) void reload()
  }, [ready, member, token])
  // 新しく登録・連携した口座が、開き直さなくても出るように 30 秒ごとに読み直す
  useEffect(() => {
    if (!(ready && member?.role === 'admin' && token)) return
    const id = setInterval(() => void reload(), 30_000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, member, token])

  if (ready && !member) return <Navigate to="/login" replace />
  if (ready && member && member.role !== 'admin') return <Navigate to="/" replace />

  /** 成功したかどうかを返す。呼ぶ側は、成功したときだけ入力を閉じる */
  const act = async (id: string, run: () => Promise<void>): Promise<boolean> => {
    if (!token) return false
    setBusyId(id)
    setError(null)
    let ok = false
    try {
      await run()
      await reload()
      ok = true
    } catch (err) {
      setError(authErrorMessage(err))
    } finally {
      setBusyId(null)
    }
    return ok
  }

  const changeRole = (row: Member, role: MemberRole) =>
    act(row.id, async () => {
      await adminUpdateMember(token!, row.id, { role })
    })
  const changeStatus = (row: Member, status: MemberStatus) =>
    act(row.id, async () => {
      await adminUpdateMember(token!, row.id, { status })
    })
  const changeTrade = (row: Member, can_trade: boolean) =>
    act(row.id, async () => {
      await adminUpdateMember(token!, row.id, { can_trade })
    })
  const removeMember = (row: Member) => {
    if (!window.confirm(`${memberLabel(row)} を削除しますか？\n連携・一斉制御の記録も一緒に消えます。元に戻せません。`)) return
    return act(row.id, async () => {
      await adminDeleteMember(token!, row.id)
    })
  }

  const savePassword = async () => {
    if (!pwTarget || !token) return
    if (pw1 !== pw2) {
      setError('パスワード（確認）が一致しません。')
      return
    }
    // 失敗（8文字未満など）のときに閉じてしまうと、入力が消えるだけで
    // 変わったのかどうか分からない。成功したときだけ閉じる。
    const ok = await act(pwTarget.id, () => adminSetPassword(token, pwTarget.id, pw1))
    if (!ok) return
    setPwTarget(null)
    setPw1('')
    setPw2('')
  }

  const saveEntry = async () => {
    if (!token) return
    const ok = await act('entry', () => adminSetEntryPassword(token, entry))
    if (ok) setEntry('')
  }

  return (
    <div className="min-h-screen px-6 py-6" style={{ background: '#070b14', color: '#e8edf5' }}>
      <div className="mx-auto max-w-[1100px]">
        <div className="flex flex-wrap items-center gap-4">
          <span className="h-4 w-[3px]" style={{ background: 'var(--accent)' }} />
          <h1 className="text-[22px] font-bold">管理者画面</h1>
          <Link to="/fleet" className="ml-auto text-[15px] font-bold" style={{ color: 'var(--accent)' }}>
            一斉制御
          </Link>
          <Link to="/" className="text-[15px] font-bold" style={{ color: 'var(--accent)' }}>
            研究所へ戻る
          </Link>
        </div>
        <p className="mt-2 text-[15px] text-slate-400">
          利用中のアカウント一覧です。「パスポート」の列で、その口座の EA を止める・動かす・全決済できます（パスポートが中継につながっている口座だけ）。
          {fleet.phase === 'denied' ? ' 中継に入れていません（管理者のログインを確かめてください）。' : fleet.phase === 'connecting' ? ' 中継に接続中…' : ''}
        </p>

        {error && (
          <p className="mt-4 text-[15px]" style={{ color: '#ff8484' }}>
            {error}
          </p>
        )}

        <div
          className="mt-5 overflow-x-auto rounded-[4px] border"
          style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}
        >
          <table className="w-full min-w-[860px] text-left text-[15px]">
            <thead>
              <tr className="border-b text-slate-400" style={{ borderColor: 'var(--panel-border)' }}>
                <th className="px-3 py-3 font-bold">お名前</th>
                <th className="px-3 py-3 font-bold">口座番号</th>
                <th className="px-3 py-3 font-bold">プラン</th>
                <th className="px-3 py-3 font-bold">権限</th>
                <th className="px-3 py-3 font-bold">状態</th>
                <th className="px-3 py-3 font-bold">お客様の操作</th>
                <th className="px-3 py-3 font-bold">MT5連携</th>
                <th className="px-3 py-3 font-bold">パスポート</th>
                <th className="px-3 py-3 font-bold">OS</th>
                <th className="px-3 py-3 font-bold">最終ログイン</th>
                <th className="px-3 py-3 font-bold">操作</th>
              </tr>
            </thead>
            <tbody>
              {shownRows.map((row) => (
                <tr key={row.id} className="border-b" style={{ borderColor: 'rgba(94,204,255,0.12)' }}>
                  <td className="px-3 py-3">
                    {row.name || <span className="text-slate-500">{row.email ?? '—'}</span>}
                    {row.id === member?.id ? (
                      <span className="ml-2 text-[12px] text-slate-500">自分</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 font-mono">{row.account ?? '—'}</td>
                  <td className="px-3 py-3">
                    {row.plan ? (
                      <span style={{ color: row.plan === 'crystal' ? '#e8d8a8' : undefined }}>{DREAMLAND_PLAN_NAMES[row.plan]}</span>
                    ) : (
                      <span className="text-slate-500">—</span>
                    )}
                  </td>
                  <td className="px-3 py-3">{row.role === 'admin' ? '管理者' : '一般'}</td>
                  <td className="px-3 py-3">
                    {row.status === 'active' ? '利用中' : <span style={{ color: '#ff8484' }}>BAN中</span>}
                  </td>
                  <td className="px-3 py-3">{row.can_trade ? '許可' : '不可'}</td>
                  <td className="px-3 py-3 text-slate-300">
                    {row.connected_account ? `${row.connected_account} / ${row.server ?? ''}` : '—'}
                  </td>
                  <td className="px-3 py-3">
                    {(() => {
                      const st = fleet.states[row.id]
                      const online = !!st?.online
                      const running = typeof st?.status?.value === 'number' ? Number(st.status.value) !== 0 : null
                      return (
                        <div className="flex flex-col gap-1">
                          <span style={{ color: online ? '#35f58a' : '#94a3b8' }}>
                            {online ? `接続中（${running === null ? '状態不明' : running ? 'EA 稼働中' : 'EA 停止中'}）` : '未接続'}
                          </span>
                          <div className="flex flex-wrap gap-1">
                            <Mini disabled={!online || busyId === row.id} onClick={() => void sendTo(row, 'stop_trading')}>停止</Mini>
                            <Mini disabled={!online || busyId === row.id} onClick={() => void sendTo(row, 'start_trading')}>稼働</Mini>
                            <Mini disabled={!online || busyId === row.id} onClick={() => void sendTo(row, 'close_all')}>全決済</Mini>
                          </div>
                          {sent[row.id] && <span className="text-[12px] text-slate-400">{sent[row.id]}</span>}
                          {st?.ack && <span className="text-[12px]" style={{ color: st.ack.ok ? '#35f58a' : '#ff8484' }}>{st.ack.ok ? 'パスポートが実行しました' : `失敗: ${st.ack.error ?? ''}`}</span>}
                        </div>
                      )
                    })()}
                  </td>
                  <td className="px-3 py-3">{row.platform === 'mac' ? 'Mac' : row.platform === 'windows' ? 'Windows' : '—'}</td>
                  <td className="px-3 py-3 text-slate-400">
                    {row.last_login_at ? new Date(row.last_login_at).toLocaleString('ja-JP') : '—'}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      <Mini
                        disabled={busyId === row.id}
                        onClick={() => void changeRole(row, row.role === 'admin' ? 'user' : 'admin')}
                      >
                        {row.role === 'admin' ? '一般にする' : '管理者にする'}
                      </Mini>
                      <Mini
                        disabled={busyId === row.id}
                        onClick={() => void changeStatus(row, row.status === 'active' ? 'suspended' : 'active')}
                      >
                        {row.status === 'active' ? 'BAN' : 'BAN解除'}
                      </Mini>
                      <Mini disabled={busyId === row.id} onClick={() => void removeMember(row)}>
                        削除
                      </Mini>
                      <Mini
                        disabled={busyId === row.id}
                        onClick={() => void changeTrade(row, !row.can_trade)}
                      >
                        {row.can_trade ? 'お客様の操作を禁止' : 'お客様の操作を許可'}
                      </Mini>
                      <Mini
                        disabled={busyId === row.id}
                        onClick={() => {
                          setPwTarget(row)
                          setPw1('')
                          setPw2('')
                          setError(null)
                        }}
                      >
                        パスワード変更
                      </Mini>
                    </div>
                  </td>
                </tr>
              ))}
              {shownRows.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-3 py-8 text-center text-slate-500">
                    まだアカウントがありません。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {pwTarget && (
          <div
            className="mt-5 rounded-[4px] border px-5 py-5"
            style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}
          >
            <p className="text-[16px] font-bold">パスワードを変更 — {memberLabel(pwTarget)}</p>
            <p className="mt-1 text-[14px] text-slate-400">変更すると、その人は再ログインが必要になります。</p>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <label className="block">
                <span className="mb-1 block text-[14px]">新しいパスワード</span>
                <input
                  type="password"
                  value={pw1}
                  onChange={(e) => setPw1(e.target.value)}
                  className="h-11 w-56 rounded-[4px] border px-3 text-[15px]"
                  style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[14px]">確認</span>
                <input
                  type="password"
                  value={pw2}
                  onChange={(e) => setPw2(e.target.value)}
                  className="h-11 w-56 rounded-[4px] border px-3 text-[15px]"
                  style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
                />
              </label>
              <button
                type="button"
                onClick={() => void savePassword()}
                className="h-11 rounded-[4px] px-5 text-[15px] font-bold text-[#081018]"
                style={{ background: 'var(--accent)' }}
              >
                変更する
              </button>
              <button type="button" onClick={() => setPwTarget(null)} className="h-11 px-3 text-[15px] text-slate-400">
                キャンセル
              </button>
            </div>
          </div>
        )}

        <DreamlandApplications token={token} members={rows} />

        <NamesSection token={token} />

        <div
          className="mt-5 rounded-[4px] border px-5 py-5"
          style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}
        >
          <p className="text-[16px] font-bold">入場パスワード</p>
          <p className="mt-1 text-[14px] text-slate-400">新規登録のときに使う合言葉です。8文字以上。</p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <input
              type="password"
              value={entry}
              onChange={(e) => setEntry(e.target.value)}
              className="h-11 w-64 rounded-[4px] border px-3 text-[15px]"
              style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
            />
            <button
              type="button"
              onClick={() => void saveEntry()}
              className="h-11 rounded-[4px] px-5 text-[15px] font-bold text-[#081018]"
              style={{ background: 'var(--accent)' }}
            >
              入場パスワードを更新
            </button>
          </div>
        </div>

        <PlanPasswordsSection token={token} />

        <OperatorPasswordSection token={token} />
      </div>
    </div>
  )
}

/** 管理サイト（運営用の別サイト）に入るための合言葉 */
function OperatorPasswordSection({ token }: { token: string | null }) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const save = async () => {
    if (!token) return
    if (value.trim().length < 8) {
      setMessage('合言葉は8文字以上にしてください。')
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      await adminSetOperatorPassword(token, value.trim())
      setValue('')
      setMessage('管理サイトの合言葉を更新しました。')
    } catch (err) {
      setMessage(authErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="mt-5 rounded-[4px] border px-5 py-5" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
      <p className="text-[16px] font-bold">管理サイトの合言葉</p>
      <p className="mt-1 text-[14px] text-slate-400">運営が管理サイトに入るときの合言葉です。8文字以上。知っている人は誰でも管理者として入れるので、外に出さないでください。</p>
      {message && (
        <p className="mt-3 text-[15px]" style={{ color: message.includes('更新しました') ? 'var(--accent)' : '#ff8484' }}>
          {message}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="h-11 w-64 rounded-[4px] border px-3 text-[15px]"
          style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
        />
        <button type="button" disabled={busy} onClick={() => void save()} className="h-11 rounded-[4px] px-5 text-[15px] font-bold text-[#081018]" style={{ background: 'var(--accent)' }}>
          合言葉を更新
        </button>
      </div>
    </div>
  )
}

/**
 * プランごとの合言葉。ロビー（ドリームランド渡航手続き）の「パスポートの設置」で
 * お客様が打ち込むもの。合った合言葉のプランに振り分けられ、会員登録でもそのプランが付く。
 */
function PlanPasswordsSection({ token }: { token: string | null }) {
  const [values, setValues] = useState<Record<'first' | 'crystal' | 'premium', string>>({ first: '', crystal: '', premium: '' })
  const [busy, setBusy] = useState<'first' | 'crystal' | 'premium' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const save = async (plan: 'first' | 'crystal' | 'premium') => {
    if (!token) return
    const pw = values[plan].trim()
    if (pw.length < 8) {
      setMessage('合言葉は8文字以上にしてください。')
      return
    }
    setBusy(plan)
    setMessage(null)
    try {
      await adminSetPlanPassword(token, plan, pw)
      setValues((v) => ({ ...v, [plan]: '' }))
      setMessage(`${DREAMLAND_PLAN_NAMES[plan]}の合言葉を更新しました。`)
    } catch (err) {
      setMessage(authErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="mt-5 rounded-[4px] border px-5 py-5" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
      <p className="text-[16px] font-bold">プランの合言葉</p>
      <p className="mt-1 text-[14px] text-slate-400">
        ロビーの「パスポートの設置」でお客様が打ち込む合言葉です。打った合言葉のプランにしか案内されません（ロイヤルの方がファーストへ、
        ファーストの方がロイヤルへ行くのを防ぎます）。8文字以上。
      </p>
      {message && (
        <p className="mt-3 text-[15px]" style={{ color: message.includes('更新しました') ? 'var(--accent)' : '#ff8484' }}>
          {message}
        </p>
      )}
      {(['first', 'crystal', 'premium'] as const).map((plan) => (
        <div key={plan} className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-[14px] text-slate-300">
            <span className="block">{DREAMLAND_PLAN_NAMES[plan]}</span>
            <input
              type="password"
              value={values[plan]}
              onChange={(e) => setValues((v) => ({ ...v, [plan]: e.target.value }))}
              className="mt-1 h-11 w-64 rounded-[4px] border px-3 text-[15px]"
              style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
            />
          </label>
          <button
            type="button"
            disabled={busy === plan}
            onClick={() => void save(plan)}
            className="h-11 rounded-[4px] px-5 text-[15px] font-bold text-[#081018]"
            style={{ background: 'var(--accent)' }}
          >
            合言葉を更新
          </button>
        </div>
      ))}
    </div>
  )
}

/** 研究員の名前。サイト全体に効く（台詞の中の呼び名もいっしょに変わる） */
function NamesSection({ token }: { token: string | null }) {
  const { settings, save } = useSiteSettings()
  const [names, setNames] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    const next: Record<string, string> = {}
    for (const id of Object.keys(CHARACTERS)) next[id] = settings.names?.[id] ?? ''
    setNames(next)
  }, [settings])

  const submit = async () => {
    setSaving(true)
    setNote(null)
    const cleaned: Record<string, string> = {}
    for (const [id, v] of Object.entries(names)) if (v.trim()) cleaned[id] = v.trim()
    const where = await save(token, { ...settings, names: cleaned })
    setSaving(false)
    setNote(
      where === 'remote'
        ? '保存しました。どの端末で開いても、この名前で表示されます。'
        : 'この端末には反映しました。他の端末にも配るには、データベースの更新（schema.sql）が必要です。',
    )
  }

  return (
    <div
      className="mt-8 rounded-[4px] border px-5 py-5"
      style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}
    >
      <p className="text-[17px] font-bold">研究員の名前</p>
      <p className="mt-1 text-[14px] text-slate-400">
        空のままなら元の名前を使います。名札だけでなく、台詞の中で呼び合う名前も変わります。
      </p>
      <div className="mt-4 flex flex-wrap gap-4">
        {Object.values(CHARACTERS).map((c) => (
          <label key={c.id} className="flex min-w-[200px] flex-1 flex-col gap-1.5 text-[14px] text-slate-300">
            <span>
              {c.role}
              <span className="ml-2 text-slate-500">（元: {c.name}）</span>
            </span>
            <input
              value={names[c.id] ?? ''}
              onChange={(e) => setNames((n) => ({ ...n, [c.id]: e.target.value }))}
              placeholder={c.name}
              maxLength={12}
              className="h-11 rounded-[4px] border px-3 text-[16px] font-bold text-white outline-none"
              style={{ borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.7)' }}
            />
          </label>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <button
          type="button"
          disabled={saving}
          onClick={() => void submit()}
          className="h-11 rounded-[4px] px-5 text-[15px] font-bold text-slate-900 disabled:opacity-40"
          style={{ background: 'var(--accent)' }}
        >
          名前を反映する
        </button>
        {note && <p className="text-[14px] text-slate-300">{note}</p>}
      </div>
    </div>
  )
}

function Mini({
  children,
  onClick,
  disabled,
}: {
  children: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="h-11 rounded-[4px] border px-3 text-[13px] font-bold text-slate-100 disabled:opacity-40"
      style={{ borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.7)' }}
    >
      {children}
    </button>
  )
}
