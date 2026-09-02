import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { authErrorMessage } from '../data/auth'
import { supabase } from '../lib/supabase'
import { useAuth } from '../hooks/AuthContext'

type Mode = 'login' | 'register'

export function Login() {
  const { member, ready, login, register } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [entry, setEntry] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (ready && member) return <Navigate to="/" replace />

  const submit = async () => {
    setError(null)
    if (!supabase) {
      setError(authErrorMessage(new Error('NOT_CONFIGURED')))
      return
    }
    if (mode === 'register') {
      if (password !== confirm) {
        setError('パスワード（確認）が一致しません。')
        return
      }
    }
    setBusy(true)
    try {
      if (mode === 'register') await register(email, password, entry)
      else await login(email, password)
    } catch (err) {
      setError(authErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative h-screen w-full overflow-hidden" style={{ background: '#070b14' }}>
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(rgba(94,204,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(94,204,255,0.04) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
        }}
      />
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: 'radial-gradient(ellipse 60% 50% at 50% 40%, rgba(94,204,255,0.08), transparent 70%)' }}
      />

      <div
        className="absolute left-1/2 top-[46%] w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-[4px] border px-8 py-8"
        style={{
          background: 'var(--panel-bg)',
          borderColor: 'var(--panel-border)',
          boxShadow: 'var(--panel-glow)',
        }}
      >
        <p className="font-mono text-[12px] font-bold tracking-[0.3em]" style={{ color: 'var(--accent)' }}>
          MARKET RESEARCH LAB
        </p>
        <h1 className="mt-2 text-[22px] font-bold text-slate-100">トレード研究所</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-slate-400">
          {mode === 'login'
            ? '登録したメールアドレスとパスワードで入室してください。'
            : '初回のみ、入場パスワードとメールアドレス、ご自身のパスワードを登録します。'}
        </p>

        <div className="mt-5 flex gap-2">
          {(
            [
              ['login', 'ログイン'],
              ['register', '新規登録'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => {
                setMode(id)
                setError(null)
              }}
              className="h-11 flex-1 rounded-[4px] border text-[15px] font-bold"
              style={{
                borderColor: mode === id ? 'var(--accent)' : 'var(--panel-border)',
                color: mode === id ? '#081018' : '#e8edf5',
                background: mode === id ? 'var(--accent)' : 'transparent',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <form
          className="mt-5 flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          {mode === 'register' && (
            <Field
              label="入場パスワード"
              type="password"
              value={entry}
              onChange={setEntry}
              autoComplete="off"
            />
          )}
          <Field label="メールアドレス" type="email" value={email} onChange={setEmail} autoComplete="username" />
          <Field
            label={mode === 'register' ? 'パスワード（8文字以上）' : 'パスワード'}
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
          />
          {mode === 'register' && (
            <Field
              label="パスワード（確認）"
              type="password"
              value={confirm}
              onChange={setConfirm}
              autoComplete="new-password"
            />
          )}

          {error && (
            <p className="text-[15px] leading-relaxed" style={{ color: '#ff8484' }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy || !ready}
            className="mt-2 h-12 rounded-[4px] text-[16px] font-bold text-[#081018] disabled:opacity-50"
            style={{ background: 'var(--accent)' }}
          >
            {busy ? '確認しています…' : mode === 'login' ? '入室する' : '登録して入室する'}
          </button>
        </form>
      </div>
    </div>
  )
}

function Field({
  label,
  type,
  value,
  onChange,
  autoComplete,
}: {
  label: string
  type: string
  value: string
  onChange: (v: string) => void
  autoComplete?: string
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[15px] font-bold text-slate-200">{label}</span>
      <input
        type={type}
        value={value}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        className="h-12 w-full rounded-[4px] border px-3 text-[16px] text-slate-100 outline-none"
        style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
      />
    </label>
  )
}
