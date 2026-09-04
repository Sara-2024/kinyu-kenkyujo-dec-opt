// 受付。研究所の入口で、受付案内のユイが順に聞いてくる。
//   はじめての方: 入場パスワード → メールアドレス → パスワード → 入室
//   会員の方:     メールアドレス・パスワード → 入室
// 台詞は characters.ts の RECEPTION にまとめてある。
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { PixelPerson } from '../components/PixelPerson'
import { authCheckEntry, authErrorMessage } from '../data/auth'
import { RECEPTION } from '../data/characters'
import { validateEmail } from '../data/setupFlow'
import { useAuth } from '../hooks/AuthContext'
import { useSiteSettings } from '../hooks/SiteSettingsContext'
import { supabase } from '../lib/supabase'

type Step = 'welcome' | 'entry' | 'email' | 'password' | 'login' | 'done'

const RED = '#ff8484'

// 受付の舞台。ソシャゲのログイン画面のように、画面の真ん中にこの大きさで置く
const STAGE_W = 880
const SCENE_H = 300 // 壁〜床の場面の高さ
const FLOOR_Y = 262 // 場面の中で床が始まる高さ（カウンターの下端）
const DESK_H = 68
const STAGE_MAX_H = 760 // いちばん背が高い状態（パスワード入力）の目安

