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
  adminSetMemberPlan,
} from '../data/auth'
import { useAuth } from '../hooks/AuthContext'
import { useFleet, type FleetCommand } from '../hooks/useFleet'
import { useSiteSettings } from '../hooks/SiteSettingsContext'
import { CHARACTERS } from '../data/characters'
import { DreamlandApplications } from '../components/DreamlandApplications'
import { MEMBER_PLANS, PLAN_NAMES, isSubscriptionAccount, subscriptionList, type MemberPlan, type PlanView } from '../data/subscription'
import { AccountsPnL } from '../components/AccountsPnL'
import { SubscriptionApprovals } from '../components/SubscriptionApprovals'
import { MemberAccounts } from '../components/MemberAccounts'

/**
 * 管理者画面のタブ。ページが長く、下のほうの欄（サブスク版の申請など）までスクロールが要ったので、上で切り替える。
 * 選んだタブは URL の末尾（#subscription など）に残す（そのリンクを開けば、最初からそのタブ）。
 */
const ADMIN_TABS = [
  { key: 'members', label: '会員' },
  { key: 'accounts', label: '口座と損益' },
  { key: 'subscription', label: 'サブスク版の申請' },
  { key: 'applications', label: '口座の申込' },
  { key: 'settings', label: '設定' },
] as const
type AdminTab = (typeof ADMIN_TABS)[number]['key']
const tabFromHash = (): AdminTab => {
  const h = typeof window === 'undefined' ? '' : window.location.hash.replace('#', '')
  return (ADMIN_TABS.find((t) => t.key === h)?.key ?? 'members') as AdminTab
}

