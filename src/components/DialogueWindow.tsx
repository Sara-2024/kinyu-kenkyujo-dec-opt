// ノベルゲーム風の会話ウィンドウ（SPEC R-08-11 / R-08-12 / R-08-13 準拠）。
// 画面遷移せず、研究所の画面の上にオーバーレイで開く。
//
// 「おまかせ接続」モードを併せ持つ。
// 売りたいのは “設定はAIが代わりに全部やる” という体験なので、
// お客様に入力していただくのは連絡先だけ。残りはAIが順に片づける様子を見せる。
import { useEffect, useRef, useState } from 'react'
import type { Character } from '../data/characters'
import { clearConnection, loadConnection, newConnection, saveConnection, type Connection } from '../data/connection'
import { ControlPanel } from './ControlPanel'
import type { useBridge } from '../hooks/useBridge'
import { saveLead } from '../data/leads'
import { CONNECT_STEPS, CONNECT_TALK, USER_STEPS, validateEmail } from '../data/setupFlow'
import { PixelPerson } from './PixelPerson'

type Phase = 'talk' | 'email' | 'sent' | 'connecting' | 'done' | 'control'

export function DialogueWindow({
  character,
  onClose,
  bridge,
}: {
  character: Character
  onClose: () => void
  bridge: ReturnType<typeof useBridge>
}) {
  const [aiText, setAiText] = useState(character.greeting)
  const [shown, setShown] = useState(0)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)

  // ── おまかせ接続 ──
  const [phase, setPhase] = useState<Phase>('talk')
  const [stepIndex, setStepIndex] = useState(0) // いま作業中の工程
  const [error, setError] = useState<string | null>(null)
  const [conn, setConn] = useState<Connection | null>(() => loadConnection())

  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const emailRef = useRef('')

  const clearTimers = () => {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }

  // キャラが替わったときの初期状態。
  // すでに接続ずみで、担当がアルゴなら、設定のやり直しではなく管理画面から始める。
  useEffect(() => {
    clearTimers()
    const saved = loadConnection()
    setConn(saved)
    setInput('')
    setBusy(false)
    setStepIndex(0)
    setError(null)

    if (saved && character.id === 'algo') {
      setPhase('control')
      setAiText(
        saved.running
          ? 'おかえりなさい。エンジンは順調に動いています。設定を変えるか、私に相談するか、上のボタンでお選びください。'
          : 'おかえりなさい。いまは停止中です。再開もこの画面からどうぞ。',
      )
      return
    }
    setPhase('talk')
    setAiText(saved && character.id === 'yui' ? '設定はもうお済みですね。ご用があれば何なりと。' : character.greeting)
  }, [character])

  useEffect(() => () => clearTimers(), [])

  // タイプライター表示
  useEffect(() => {
    setShown(0)
    const id = setInterval(() => {
      setShown((n) => {
        if (n >= aiText.length) {
          clearInterval(id)
          return n
        }
        return n + 1
      })
    }, 24)
    return () => clearInterval(id)
  }, [aiText])

  useEffect(() => {
    if (phase === 'email') inputRef.current?.focus()
  }, [phase])

  const typing = shown < aiText.length

  // ── 通常会話 ──
  const ask = (q: string) => {
    if (busy || !q.trim()) return
    if (character.startsSetup && q.trim() === character.startsSetup) {
      setPhase('email')
      setInput('')
      setError(null)
      setAiText('かしこまりました。接続用のツールをお送りします。難しい設定は、そのツールが代わりに全部やります。')
      return
    }
    const question = q.trim()
    setBusy(true)
    setAiText('…')
    timers.current.push(
      setTimeout(() => {
        setAiText(character.answers[question] ?? character.fallback)
        setBusy(false)
      }, 700),
    )
  }

  // ── メール送信 → ツールの起動を待つ ──
  const sendTool = () => {
    const message = validateEmail(input)
    if (message) {
      setError(message)
      return
    }
    setError(null)
    emailRef.current = input.trim()
    void saveLead(input.trim())
    setPhase('sent')
    setAiText(
      `${input.trim()} 宛に接続ツールをお送りしました。ダウンロードして開いていただければ、あとは私が引き継ぎます。`,
    )
    // ツールが起動されたら自動で接続がはじまる
    timers.current.push(setTimeout(() => startConnecting(), 4200))
  }

  // ── 接続開始（ツール起動後。ここから先はお客様の操作なし） ──
  const startConnecting = () => {
    setPhase('connecting')
    setStepIndex(0)
    setAiText(CONNECT_TALK[0])

    // 各工程を順番に片づけていく
    let elapsed = 0
    CONNECT_STEPS.forEach((step, i) => {
      elapsed += step.ms
      timers.current.push(
        setTimeout(() => {
          const next = i + 1
          setStepIndex(next)
          const talk = CONNECT_TALK[Math.min(next, CONNECT_TALK.length - 1)]
          if (next < CONNECT_STEPS.length) {
            setAiText(talk)
          } else {
            const created = newConnection(emailRef.current)
            // 実機がつながっていれば、本物の口座情報で上書きする
            if (bridge.live && bridge.status) {
              if (bridge.status.account) created.account = String(bridge.status.account)
              if (bridge.status.server) created.server = String(bridge.status.server)
            }
            saveConnection(created)
            setConn(created)
            setPhase('done')
            setAiText(
              '接続が完了しました。もう設定は終わっています。次からはこの画面を開くだけで、止めたり設定を変えたりできます。',
            )
          }
        }, elapsed),
      )
    })
  }


  /** 実機がつながっていれば、工程の結果を本物の値に差し替える */
  const liveDone = (index: number, fallbackText: string) => {
    if (!bridge.live || !bridge.status) return fallbackText
    if (index === 1 && bridge.status.account) {
      return `口座 ${bridge.status.account} ／ ${bridge.status.server ?? ''}`
    }
    return fallbackText
  }

  /** 連携後だけ出す「設定 / 相談」の切り替え */
  const canSwitch = !!conn && character.id === 'algo' && (phase === 'control' || phase === 'talk')

  const switchTo = (next: 'control' | 'talk') => {
    if (phase === next) return
    clearTimers()
    setBusy(false)
    setInput('')
    setPhase(next)
    setAiText(
      next === 'control'
        ? '設定の画面です。停止も、ロットなどの変更もここから行えます。'
        : 'なんでしょうか。稼働のことでも、相場のことでも構いませんよ。',
    )
  }

  const inFlow = phase !== 'talk'

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-50 flex justify-center px-4 pb-4">
      <div
        className="pointer-events-auto flex max-h-[calc(100vh-70px)] w-full max-w-[920px] flex-col rounded-[8px] border backdrop-blur-md"
        style={{
          background: 'rgba(7, 14, 27, 0.74)', // 背後のフロアがぼけて透ける（R-08-12）
          borderColor: 'var(--panel-border)',
          boxShadow: '0 0 30px rgba(94,204,255,0.12), 0 12px 40px rgba(0,0,0,0.55)',
        }}
      >
        <div className="accent-line h-px w-full rounded-t-[8px]" />

        {/* ── ヘッダー（名札） ── */}
        <div className="flex shrink-0 items-center gap-3 border-b px-5 py-2.5" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
          <div className="-my-1 shrink-0">
            <PixelPerson look={character.look} s={2.6} />
          </div>
          <span className="h-4 w-[2px]" style={{ background: character.color, boxShadow: `0 0 8px ${character.color}` }} />
          <p className="text-[17px] font-bold leading-none text-white">
            {character.role}
            <span className="font-dot ml-2 text-[15px]" style={{ color: character.color }}>
              {character.name}
            </span>
          </p>
          {inFlow ? (
            <p
              className="font-mono ml-2 rounded-[3px] border px-2 py-1 text-[11px] font-bold tracking-wide"
              style={{ borderColor: 'rgba(250,204,21,0.5)', background: 'rgba(250,204,21,0.1)', color: '#ffd23e' }}
            >
              {phase === 'email'
                ? 'おまかせ接続'
                : phase === 'sent'
                  ? 'ツール送信ずみ'
                  : phase === 'connecting'
                    ? '接続中…'
                    : phase === 'control'
                      ? '管理画面'
                      : '接続完了'}
            </p>
          ) : (
            character.statusText && (
              <p
                className="font-mono ml-2 hidden rounded-[3px] border px-2 py-1 text-[11px] tracking-wide text-slate-300 sm:block"
                style={{ borderColor: 'rgba(94,204,255,0.25)', background: 'rgba(94,204,255,0.06)' }}
              >
                いま: {character.statusText}
              </p>
            )
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="会話を閉じる"
            className="ml-auto flex h-9 w-9 items-center justify-center rounded-[4px] border text-[16px] font-bold text-slate-300 transition hover:brightness-150"
            style={{ borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.6)' }}
          >
            ✕
          </button>
        </div>

        {/* ── 連携後の切り替え（設定 / 相談） ── */}
        {canSwitch && (
          <div className="flex shrink-0 gap-2 border-b px-5 py-2.5" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            {([
              { key: 'control', label: '⚙ 設定・停止' },
              { key: 'talk', label: '💬 相談する' },
            ] as const).map((t) => {
              const active = phase === t.key
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => switchTo(t.key)}
                  className="rounded-[5px] border px-5 py-2.5 text-[14px] font-bold transition hover:brightness-125 active:translate-y-px"
                  style={
                    active
                      ? {
                          borderColor: 'var(--accent)',
                          background: 'rgba(94,204,255,0.16)',
                          color: '#fff',
                          boxShadow: '0 0 12px rgba(94,204,255,0.25)',
                        }
                      : { borderColor: 'rgba(148,163,184,0.3)', background: 'rgba(10,18,32,0.5)', color: '#94a3b8' }
                  }
                >
                  {t.label}
                </button>
              )
            })}
          </div>
        )}

        {/* ヘッダー以外はスクロールさせ、画面が短くてもはみ出さないようにする */}
        <div className="min-h-0 flex-1 overflow-y-auto">
        {/* ── メインテキスト ── */}
        <div className="min-h-[72px] cursor-pointer px-6 pb-3 pt-4" onClick={() => setShown(aiText.length)}>
          <p className="text-[16px] font-bold leading-relaxed text-slate-100">
            {aiText.slice(0, shown)}
            {typing && <span className="cursor-blink ml-0.5 inline-block h-4 w-2.5 bg-[var(--accent)] align-middle" />}
            {!typing && !busy && !inFlow && (
              <span className="animate-bob ml-1 inline-block text-[13px] text-[var(--accent)]">▼</span>
            )}
          </p>
        </div>

        {/* ══════ 通常会話 ══════ */}
        {phase === 'talk' && (
          <>
            <div className="flex flex-wrap gap-2.5 px-6 pb-3">
              {(conn && character.connectedChoices ? character.connectedChoices : character.choices).map((c) => {
                const isSetup = character.startsSetup === c
                return (
                  <button
                    key={c}
                    type="button"
                    disabled={busy}
                    onClick={() => ask(c)}
                    className="rounded-[5px] border px-4 py-2.5 text-[14px] font-bold transition hover:brightness-125 active:translate-y-px disabled:opacity-40"
                    style={
                      isSetup
                        ? {
                            borderColor: '#a16207',
                            background: 'rgba(250,204,21,0.92)',
                            color: '#1c1607',
                            boxShadow: '0 0 14px rgba(250,204,21,0.3)',
                          }
                        : { borderColor: 'rgba(94,204,255,0.45)', background: 'rgba(94,204,255,0.08)', color: '#e8edf5' }
                    }
                  >
                    {isSetup ? `▶ ${c}` : c}
                  </button>
                )
              })}
            </div>

            <div className="flex items-center gap-3 border-t px-5 py-3.5" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    ask(input)
                    setInput('')
                  }
                }}
                disabled={busy}
                placeholder={`${character.name}に自由に質問できます…`}
                className="min-w-0 flex-1 rounded-[5px] border px-4 py-3 text-[15px] font-bold text-slate-100 outline-none placeholder:text-slate-500 focus:border-[var(--accent)] disabled:opacity-50"
                style={{ background: 'rgba(9,17,31,0.85)', borderColor: 'rgba(148,163,184,0.35)' }}
              />
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  ask(input)
                  setInput('')
                }}
                className="whitespace-nowrap rounded-[5px] border px-5 py-3 text-[15px] font-bold transition hover:brightness-110 active:translate-y-px disabled:opacity-40"
                style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607' }}
              >
                送信（はなす）▶
              </button>
            </div>
          </>
        )}

        {/* ══════ 唯一の入力：連絡先 ══════ */}
        {phase === 'email' && (
          <div className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
              <span className="rounded-[4px] border px-2.5 py-1 text-[12px] font-bold text-[#35f58a]"
                    style={{ borderColor: 'rgba(53,245,138,0.4)', background: 'rgba(53,245,138,0.08)' }}>
                ✓ MT5のパスワードは不要
              </span>
              <span className="rounded-[4px] border px-2.5 py-1 text-[12px] font-bold text-[#35f58a]"
                    style={{ borderColor: 'rgba(53,245,138,0.4)', background: 'rgba(53,245,138,0.08)' }}>
                ✓ 口座番号の入力も不要
              </span>
              <span className="rounded-[4px] border px-2.5 py-1 text-[12px] font-bold text-[#35f58a]"
                    style={{ borderColor: 'rgba(53,245,138,0.4)', background: 'rgba(53,245,138,0.08)' }}>
                ✓ 設定画面はありません
              </span>
            </div>

            <div className="mb-2 flex items-baseline gap-3">
              <span className="h-3 w-[2px]" style={{ background: 'var(--accent)', boxShadow: '0 0 6px var(--accent)' }} />
              <label className="text-[14px] font-bold text-slate-200">メールアドレス</label>
              <span className="text-[12px] text-slate-400">このアドレスに接続ツールをお送りします。</span>
            </div>

            <div className="flex items-center gap-3">
              <input
                ref={inputRef}
                value={input}
                inputMode="email"
                onChange={(e) => {
                  setInput(e.target.value)
                  setError(null)
                }}
                onKeyDown={(e) => e.key === 'Enter' && sendTool()}
                placeholder="example@gmail.com"
                className="min-w-0 flex-1 rounded-[5px] border px-4 py-3 text-[16px] font-bold text-slate-100 outline-none placeholder:text-slate-500 focus:border-[var(--accent)]"
                style={{
                  background: 'rgba(9,17,31,0.85)',
                  borderColor: error ? 'rgba(224,75,75,0.8)' : 'rgba(148,163,184,0.35)',
                }}
              />
              <button
                type="button"
                onClick={sendTool}
                className="whitespace-nowrap rounded-[5px] border px-6 py-3 text-[15px] font-bold transition hover:brightness-110 active:translate-y-px"
                style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607' }}
              >
                ツールを受け取る ▶
              </button>
            </div>

            <div className="mt-2.5 flex items-center gap-4">
              {error && <p className="text-[13px] font-bold text-[#ff8484]">⚠ {error}</p>}
              <button
                type="button"
                onClick={() => setPhase('talk')}
                className="font-mono ml-auto text-[12px] text-slate-400 underline-offset-4 hover:underline"
              >
                ← もどる
              </button>
            </div>
          </div>
        )}

        {/* ══════ ツールを送った直後：お客様の手順を見せる ══════ */}
        {phase === 'sent' && (
          <div className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <p className="mb-3 text-[13px] font-bold text-slate-400">お客様にしていただくのは、この3つだけです。</p>
            <ol className="mb-4 space-y-2.5">
              {USER_STEPS.map((u) => (
                <li key={u.no} className="flex items-start gap-3">
                  <span
                    className="font-mono mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-bold"
                    style={{
                      background: u.no === 3 ? 'rgba(53,245,138,0.15)' : 'rgba(94,204,255,0.12)',
                      color: u.no === 3 ? '#35f58a' : 'var(--accent)',
                      border: `1px solid ${u.no === 3 ? 'rgba(53,245,138,0.5)' : 'rgba(94,204,255,0.4)'}`,
                    }}
                  >
                    {u.no}
                  </span>
                  <span>
                    <span className="text-[15px] font-bold text-white">{u.title}</span>
                    <span className="ml-2 text-[13px] text-slate-400">{u.detail}</span>
                  </span>
                </li>
              ))}
            </ol>

            <div
              className="flex flex-wrap items-center gap-4 rounded-[6px] border px-5 py-4"
              style={{ borderColor: 'rgba(250,204,21,0.4)', background: 'rgba(250,204,21,0.06)' }}
            >
              <span className="spin h-5 w-5 shrink-0 rounded-full"
                    style={{ border: '2px solid rgba(250,204,21,0.25)', borderTopColor: '#ffd23e' }} />
              <p className="text-[15px] font-bold text-slate-200">ツールが起動されるのを待っています…</p>
              <span className="font-mono ml-auto text-[12px] tracking-wide text-slate-500">
                起動を検知すると自動ではじまります
              </span>
            </div>
          </div>
        )}

        {/* ══════ AIが代わりに作業している様子 ══════ */}
        {(phase === 'connecting' || phase === 'done') && (
          <div className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <p className="mb-2.5 text-[13px] font-bold text-slate-400">
              お客様のパソコンで、接続ツールが作業しています。
            </p>
            <ol className="space-y-2">
              {CONNECT_STEPS.map((step, i) => {
                const finished = i < stepIndex
                const current = i === stepIndex && phase === 'connecting'
                if (!finished && !current) return null
                return (
                  <li key={step.working} className="step-in flex items-center gap-3">
                    {finished ? (
                      <span className="check-pop flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[12px] font-bold"
                            style={{ background: 'rgba(53,245,138,0.15)', color: '#35f58a', border: '1px solid rgba(53,245,138,0.5)' }}>
                        ✓
                      </span>
                    ) : (
                      <span
                        className="spin h-5 w-5 shrink-0 rounded-full"
                        style={{
                          border: '2px solid rgba(94,204,255,0.2)',
                          borderTopColor: 'var(--accent)',
                        }}
                      />
                    )}
                    <span className={`text-[15px] font-bold ${finished ? 'text-slate-300' : 'text-white'}`}>
                      {finished ? liveDone(i, step.done) : `${step.working}…`}
                    </span>
                  </li>
                )
              })}
            </ol>

            {/* 進捗バー */}
            <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full" style={{ background: 'rgba(94,204,255,0.12)' }}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${(stepIndex / CONNECT_STEPS.length) * 100}%`,
                  background: 'var(--accent)',
                  boxShadow: '0 0 10px var(--accent)',
                }}
              />
            </div>

            {/* 完了後：そのまま管理画面へ進める */}
            {phase === 'done' && (
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setPhase('control')
                    setAiText('こちらが管理画面です。停止も、ロットなどの設定変更も、すべてここから行えます。')
                  }}
                  className="rounded-[5px] border px-6 py-3 text-[15px] font-bold transition hover:brightness-110 active:translate-y-px"
                  style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607' }}
                >
                  管理画面をひらく ▶
                </button>
                <button
                  type="button"
                  onClick={() => switchTo('talk')}
                  className="rounded-[5px] border px-5 py-3 text-[15px] font-bold text-slate-100 transition hover:brightness-125"
                  style={{ borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.6)' }}
                >
                  💬 相談する
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-[5px] border px-5 py-3 text-[15px] font-bold text-slate-100 transition hover:brightness-125"
                  style={{ borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.6)' }}
                >
                  研究所にもどる
                </button>
              </div>
            )}
          </div>
        )}

        {/* ══════ 管理画面（接続ずみのお客様が次に開くのはここ） ══════ */}
        {phase === 'control' && conn && (
          <ControlPanel
            bridge={bridge}
            conn={conn}
            onChange={(next) => {
              saveConnection(next)
              setConn(next)
            }}
            onReset={() => {
              clearConnection()
              setConn(null)
              setPhase('talk')
              setInput('')
              setAiText(character.greeting)
            }}
          />
        )}

        </div>
      </div>
    </div>
  )
}
