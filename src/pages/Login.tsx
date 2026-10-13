// 受付。研究所の入口で、受付案内のユイが順に聞いてくる。
//   はじめての方: 入場パスワード → MT5 の口座番号 → お名前 → パスワード → 入室
//   会員の方:     口座番号・パスワード → 入室
// 会員 ＝ MT5 の口座番号。メールは聞かない。
// 台詞は characters.ts の RECEPTION にまとめてある。
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { PixelPerson } from '../components/PixelPerson'
import { authCheckEntry, authErrorMessage } from '../data/auth'
import { RECEPTION } from '../data/characters'
import { useAuth } from '../hooks/AuthContext'
import { useSiteSettings } from '../hooks/SiteSettingsContext'
import { supabase } from '../lib/supabase'

type Step = 'welcome' | 'entry' | 'account' | 'name' | 'password' | 'login' | 'done'

/** 口座番号を数に。全角の数字も受ける。数字でなければ null */
function parseAccount(value: string): number | null {
  const s = value.trim().replace(/[０-９]/g, (d) => String.fromCharCode(d.charCodeAt(0) - 0xfee0))
  if (!/^[0-9]{1,13}$/.test(s)) return null
  const n = Number(s)
  return n > 0 ? n : null
}

const RED = '#ff8484'

/**
 * ユイの大きさ。場面の高さ（画面の高さから、題字と会話ウィンドウを除いた残り）に合わせる。
 * 小さい画面でも、頭が切れない程度に縮める
 */