export function Admin() {
  const [tab, setTabState] = useState<AdminTab>(tabFromHash)
  const setTab = (next: AdminTab) => {
    setTabState(next)
    try {
      window.history.replaceState(null, '', `#${next}`)
    } catch {
      /* 履歴を書けなくても切り替えは効く */
    }
  }
  // 審査待ちの件数（タブに出す）。タブを切り替えるたびに数え直す
  const [pendingSubs, setPendingSubs] = useState(0)
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
  // 通常プランとサブスク版を分けて見る（会員・口座と損益のタブ）
  const [planView, setPlanView] = useState<PlanView>('all')
  const isSub = (r: Member) => isSubscriptionAccount(r.plan, fleet.states[r.id]?.status)
  const viewRows = shownRows.filter((r) => planView === 'all' || (planView === 'subscription') === isSub(r))
  const planCount = (v: PlanView) => shownRows.filter((r) => r.role !== 'admin' && (v === 'all' || (v === 'subscription') === isSub(r))).length
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
    <AdminTabsCounter token={token} tab={tab} onCount={setPendingSubs}>
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
          お客様の一覧です。行を押すと開いて、その口座の稼働状況・資金状況・持っているポジション・取引履歴を見られます。停止・稼働・全決済もそこから送れます（パスポートが中継につながっている口座だけ）。
          {fleet.phase === 'denied' ? ' 中継に入れていません（管理者のログインを確かめてください）。' : fleet.phase === 'connecting' ? ' 中継に接続中…' : ''}
        </p>

        <div role="tablist" aria-label="管理者画面の切り替え" className="mt-4 flex flex-wrap gap-2 border-b pb-3" style={{ borderColor: 'var(--panel-border)' }}>
          {ADMIN_TABS.map((t) => {
            const on = tab === t.key
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => setTab(t.key)}
                className="h-11 rounded-[4px] border px-5 text-[15px] font-bold"
                style={{
                  borderColor: on ? 'var(--accent)' : 'var(--panel-border)',
                  background: on ? 'var(--accent)' : 'var(--panel-bg)',
                  color: on ? '#081018' : '#e2e8f0',
                }}
              >
                {t.label}
                {t.key === 'subscription' && pendingSubs > 0 && (
                  <span
                    className="ml-2 inline-flex h-6 min-w-6 items-center justify-center rounded-full px-2 text-[13px]"
                    style={{ background: '#f4c46a', color: '#081018' }}
                    aria-label={`審査待ち ${pendingSubs} 件`}
                  >
                    {pendingSubs}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {(tab === 'members' || tab === 'accounts') && (
          <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="プランで分けて見る">
            {([['all', 'すべて'], ['normal', '通常プラン'], ['subscription', 'サブスク版']] as const).map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={planView === v}
                onClick={() => setPlanView(v)}
                className="h-11 rounded-full border px-4 text-[15px]"
                style={{
                  borderColor: planView === v ? (v === 'subscription' ? '#f4c46a' : 'var(--accent)') : 'var(--panel-border)',
                  color: planView === v ? (v === 'subscription' ? '#f4c46a' : 'var(--accent)') : '#cbd5e1',
                  background: 'var(--panel-bg)',
                }}
              >
                {label}（{planCount(v)}）
              </button>
            ))}
          </div>
        )}

        {tab === 'accounts' && <AccountsPnL rows={viewRows} states={fleet.states} />}

        {error && (
          <p className="mt-4 text-[15px]" style={{ color: '#ff8484' }}>
            {error}
          </p>
        )}

        {tab === 'members' && (
          <>
        <MemberAccounts
          rows={viewRows}
          states={fleet.states}
          selfId={member?.id}
          busyId={busyId}
          sent={sent}
          query={fleet.query}
          onSend={(row, command) => void sendTo(row, command)}
          onPlan={(row, plan) =>
            void act(row.id, async () => {
              await adminSetMemberPlan(token!, row.id, plan)
            })
          }
          onRole={(row, role) => void changeRole(row, role)}
          onStatus={(row, status) => void changeStatus(row, status)}
          onTrade={(row, canTrade) => void changeTrade(row, canTrade)}
          onRemove={(row) => void removeMember(row)}
          onPassword={(row) => {
            setPwTarget(row)
            setPw1('')
            setPw2('')
            setError(null)
          }}
          passwordTargetId={pwTarget?.id ?? null}
          passwordForm={pwTarget && (
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
        />
          </>
        )}

        {tab === 'applications' && <DreamlandApplications token={token} members={rows} />}

        {tab === 'subscription' && <SubscriptionApprovals token={token} />}

        {tab === 'settings' && (
          <>
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
          </>
        )}
      </div>
    </div>
    </AdminTabsCounter>
  )
}

/** 審査待ちの件数を数えて渡すだけ（画面には何も足さない） */
function AdminTabsCounter({ token, tab, onCount, children }: { token: string | null; tab: string; onCount: (n: number) => void; children: React.ReactNode }) {
  useEffect(() => {
    if (!token) return
    let alive = true
    subscriptionList(token)
      .then((rows) => {
        if (alive) onCount(rows.filter((r) => r.status === 'pending').length)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, tab])
  return <>{children}</>
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
  const [values, setValues] = useState<Record<MemberPlan, string>>({ first: '', crystal: '', premium: '', subscription: '' })
  const [busy, setBusy] = useState<MemberPlan | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const save = async (plan: MemberPlan) => {
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
      setMessage(`${PLAN_NAMES[plan]}の合言葉を更新しました。`)
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
        ファーストの方がロイヤルへ行くのを防ぎます）。Yumekku【サブスク版】の合言葉は、特別ゲート（ロビーの yumekku-sub/）の申請で使います。8文字以上。
      </p>
      {message && (
        <p className="mt-3 text-[15px]" style={{ color: message.includes('更新しました') ? 'var(--accent)' : '#ff8484' }}>
          {message}
        </p>
      )}
      {MEMBER_PLANS.map((plan) => (
        <div key={plan} className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-[14px] text-slate-300">
            <span className="block">{PLAN_NAMES[plan]}</span>
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