/** 画面に収まる倍率。大きい画面でも等倍より広げない */
function useStageScale(): number {
  const calc = () => Math.min(1, (window.innerWidth - 24) / STAGE_W, (window.innerHeight - 24) / STAGE_MAX_H)
  const [scale, setScale] = useState(calc)
  useEffect(() => {
    const onResize = () => setScale(calc())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return scale
}

/** 一文字ずつ出す */
function useTypewriter(text: string): { shown: string; typing: boolean; skip: () => void } {
  const [n, setN] = useState(0)
  useEffect(() => {
    setN(0)
    const id = setInterval(() => {
      setN((k) => {
        if (k >= text.length) {
          clearInterval(id)
          return k
        }
        return k + 1
      })
    }, 24)
    return () => clearInterval(id)
  }, [text])
  return { shown: text.slice(0, n), typing: n < text.length, skip: () => setN(text.length) }
}

export function Login() {
  const { member, ready, login, register } = useAuth()
  const { characters, t } = useSiteSettings()
  const yui = characters.yui

  const [step, setStep] = useState<Step>('welcome')
  const [line, setLine] = useState(() => t(RECEPTION.welcome))
  const [tone, setTone] = useState<'normal' | 'warn'>('normal')
  const [busy, setBusy] = useState(false)
  const [surprised, setSurprised] = useState(false)
  const [leave, setLeave] = useState(false)

  const [entry, setEntry] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')

  const { shown, typing, skip } = useTypewriter(line)
  const scale = useStageScale()
  const firstInput = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    firstInput.current?.focus()
  }, [step])

  // 登録・ログインが済んだら、ひとこと言ってから研究所へ
  useEffect(() => {
    if (step !== 'done') return
    const id = setTimeout(() => setLeave(true), 1600)
    return () => clearTimeout(id)
  }, [step])

  // 登録・ログインの直後は「ご案内しますね」を言ってから移る（busy の間は member が付いても待つ）
  if (ready && member && !busy && (step !== 'done' || leave)) return <Navigate to="/" replace />

  const say = (text: string, warn = false) => {
    setLine(t(text))
    setTone(warn ? 'warn' : 'normal')
    if (warn) {
      setSurprised(true)
      setTimeout(() => setSurprised(false), 1400)
    }
  }

  const go = (next: Step, text: string) => {
    setStep(next)
    say(text)
  }

  const fail = (err: unknown) => say(authErrorMessage(err), true)

  const submitEntry = async () => {
    if (!entry.trim()) return
    if (!supabase) {
      fail(new Error('NOT_CONFIGURED'))
      return
    }
    setBusy(true)
    say(RECEPTION.checkingEntry)
    try {
      const ok = await authCheckEntry(entry.trim())
      if (ok === false) {
        say(RECEPTION.entryBad, true)
        return
      }
      // ok === null は「確認する仕組みがまだ無い」。本登録のときに確かめる
      go('email', ok ? `${RECEPTION.entryOk} ${RECEPTION.askEmail}` : RECEPTION.askEmail)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const submitEmail = () => {
    if (validateEmail(email) != null) {
      say(RECEPTION.emailBad, true)
      return
    }
    go('password', RECEPTION.askPassword)
  }

  const submitRegister = async () => {
    if (password.length < 8) {
      say(RECEPTION.passwordShort, true)
      return
    }
    if (password !== confirm) {
      say(RECEPTION.passwordMismatch, true)
      return
    }
    setBusy(true)
    say(RECEPTION.registering)
    try {
      await register(email.trim(), password, entry.trim())
      go('done', RECEPTION.registered)
    } catch (err) {
      const msg = authErrorMessage(err)
      // 入場パスワードで弾かれたら、そこからやり直し
      if (msg.includes('入場パスワード')) {
        setStep('entry')
        say(RECEPTION.entryBad, true)
      } else {
        fail(err)
      }
    } finally {
      setBusy(false)
    }
  }

  const submitLogin = async () => {
    if (!email.trim() || !password) return
    if (!supabase) {
      fail(new Error('NOT_CONFIGURED'))
      return
    }
    setBusy(true)
    say(RECEPTION.checkingLogin)
    try {
      await login(email.trim(), password)
      go('done', RECEPTION.loggedIn)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (step === 'entry') void submitEntry()
    else if (step === 'email') submitEmail()
    else if (step === 'password') void submitRegister()
    else if (step === 'login') void submitLogin()
  }

  const restart = () => {
    setEntry('')
    setPassword('')
    setConfirm('')
    go('welcome', RECEPTION.welcome)
  }

  const progress =
    step === 'entry' ? 1 : step === 'email' ? 2 : step === 'password' ? 3 : step === 'done' && entry ? 4 : 0

  return (
    <div className="fixed inset-0 flex items-center justify-center overflow-hidden select-none" style={{ background: '#05080f' }}>
      {/* 画面の外側は暗くして、真ん中の受付に目が行くようにする */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: 'radial-gradient(ellipse 60% 55% at 50% 50%, rgba(94,204,255,0.07), transparent 70%)' }}
      />

      {/* ── 受付の舞台（固定サイズ。画面が小さいときは丸ごと縮める） ── */}
      <div
        className="relative overflow-hidden rounded-[10px] border"
        style={{
          width: STAGE_W,
          transform: `scale(${scale})`,
          borderColor: 'var(--panel-border)',
          boxShadow: 'var(--panel-glow), 0 30px 80px rgba(0,0,0,0.6)',
          backgroundColor: '#070b14',
          backgroundImage:
            'linear-gradient(rgba(94,204,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(94,204,255,0.05) 1px, transparent 1px), linear-gradient(180deg, #060a14 0%, #0c1629 100%)',
          backgroundSize: '48px 48px, 48px 48px, 100% 100%',
        }}
      >
        <div className="accent-line h-px w-full" />

        {/* 受付の場面（壁・看板・ユイ・カウンター・床） */}
        <div className="relative" style={{ height: SCENE_H }}>
          {/* 灯り */}
          {[14, 86].map((x) => (
            <div key={x} className="absolute top-0 h-[70px] w-[2px]" style={{ left: `${x}%`, background: 'linear-gradient(180deg, var(--accent), transparent)', opacity: 0.5 }} />
          ))}
          {[14, 86].map((x) => (
            <div
              key={`l${x}`}
              className="absolute top-[70px] h-2.5 w-12 -translate-x-1/2 rounded-b-[6px]"
              style={{ left: `${x}%`, background: 'rgba(94,204,255,0.5)', boxShadow: '0 0 36px 12px rgba(94,204,255,0.16)' }}
            />
          ))}
          {/* 看板 */}
          <div
            className="absolute left-1/2 top-[26px] -translate-x-1/2 rounded-[4px] border px-5 py-2"
            style={{ borderColor: 'rgba(94,204,255,0.4)', background: 'rgba(9,17,31,0.85)', boxShadow: 'var(--panel-glow)' }}
          >
            <p className="font-mono whitespace-nowrap text-[13px] font-bold tracking-[0.35em]" style={{ color: 'var(--accent)' }}>
              ▍RECEPTION 受付
            </p>
          </div>
          {/* 受付の灯り */}
          <div
            className="pointer-events-none absolute left-1/2 top-[40px] h-[260px] w-[520px] -translate-x-1/2"
            style={{ background: 'radial-gradient(ellipse 50% 50% at 50% 60%, rgba(94,204,255,0.14), transparent 70%)' }}
          />
          {/* 床（カウンターの下端から場面の下端まで） */}
          <div
            className="absolute inset-x-0 bottom-0"
            style={{
              top: FLOOR_Y,
              backgroundColor: '#0d1729',
              backgroundImage:
                'linear-gradient(90deg, rgba(94,204,255,0.08) 1px, transparent 1px), linear-gradient(180deg, #101c33 0%, #0a1222 100%)',
              backgroundSize: '96px 100%, 100% 100%',
              borderTop: '1px solid rgba(94,204,255,0.35)',
              boxShadow: '0 -1px 12px rgba(94,204,255,0.35)',
            }}
          />
          {/* ユイとカウンター */}
          <div className="absolute left-1/2 w-[380px] -translate-x-1/2" style={{ top: FLOOR_Y - DESK_H }}>
            <div className="absolute left-1/2 bottom-[26px] -translate-x-1/2">
              <PixelPerson look={yui.look} s={6} surprised={surprised} />
            </div>
            <div className="relative">
              <div className="h-4 rounded-t-[4px] border border-b-0 border-[#2a1608] bg-[#8a5a2b]" />
              <div className="rounded-b-[4px] border border-t-0 border-[#2a1608] bg-[#6e4520] px-4 py-3 text-center">
                <p className="font-mono text-[15px] font-bold tracking-[0.35em] text-amber-100">RECEPTION</p>
              </div>
            </div>
          </div>
        </div>

        {/* ── 会話ウィンドウ ── */}
        <div
          className="relative mx-5 -mt-3 mb-5 rounded-[8px] border backdrop-blur-[2px]"
        style={{ background: 'var(--panel-bg)', borderColor: 'var(--panel-border)', boxShadow: 'var(--panel-glow)' }}
      >
        <div className="accent-line h-px w-full rounded-t-[8px]" />

        {/* 名札 */}
        <div className="flex items-center gap-3 border-b px-5 py-2.5" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
          <div className="-my-1 shrink-0">
            <PixelPerson look={yui.look} s={2.6} />
          </div>
          <span className="h-4 w-[2px]" style={{ background: yui.color, boxShadow: `0 0 8px ${yui.color}` }} />
          <p className="text-[17px] font-bold leading-none text-white">
            {yui.role}
            <span className="font-dot ml-2 text-[15px]" style={{ color: yui.color }}>
              {yui.name}
            </span>
          </p>
          {progress > 0 && (
            <p className="font-mono ml-auto flex items-center gap-1.5 text-[11px] tracking-wide text-slate-400">
              {[1, 2, 3].map((k) => (
                <span
                  key={k}
                  className="h-2 w-6 rounded-full"
                  style={{ background: progress >= k ? 'var(--accent)' : 'rgba(94,204,255,0.18)', boxShadow: progress >= k ? '0 0 6px var(--accent)' : undefined }}
                />
              ))}
              <span className="ml-1">{progress === 1 ? '入場確認' : progress === 2 ? '連絡先' : progress === 3 ? 'パスワード' : '完了'}</span>
            </p>
          )}
          {step === 'login' && (
            <p className="font-mono ml-auto rounded-[3px] border px-2 py-1 text-[11px] tracking-wide text-slate-300" style={{ borderColor: 'rgba(94,204,255,0.25)', background: 'rgba(94,204,255,0.06)' }}>
              会員証の確認
            </p>
          )}
        </div>

        {/* 台詞 */}
        <div className="min-h-[76px] cursor-pointer px-6 pb-3 pt-4" onClick={skip}>
          <p className="text-[17px] font-bold leading-relaxed" style={{ color: tone === 'warn' ? RED : '#f1f5f9' }}>
            {shown}
            {typing && <span className="cursor-blink ml-0.5 inline-block h-4 w-2.5 bg-[var(--accent)] align-middle" />}
            {!typing && !busy && step !== 'done' && (
              <span className="animate-bob ml-1 inline-block text-[13px] text-[var(--accent)]">▼</span>
            )}
          </p>
        </div>

        {/* 選択肢・入力 */}
        {step === 'welcome' && (
          <div className="flex flex-wrap gap-3 border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <Choice primary onClick={() => go('entry', RECEPTION.askEntry)}>
              ▶ {RECEPTION.choiceNew}
            </Choice>
            <Choice onClick={() => go('login', RECEPTION.askLogin)}>{RECEPTION.choiceMember}</Choice>
          </div>
        )}

        {step !== 'welcome' && step !== 'done' && (
          <form onSubmit={onSubmit} className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <div className="flex flex-col gap-3">
              {step === 'entry' && (
                <Field
                  ref={firstInput}
                  label={RECEPTION.labels.entry}
                  type="password"
                  value={entry}
                  onChange={setEntry}
                  autoComplete="off"
                  disabled={busy}
                />
              )}
              {(step === 'email' || step === 'login') && (
                <Field
                  ref={firstInput}
                  label={RECEPTION.labels.email}
                  type="email"
                  value={email}
                  onChange={setEmail}
                  autoComplete="username"
                  disabled={busy}
                />
              )}
              {step === 'login' && (
                <Field
                  label={RECEPTION.labels.password}
                  type="password"
                  value={password}
                  onChange={setPassword}
                  autoComplete="current-password"
                  disabled={busy}
                />
              )}
              {step === 'password' && (
                <>
                  <Field
                    ref={firstInput}
                    label={RECEPTION.labels.newPassword}
                    type="password"
                    value={password}
                    onChange={setPassword}
                    autoComplete="new-password"
                    disabled={busy}
                  />
                  <Field
                    label={RECEPTION.labels.confirm}
                    type="password"
                    value={confirm}
                    onChange={setConfirm}
                    autoComplete="new-password"
                    disabled={busy}
                  />
                </>
              )}
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={busy || !ready}
                className="h-12 rounded-[5px] border px-6 text-[16px] font-bold transition hover:brightness-110 active:translate-y-px disabled:opacity-40"
                style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607', boxShadow: '0 0 14px rgba(250,204,21,0.3)' }}
              >
                {busy
                  ? '…'
                  : step === 'entry'
                    ? `${RECEPTION.buttons.tell} ▶`
                    : step === 'email'
                      ? `${RECEPTION.buttons.next} ▶`
                      : step === 'password'
                        ? `${RECEPTION.buttons.register} ▶`
                        : `${RECEPTION.buttons.login} ▶`}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={restart}
                className="h-12 rounded-[5px] border px-4 text-[15px] font-bold text-slate-300 transition hover:brightness-125 disabled:opacity-40"
                style={{ borderColor: 'rgba(148,163,184,0.3)', background: 'rgba(10,18,32,0.5)' }}
              >
                {RECEPTION.back}
              </button>
            </div>
          </form>
        )}
        </div>
      </div>
    </div>
  )
}

function Choice({ children, onClick, primary }: { children: ReactNode; onClick: () => void; primary?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="h-12 rounded-[5px] border px-5 text-[16px] font-bold transition hover:brightness-125 active:translate-y-px"
      style={
        primary
          ? { borderColor: '#a16207', background: 'rgba(250,204,21,0.92)', color: '#1c1607', boxShadow: '0 0 14px rgba(250,204,21,0.3)' }
          : { borderColor: 'rgba(94,204,255,0.45)', background: 'rgba(94,204,255,0.08)', color: '#e8edf5' }
      }
    >
      {children}
    </button>
  )
}

function Field({
  ref,
  label,
  type,
  value,
  onChange,
  autoComplete,
  disabled,
}: {
  ref?: React.Ref<HTMLInputElement>
  label: string
  type: string
  value: string
  onChange: (v: string) => void
  autoComplete?: string
  disabled?: boolean
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[14px] font-bold text-slate-300">{label}</span>
      <input
        ref={ref}
        type={type}
        value={value}
        disabled={disabled}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        className="h-12 w-full rounded-[5px] border px-4 text-[17px] font-bold text-slate-100 outline-none focus:border-[var(--accent)] disabled:opacity-50"
        style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'rgba(148,163,184,0.35)' }}
      />
    </label>
  )
}
