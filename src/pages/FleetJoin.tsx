// 口座の登録（会員）。自社のデモ口座を一斉制御の対象にするための登録ページ。
//
// ここで登録した口座は、「運営が止めてよい」と許可したものとして扱う。
// 止める合図は、この会員の PC で動く MT5 Automatic へ流す（パスワードは使わない）。
import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../hooks/AuthContext'
import { fleetDelete, fleetErrorMessage, fleetMyAccounts, fleetRegister, type FleetAccount } from '../data/fleet'

export function FleetJoin() {
  const { member, token, ready } = useAuth()
  const [rows, setRows] = useState<FleetAccount[]>([])
  const [account, setAccount] = useState('')
  const [server, setServer] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
      setRows(await fleetMyAccounts(token))
    } catch (err) {
      setError(fleetErrorMessage(err))
    }
  }

  useEffect(() => {
    if (ready && member && token) void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, member, token])

  if (ready && !member) return <Navigate to="/login" replace />

  const submit = async () => {
    if (!token) return
    const num = Number(account.trim())
    setError(null)
    setDone(null)
    if (!Number.isInteger(num) || num <= 0) {
      setError('口座番号は数字で入力してください。')
      return
    }
    setBusy(true)
    try {
      await fleetRegister(token, num, server.trim(), password)
      setDone(`${num} / ${server.trim()} を登録しました。`)
      setAccount('')
      setServer('')
      setPassword('')
      await reload()
    } catch (err) {
      setError(fleetErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (row: FleetAccount) => {
    if (!token) return
    if (!window.confirm(`${row.account} / ${row.server} の登録を取り消しますか？`)) return
    setBusy(true)
    try {
      await fleetDelete(token, row.id)
      await reload()
    } catch (err) {
      setError(fleetErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen px-6 py-6" style={{ background: '#070b14', color: '#e8edf5' }}>
      <div className="mx-auto max-w-[760px]">
        <div className="flex flex-wrap items-center gap-4">
          <span className="h-4 w-[3px]" style={{ background: 'var(--accent)' }} />
          <h1 className="text-[22px] font-bold">口座の登録</h1>
          <Link to="/" className="ml-auto text-[15px] font-bold" style={{ color: 'var(--accent)' }}>
            研究所へ戻る
          </Link>
        </div>
        <p className="mt-2 text-[16px] text-slate-300">
          ここに登録した口座は、運営が一斉に停止・再開できるようになります。
          登録をもって、その操作を運営に任せることに同意したものとします。
        </p>
        <p className="mt-1 text-[14px] text-slate-400">
          口座番号・サーバー名は MT5 のログイン画面に出ているものです。この PC の MT5 Automatic が研究所と連携済みであれば、そのまま制御できます。
        </p>

        <div className="mt-5 rounded-[4px] border px-5 py-5" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="口座番号">
              <input
                value={account}
                onChange={(e) => setAccount(e.target.value)}
                inputMode="numeric"
                placeholder="例 75602463"
                className={INPUT}
                style={INPUT_STYLE}
              />
            </Field>
            <Field label="サーバー">
              <input value={server} onChange={(e) => setServer(e.target.value)} placeholder="例 XMTrading-MT5 3" className={INPUT} style={INPUT_STYLE} />
            </Field>
            <Field label="パスワード">
              <input
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                type="password"
                autoComplete="off"
                className={INPUT}
                style={INPUT_STYLE}
              />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <button
              type="button"
              disabled={busy}
              onClick={() => void submit()}
              className="h-12 rounded-[4px] border px-6 text-[16px] font-bold disabled:opacity-40"
              style={{ borderColor: 'var(--accent)', background: 'rgba(94,204,255,0.15)', color: 'var(--accent)' }}
            >
              登録する
            </button>
            {done && <span className="text-[15px]" style={{ color: '#35f58a' }}>{done}</span>}
            {error && <span className="text-[15px]" style={{ color: '#ff8484' }}>{error}</span>}
          </div>
        </div>

        <h2 className="mt-8 text-[17px] font-bold">登録済みの口座</h2>
        <div className="mt-3 rounded-[4px] border" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
          {rows.length === 0 ? (
            <p className="px-5 py-6 text-[15px] text-slate-500">まだ登録はありません。</p>
          ) : (
            rows.map((row) => (
              <div key={row.id} className="flex flex-wrap items-center gap-4 border-b px-5 py-4" style={{ borderColor: 'rgba(94,204,255,0.12)' }}>
                <div>
                  <div className="text-[16px] font-bold">{row.account}</div>
                  <div className="text-[13px] text-slate-400">{row.server}</div>
                </div>
                <span className="text-[13px] text-slate-500">{new Date(row.created_at).toLocaleString('ja-JP')} 登録</span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void remove(row)}
                  className="ml-auto h-11 rounded-[4px] border px-3 text-[13px] font-bold text-slate-100 disabled:opacity-40"
                  style={{ borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.7)' }}
                >
                  登録を取り消す
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

const INPUT = 'h-12 w-full rounded-[4px] border px-3 text-[16px] text-slate-100 outline-none'
const INPUT_STYLE = { borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.7)' } as const

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[14px] text-slate-400">{label}</span>
      {children}
    </label>
  )
}
