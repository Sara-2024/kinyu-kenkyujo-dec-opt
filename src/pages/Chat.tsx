// 研究員との会話画面（AIチャットのモック）。
// 40〜50代向けに文字は大きく、操作は「入力して送る」だけ。
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PixelPerson } from '../components/PixelPerson'
import { useSiteSettings } from '../hooks/SiteSettingsContext'

interface Msg {
  from: 'ai' | 'user'
  text: string
}

const CANNED_REPLY =
  'ご質問ありがとうございます。順を追ってご説明しますので、少しお時間をください。'

export function Chat() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { characters: CHARACTERS } = useSiteSettings()
  const chara = id ? CHARACTERS[id] : undefined
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!chara) {
      navigate('/', { replace: true })
      return
    }
    setMessages([{ from: 'ai', text: chara.greeting }])
  }, [chara, navigate])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  if (!chara) return null

  const send = () => {
    const text = input.trim()
    if (!text) return
    setInput('')
    setMessages((m) => [...m, { from: 'user', text }])
    setTimeout(() => setMessages((m) => [...m, { from: 'ai', text: CANNED_REPLY }]), 700)
  }

  return (
    <div className="relative flex h-screen w-full flex-col overflow-hidden" style={{ background: '#0a1120' }}>
      {/* 方眼グリッド */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(rgba(94,204,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(94,204,255,0.03) 1px, transparent 1px)',
          backgroundSize: '44px 44px',
        }}
      />

      {/* ヘッダー */}
      <header
        className="relative z-10 flex items-center gap-4 border-b px-5 py-3"
        style={{ background: 'rgba(8,14,26,0.95)', borderColor: 'var(--panel-border)' }}
      >
        <Link
          to="/"
          className="rounded-[5px] border px-4 py-2.5 text-[15px] font-bold text-slate-100 transition hover:brightness-125"
          style={{ background: 'var(--panel-bg)', borderColor: 'var(--panel-border)' }}
        >
          ← 研究所へ戻る
        </Link>
        <div
          className="flex items-center gap-3 rounded-[5px] border px-4 py-1.5"
          style={{ background: 'var(--panel-bg)', borderColor: 'var(--panel-border)' }}
        >
          <div className="scale-75">
            <PixelPerson look={chara.look} s={3.4} />
          </div>
          <div>
            <p className="text-[17px] font-bold leading-tight text-white">
              {chara.role}　<span className="font-dot" style={{ color: chara.color }}>{chara.name}</span>
            </p>
            <p className="font-mono text-[11px] tracking-[0.2em] text-slate-500">MARKET RESEARCH LAB</p>
          </div>
        </div>
      </header>

      {/* メッセージ一覧 */}
      <div ref={listRef} className="relative z-10 mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-5 py-6">
        <div className="flex flex-col gap-5">
          {messages.map((m, i) =>
            m.from === 'ai' ? (
              <div key={i} className="flex items-end gap-3">
                <div className="shrink-0">
                  <PixelPerson look={chara.look} s={3} />
                </div>
                <div
                  className="max-w-[75%] rounded-[10px] rounded-bl-[3px] border px-5 py-3.5 text-[16px] font-bold leading-relaxed text-slate-100"
                  style={{ background: 'var(--panel-bg)', borderColor: 'var(--panel-border)', boxShadow: 'var(--panel-glow)' }}
                >
                  {m.text}
                </div>
              </div>
            ) : (
              <div key={i} className="flex justify-end">
                <div
                  className="max-w-[75%] rounded-[10px] rounded-br-[3px] border px-5 py-3.5 text-[16px] font-bold leading-relaxed"
                  style={{
                    background: 'rgba(250,204,21,0.14)',
                    borderColor: 'rgba(250,204,21,0.45)',
                    color: '#ffe9a8',
                  }}
                >
                  {m.text}
                </div>
              </div>
            ),
          )}
        </div>
      </div>

      {/* 入力欄 */}
      <div className="relative z-10 border-t px-5 py-4" style={{ background: 'rgba(8,14,26,0.95)', borderColor: 'var(--panel-border)' }}>
        <div className="mx-auto flex w-full max-w-3xl items-center gap-3">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder={`${chara.name}に質問してみましょう…`}
            className="min-w-0 flex-1 rounded-[6px] border px-4 py-3.5 text-[16px] font-bold text-slate-100 outline-none placeholder:text-slate-500 focus:border-[var(--accent)]"
            style={{ background: 'rgba(9,17,31,0.9)', borderColor: 'var(--panel-border)' }}
          />
          <button
            type="button"
            onClick={send}
            className="whitespace-nowrap rounded-[6px] border px-6 py-3.5 text-[16px] font-bold transition hover:brightness-110 active:translate-y-px"
            style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607' }}
          >
            送信 ▶
          </button>
        </div>
        <p className="font-mono mx-auto mt-2 w-full max-w-3xl text-[11px] tracking-wide text-slate-600">
          ここでの会話は判断の材料であり、売買の指示や利益の保証ではありません。
        </p>
      </div>
    </div>
  )
}
