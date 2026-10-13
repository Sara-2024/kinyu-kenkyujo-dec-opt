// 管理サイトの入口。口座番号ではなく「管理サイトの合言葉」1つで入る。
// 見た目はロビー（dreamland/）に合わせる。入れたら /admin へ。
import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { authErrorMessage } from '../data/auth'
import { useAuth } from '../hooks/AuthContext'

const C = {
  ink: '#30384f',
  muted: '#68718a',
  gold: '#cbbb98',
  goldDeep: '#aa9461',
  cream2: '#fffdf2',
  lav: '#7665a9',
  teal: '#69b4bc',
}

export function AdminGate() {
  const { ready, member, loginOperator } = useAuth()
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!ready) return <div style={{ minHeight: '100vh', background: '#dbe5f2' }} />
  if (member?.role === 'admin') return <Navigate to="/admin" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy || !password) return
    setBusy(true)
    setError(null)
    try {
      await loginOperator(password)
    } catch (err) {
      setError(authErrorMessage(err).replace('口座番号またはパスワードが違います。', '合言葉が違います。'))
      setBusy(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: 24,
        fontFamily: '"Hiragino Kaku Gothic ProN","Hiragino Sans","Yu Gothic",Meiryo,sans-serif',
        color: C.ink,
        background: 'linear-gradient(165deg,#d1e4ee 0%,#dae2f4 40%,#eee6f6 75%,#fbf4e8 100%)',
      }}
    >
      <form
        onSubmit={(e) => void submit(e)}
        style={{
          width: 'min(100%, 420px)',
          padding: '34px 32px 30px',
          borderRadius: 22,
          background: 'linear-gradient(150deg,rgba(255,253,248,.95),rgba(245,241,246,.95))',
          border: '1px solid #fcf9df',
          boxShadow: 'inset 0 0 0 4px rgba(255,248,234,.8), 0 18px 60px rgba(72,85,116,.25)',
        }}
      >
        <p style={{ margin: 0, fontFamily: 'Georgia,serif', letterSpacing: '.26em', fontSize: 12, color: C.goldDeep }}>DREAMLAND · OPERATIONS</p>
        <h1 style={{ margin: '8px 0 0', fontFamily: '"Hiragino Mincho ProN","Yu Mincho",serif', fontWeight: 600, fontSize: 24, letterSpacing: '.12em' }}>
          管理サイト
        </h1>
        <p style={{ margin: '8px 0 22px', fontSize: 14, color: C.muted, lineHeight: 1.8 }}>
          運営の方だけが入れます。管理サイトの合言葉を入力してください。
        </p>
        <label style={{ display: 'grid', gap: 6, fontSize: 13, color: C.muted }}>
          <span>合言葉</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            style={{
              height: 50,
              padding: '0 14px',
              borderRadius: 12,
              border: '1px solid #d8d3e8',
              background: '#fff',
              fontSize: 17,
              color: C.ink,
              outline: 'none',
            }}
          />
        </label>
        {error && (
          <p role="alert" style={{ margin: '10px 0 0', fontSize: 14, color: '#b74c4c' }}>
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || !password}
          style={{
            marginTop: 18,
            width: '100%',
            minHeight: 56,
            borderRadius: 34,
            border: '2px solid #faf8df',
            color: '#fcfff7',
            fontFamily: '"Hiragino Mincho ProN","Yu Mincho",serif',
            fontSize: 17,
            letterSpacing: '.16em',
            background: 'linear-gradient(120deg,#76b8be,#578d9a)',
            boxShadow: '0 0 0 4px rgba(216,232,222,.45), inset 0 0 0 2px rgba(202,233,220,.49), 0 7px 20px rgba(92,113,129,.3)',
            opacity: busy || !password ? 0.7 : 1,
            cursor: busy || !password ? 'default' : 'pointer',
          }}
        >
          {busy ? '確かめています…' : '管理サイトに入る'}
        </button>
        <p style={{ margin: '18px 0 0', fontSize: 12, color: C.muted, textAlign: 'center', letterSpacing: '.06em' }}>
          合言葉は、管理サイトの中の「管理サイトの合言葉」から変えられます。
        </p>
      </form>
    </div>
  )
}