function useSpriteScale(ref: React.RefObject<HTMLDivElement | null>): number {
  const [s, setS] = useState(12)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => {
      const h = el.clientHeight
      // 人物の高さはだいたい 17 × s。カウンター（70px）と余白ぶんを引く
      setS(Math.max(5, Math.min(12, (h - 52 - 20) / 17)))
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return s
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
  const [account, setAccount] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')

  const { shown, typing, skip } = useTypewriter(line)
  const sceneRef = useRef<HTMLDivElement | null>(null)
  const spriteScale = useSpriteScale(sceneRef)
  const firstInput = useRef<HTMLInputElement | null>(null)
  /** 「驚いた顔」を戻すタイマー。画面が外れたあとに触らないよう片付ける */
  const surpriseTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (surpriseTimer.current) clearTimeout(surpriseTimer.current)
    },
    [],
  )

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
      if (surpriseTimer.current) clearTimeout(surpriseTimer.current)
      surpriseTimer.current = setTimeout(() => setSurprised(false), 1400)
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
      go('account', ok ? `${RECEPTION.entryOk} ${RECEPTION.askAccount}` : RECEPTION.askAccount)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const submitAccount = () => {
    if (parseAccount(account) == null) {
      say(RECEPTION.accountBad, true)
      return
    }
    go('name', RECEPTION.askName)
  }

  const submitName = () => {
    if (!name.trim()) {
      say(RECEPTION.nameBad, true)
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
      await register(parseAccount(account) ?? 0, name.trim(), password, entry.trim())
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
    const acct = parseAccount(account)
    if (acct == null) {
      say(RECEPTION.accountBad, true)
      return
    }
    if (!password) return
    if (!supabase) {
      fail(new Error('NOT_CONFIGURED'))
      return
    }
    setBusy(true)
    say(RECEPTION.checkingLogin)
    try {
      await login(acct, password)
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
    else if (step === 'account') submitAccount()
    else if (step === 'name') submitName()
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
    step === 'entry' ? 1 : step === 'account' ? 2 : step === 'name' ? 3 : step === 'password' ? 4 : step === 'done' && entry ? 5 : 0

  const modeLabel = step === 'login' ? 'ログイン' : step === 'welcome' ? 'ログイン ／ 会員登録' : '会員登録'

  return (
    <div
      className="fixed inset-0 flex items-center justify-center overflow-hidden select-none"
      style={{
        backgroundColor: '#0c1730',
        backgroundImage:
          'radial-gradient(ellipse 60% 55% at 50% 45%, rgba(94,204,255,0.16), transparent 70%), linear-gradient(rgba(94,204,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(94,204,255,0.05) 1px, transparent 1px), linear-gradient(180deg, #0a1428 0%, #11203c 55%, #0d1a33 100%)',
        backgroundSize: '100% 100%, 48px 48px, 48px 48px, 100% 100%',
      }}
    >
      {/* 真ん中の一列だけ使う。上から 題字 → ユイ → 会話ウィンドウ */}
      <div className="flex h-full max-h-[840px] w-[min(94vw,40rem)] flex-col items-center overflow-y-auto py-5">
        {/* ── 題字 ── */}
        <div className="shrink-0 text-center">
          <p className="font-mono text-[12px] tracking-[0.35em] text-slate-400">MARKET RESEARCH LAB</p>
          <p className="mt-1 text-[28px] font-bold leading-none text-white">トレード研究所</p>
          <p className="mt-2 text-[17px] font-bold" style={{ color: 'var(--accent)' }}>
            {modeLabel}
          </p>
        </div>

        {/* ── ユイ（カウンター越しに、こちらを向いて話す） ── */}
        <div ref={sceneRef} className="relative min-h-[160px] w-full flex-1">
          <div
            className="pointer-events-none absolute left-1/2 bottom-0 h-full w-[560px] -translate-x-1/2"
            style={{ background: 'radial-gradient(ellipse 45% 55% at 50% 70%, rgba(94,204,255,0.2), transparent 70%)' }}
          />
          <div className={`absolute left-1/2 bottom-[22px] -translate-x-1/2 ${typing ? 'animate-bob' : ''}`}>
            <PixelPerson look={yui.look} s={spriteScale} surprised={surprised} />
          </div>
          <div className="absolute left-1/2 bottom-0 w-[360px] max-w-full -translate-x-1/2">
            <div className="h-[14px] rounded-t-[5px] border border-b-0 border-[#2a1608] bg-[#8a5a2b]" />
            <div className="rounded-b-[5px] border border-t-0 border-[#2a1608] bg-[#6e4520] px-4 py-2 text-center" style={{ boxShadow: 'inset 0 -12px 20px rgba(0,0,0,0.25)' }}>
              <p className="font-mono text-[15px] font-bold tracking-[0.4em] text-amber-100">RECEPTION</p>
            </div>
          </div>
        </div>

        {/* ── 会話ウィンドウ（吹き出し） ── */}
        <div className="relative mt-5 w-full shrink-0">
          {/* 吹き出しのしっぽ */}
          <div
            className="absolute left-1/2 top-[-9px] h-4 w-4 -translate-x-1/2 border-l border-t"
            style={{ background: 'var(--panel-bg)', borderColor: 'var(--panel-border)', transform: 'translateX(-50%) rotate(45deg)' }}
          />
          <div
            className="relative rounded-[8px] border backdrop-blur-[2px]"
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
                <p className="ml-auto flex items-center gap-1.5 text-[13px] font-bold tracking-wide text-slate-300">
                  {[1, 2, 3, 4].map((k) => (
                    <span
                      key={k}
                      className="h-2 w-6 rounded-full"
                      style={{ background: progress >= k ? 'var(--accent)' : 'rgba(94,204,255,0.18)', boxShadow: progress >= k ? '0 0 6px var(--accent)' : undefined }}
                    />
                  ))}
                  <span className="ml-1 text-[12px] text-slate-400">{progress === 1 ? '入場確認' : progress === 2 ? '口座番号' : progress === 3 ? 'お名前' : progress === 4 ? 'パスワード' : '完了'}</span>
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

            {/* 選択肢（RPG のように、真ん中に縦に並べる） */}
            {step === 'welcome' && (
              <div className="flex flex-col items-center gap-2.5 border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
                <Choice primary onClick={() => go('entry', RECEPTION.askEntry)}>
                  ▶ {RECEPTION.choiceNew}
                </Choice>
                <Choice onClick={() => go('login', RECEPTION.askLogin)}>{RECEPTION.choiceMember}</Choice>
              </div>
            )}

            {/* 入力（真ん中に寄せる） */}
            {step !== 'welcome' && step !== 'done' && (
              <form onSubmit={onSubmit} className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
                <div className="mx-auto flex w-full max-w-[26rem] flex-col gap-3">
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
                  {(step === 'account' || step === 'login') && (
                    <Field
                      ref={firstInput}
                      label={RECEPTION.labels.account}
                      type="text"
                      value={account}
                      onChange={setAccount}
                      autoComplete="username"
                      inputMode="numeric"
                      disabled={busy}
                    />
                  )}
                  {step === 'name' && (
                    <Field
                      ref={firstInput}
                      label={RECEPTION.labels.name}
                      type="text"
                      value={name}
                      onChange={setName}
                      autoComplete="name"
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

                <div className="mx-auto mt-4 flex w-full max-w-[26rem] flex-col items-center gap-2.5">
                  <button
                    type="submit"
                    disabled={busy || !ready}
                    className="h-12 w-full rounded-[5px] border px-6 text-[16px] font-bold transition hover:brightness-110 active:translate-y-px disabled:opacity-40"
                    style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607', boxShadow: '0 0 14px rgba(250,204,21,0.3)' }}
                  >
                    {busy
                      ? '…'
                      : step === 'entry'
                        ? `${RECEPTION.buttons.tell} ▶`
                        : step === 'account' || step === 'name'
                          ? `${RECEPTION.buttons.next} ▶`
                          : step === 'password'
                            ? `${RECEPTION.buttons.register} ▶`
                            : `${RECEPTION.buttons.login} ▶`}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={restart}
                    className="h-11 rounded-[5px] px-4 text-[15px] font-bold text-slate-400 transition hover:text-slate-200 disabled:opacity-40"
                  >
                    {RECEPTION.back}
                  </button>
                </div>
              </form>
            )}
          </div>
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
      className="h-12 w-full max-w-[26rem] rounded-[5px] border px-5 text-[16px] font-bold transition hover:brightness-125 active:translate-y-px"
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
  inputMode,
  disabled,
}: {
  ref?: React.Ref<HTMLInputElement>
  label: string
  type: string
  value: string
  onChange: (v: string) => void
  autoComplete?: string
  /** スマホで数字のキーボードを出すとき 'numeric' */
  inputMode?: 'numeric' | 'text'
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
        inputMode={inputMode}
        onChange={(e) => onChange(e.target.value)}
        className="h-12 w-full rounded-[5px] border px-4 text-[17px] font-bold text-slate-100 outline-none focus:border-[var(--accent)] disabled:opacity-50"
        style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'rgba(148,163,184,0.35)' }}
      />
    </label>
  )
}
