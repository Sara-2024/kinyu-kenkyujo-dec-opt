// ---------------------------------------------------------------
// 研究所のメイン画面。
//  - 1440×810 の固定ステージを画面にフィットさせ、
//    ホイールで拡大縮小・ドラッグで移動できる（40〜50代向けに大きなボタンも用意）
//  - キャラをクリックするとズームインしてから /chat/:id へ遷移
//  - 「…」の常時吹き出しは廃止。かわりに経済指標・要人発言などの
//    AI通知が研究員の頭上に随時ポップアップする
// ---------------------------------------------------------------
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { DialogueWindow } from '../components/DialogueWindow'
import { PixelPerson } from '../components/PixelPerson'
import { BigChart, CodePanel, Desk, DeskMonitor, ServerRack, StatusMonitor, ToolBox } from '../components/Panels'
import { CHARACTERS, type Character } from '../data/characters'
import { useAuth } from '../hooks/AuthContext'
import { useBridge } from '../hooks/useBridge'
import { useMarket } from '../hooks/useMarket'

const STAGE_W = 1440
const STAGE_H = 810
const HUD_H = 52
const FLOOR_TOP = 470 // ステージ内の壁と床の境目(px)

const ZONES = {
  analysis: { from: 0, to: 44.5, color: '#5eccff', en: 'ANALYSIS DESK', jp: '分析デスク' },
  engine: { from: 44.5, to: 78.5, color: '#35f58a', en: 'CORE ENGINE ROOM', jp: 'コア・エンジンルーム' },
  garage: { from: 78.5, to: 100, color: '#ff9d4d', en: 'DEV GARAGE', jp: '開発ガレージ' },
} as const

/** キャラの立ち位置（ステージ%）。描画とズームインの両方で使う */
const CHAR_POS: Record<string, { x: number; bottom: number; s: number }> = {
  rin: { x: 16, bottom: 30, s: 5 },
  jin: { x: 29, bottom: 30, s: 5.4 },
  algo: { x: 61.5, bottom: 30, s: 5.4 },
  gantz: { x: 87, bottom: 30, s: 5.4 },
  yui: { x: 50, bottom: 12, s: 5.6 },
}

const JIN_SHOCK_LINE = 'おや…？ 妙な動きだ。指標か、それとも──ちょっと金利を見てくる。'

/** AI通知のネタ帳。tone で吹き出しの色が変わる */
interface NewsItem {
  charId: string
  tone: 'alert' | 'warn' | 'info'
  label: string
  text: string
}
const NEWS_POOL: NewsItem[] = [
  { charId: 'jin', tone: 'warn', label: '指標接近', text: '⏰ まもなく米・雇用統計の発表です（21:30）。値が飛びやすい時間帯ですよ。' },
  { charId: 'jin', tone: 'alert', label: '速報', text: '📢 速報：トランプ大統領の発言が伝わりました。ドル円が振れやすくなっています。' },
  { charId: 'rin', tone: 'info', label: '注目', text: '👀 USD/JPYが直近高値に接近中。ここを抜けるかどうかが今日のポイントです。' },
  { charId: 'algo', tone: 'info', label: '稼働報告', text: '🤖 システムの状態は、チャート上の稼働表示で確認できます。' },
  { charId: 'gantz', tone: 'info', label: '開発中', text: '🔧 新しいインジケーターのテストがもうすぐ終わる。近々ここで公開する。' },
  { charId: 'jin', tone: 'warn', label: '指標接近', text: '⏰ 30分後に日銀総裁の会見があります。円絡みは値動きに注意です。' },
]

const TONE_STYLE: Record<NewsItem['tone'], { border: string; glow: string; labelColor: string }> = {
  alert: { border: 'rgba(255,107,107,0.8)', glow: '0 0 18px rgba(224,75,75,0.3)', labelColor: '#ff6b6b' },
  warn: { border: 'rgba(255,210,62,0.8)', glow: '0 0 18px rgba(255,210,62,0.25)', labelColor: '#ffd23e' },
  info: { border: 'rgba(94,204,255,0.8)', glow: '0 0 18px rgba(94,204,255,0.25)', labelColor: '#5eccff' },
}

function Chara({
  character,
  x,
  bottom,
  s,
  onSelect,
  z = 10,
  dimmed = false,
  surprised = false,
  bubble,
  exclaim = false,
}: {
  character: Character
  x: number
  bottom: number
  s: number
  onSelect: (id: string) => void
  z?: number
  dimmed?: boolean
  surprised?: boolean
  bubble?: { label: string; text: string; tone: NewsItem['tone'] } | null
  exclaim?: boolean
}) {
  const tone = bubble ? TONE_STYLE[bubble.tone] : null
  return (
    <button
      type="button"
      onClick={() => onSelect(character.id)}
      className={`chara absolute flex -translate-x-1/2 flex-col items-center border-0 bg-transparent p-0 ${
        dimmed ? 'chara-dim' : ''
      }`}
      style={{ left: `${x}%`, bottom: `${bottom}%`, zIndex: z }}
      aria-label={`${character.role} ${character.name}と会話する`}
      title={`${character.name}と会話する`}
    >
      {/* AI通知・イベント吹き出し */}
      {bubble && !dimmed && tone && (
        <div className="news-in absolute bottom-full left-1/2 z-40 mb-3 w-64 -translate-x-1/2">
          <div
            className="rounded-[5px] border px-4 py-3 text-left backdrop-blur-[2px]"
            style={{ background: 'rgba(9,17,31,0.94)', borderColor: tone.border, boxShadow: tone.glow }}
          >
            <p className="font-mono mb-1 text-[10px] font-bold tracking-[0.3em]" style={{ color: tone.labelColor }}>
              ▎{bubble.label}
            </p>
            <p className="text-[14px] font-bold leading-relaxed text-slate-100">{bubble.text}</p>
          </div>
          <div
            className="mx-auto h-0 w-0 border-x-[8px] border-t-[8px] border-x-transparent"
            style={{ borderTopColor: tone.border }}
          />
        </div>
      )}

      <div className="relative flex flex-col items-center">
        {exclaim && !bubble && !dimmed && (
          <span className="animate-bob absolute -top-9 left-1/2 z-20 -translate-x-1/2 text-2xl font-bold text-yellow-300 drop-shadow-[0_0_8px_rgba(253,224,71,0.95)]">
            ！
          </span>
        )}
        <div
          className="plate mb-1.5 rounded-[3px] border px-3 py-1 text-center backdrop-blur-[2px]"
          style={{ background: 'rgba(10,18,32,0.88)', borderColor: 'rgba(148,163,184,0.5)' }}
        >
          <p className="whitespace-nowrap text-[15px] font-bold leading-tight text-white">{character.role}</p>
          <p className="font-dot whitespace-nowrap text-[12px] leading-tight" style={{ color: character.color }}>
            {character.name}
          </p>
        </div>
        <PixelPerson look={character.look} s={s} surprised={surprised} />
        {/* 「話せる」ことを示すマイクロコピー */}
        {!dimmed && (
          <p className="font-mono mt-1 text-[10px] tracking-[0.2em] text-slate-500">▶ CLICK</p>
        )}
      </div>
    </button>
  )
}

function Ticker({ price, dir }: { price: number; dir: number }) {
  const items: Array<[string, string, number]> = [
    ['USD/JPY', price.toFixed(2), dir],
    ['EUR/USD', '1.0842', -1],
    ['GBP/JPY', '201.55', 1],
    ['GOLD', '2,712.4', 1],
    ['BTC/USD', '112,480', -1],
    ['NIKKEI', '39,120', 1],
  ]
  const row = (key: string) => (
    <span key={key} className="flex shrink-0 items-center gap-6 pr-6">
      {items.map(([sym, val, d]) => (
        <span key={sym} className="font-mono flex items-center gap-1.5 text-[13px] tracking-wide">
          <span className="text-slate-400">{sym}</span>
          <span style={{ color: d >= 0 ? '#2fbf62' : '#e04b4b' }}>
            {d >= 0 ? '▲' : '▼'} {val}
          </span>
        </span>
      ))}
    </span>
  )
  return (
    <div className="relative mx-6 h-full min-w-0 flex-1 overflow-hidden">
      <div className="anim-marquee flex h-full w-max items-center">
        {row('a')}
        {row('b')}
      </div>
      <div className="pointer-events-none absolute inset-y-0 left-0 w-10 bg-gradient-to-r from-[#080e1a] to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-[#080e1a] to-transparent" />
    </div>
  )
}

function ZoneHeader({ zone, extra }: { zone: (typeof ZONES)[keyof typeof ZONES]; extra?: React.ReactNode }) {
  const center = (zone.from + zone.to) / 2
  return (
    <div className="absolute z-20 flex -translate-x-1/2 items-center gap-3" style={{ left: `${center}%`, top: 16 }}>
      <span className="h-4 w-[2px]" style={{ background: zone.color, boxShadow: `0 0 8px ${zone.color}` }} />
      <span className="font-mono whitespace-nowrap text-[12px] font-bold tracking-[0.3em]" style={{ color: zone.color }}>
        {zone.en}
      </span>
      <span className="whitespace-nowrap text-[15px] font-bold text-slate-200">{zone.jp}</span>
      {extra}
    </div>
  )
}

export function Lab() {
  const { member, logout } = useAuth()
  const tutorialKey = member ? `lab-tutorial-done:${member.id}` : 'lab-tutorial-done'
  // チュートリアルは会員ごとに初回だけ
  const [tutorial, setTutorial] = useState(() => !localStorage.getItem(tutorialKey))
  const { candles, price, dir, shocked, triggerShock } = useMarket()
  const bridge = useBridge()
  const [news, setNews] = useState<NewsItem | null>(null)
  const [dialogueId, setDialogueId] = useState<string | null>(null)

  // ───── パン・ズーム ─────
  const viewRef = useRef<HTMLDivElement>(null)
  const [base, setBase] = useState(0.5)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [animate, setAnimate] = useState(false)
  const zoomRef = useRef(zoom)
  const panRef = useRef(pan)
  zoomRef.current = zoom
  panRef.current = pan
  const dragState = useRef<{ sx: number; sy: number; px: number; py: number; moved: boolean } | null>(null)
  const suppressClick = useRef(false)

  useEffect(() => {
    const fit = () => {
      const w = window.innerWidth
      const h = window.innerHeight - HUD_H
      setBase(Math.min(w / STAGE_W, h / STAGE_H))
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [])

  // ホイールで拡大縮小（カーソル位置を中心に）
  useEffect(() => {
    const el = viewRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const cx = e.clientX - rect.left - rect.width / 2 - panRef.current.x
      const cy = e.clientY - rect.top - rect.height / 2 - panRef.current.y
      const z0 = zoomRef.current
      const z1 = Math.min(3, Math.max(0.6, z0 * Math.exp(-e.deltaY * 0.0014)))
      const k = z1 / z0
      setAnimate(false)
      setPan({ x: panRef.current.x - cx * (k - 1), y: panRef.current.y - cy * (k - 1) })
      setZoom(z1)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // ドラッグで移動
  const onPointerDown = (e: React.PointerEvent) => {
    dragState.current = { sx: e.clientX, sy: e.clientY, px: pan.x, py: pan.y, moved: false }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragState.current
    if (!d) return
    const dx = e.clientX - d.sx
    const dy = e.clientY - d.sy
    if (!d.moved && Math.hypot(dx, dy) > 6) d.moved = true
    if (d.moved) {
      setAnimate(false)
      setPan({ x: d.px + dx, y: d.py + dy })
    }
  }
  const onPointerUp = () => {
    if (dragState.current?.moved) {
      suppressClick.current = true
      setTimeout(() => (suppressClick.current = false), 0)
    }
    dragState.current = null
  }

  const resetView = useCallback(() => {
    setAnimate(true)
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [])
  const zoomBy = useCallback((k: number) => {
    setAnimate(true)
    setZoom((z) => Math.min(3, Math.max(0.6, z * k)))
  }, [])

  /** キャラへズームインして、その場に会話ウィンドウを開く（画面遷移しない） */
  const select = useCallback(
    (id: string) => {
      if (suppressClick.current) return
      if (tutorial && id !== 'yui') return
      const pos = CHAR_POS[id]
      if (!pos) return
      const targetZoom = 1.7
      const vh = window.innerHeight - HUD_H
      const cx = (pos.x / 100) * STAGE_W - STAGE_W / 2
      const footY = STAGE_H * (1 - pos.bottom / 100)
      const cy = footY - 70 - STAGE_H / 2
      setAnimate(true)
      setZoom(targetZoom)
      // キャラが会話ウィンドウの上（画面のやや上寄り）に来るようにずらす
      setPan({ x: -cx * base * targetZoom, y: -cy * base * targetZoom - vh * 0.18 })
      setDialogueId(id)
      if (tutorial) {
        setTutorial(false)
        localStorage.setItem(tutorialKey, '1')
      }
    },
    [tutorial, base, tutorialKey],
  )

  const closeDialogue = useCallback(() => {
    setDialogueId(null)
    resetView()
  }, [resetView])

  // Escで会話を閉じる
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeDialogue()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [closeDialogue])

  // AI通知のスケジューラ（チュートリアル中と急変動中は出さない）
  useEffect(() => {
    if (tutorial) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    let clearTimer: ReturnType<typeof setTimeout>
    let idx = 0
    const schedule = (delay: number) => {
      timer = setTimeout(() => {
        if (!alive) return
        const item = NEWS_POOL[idx % NEWS_POOL.length]
        idx++
        setNews(item)
        clearTimer = setTimeout(() => alive && setNews(null), 9000)
        schedule(14000 + Math.random() * 12000)
      }, delay)
    }
    schedule(5000)
    return () => {
      alive = false
      clearTimeout(timer)
      clearTimeout(clearTimer)
    }
  }, [tutorial])

  const bubbleFor = (id: string) => {
    if (dialogueId) return null
    if (shocked && id === 'jin') return { label: '急変動', text: JIN_SHOCK_LINE, tone: 'alert' as const }
    if (!shocked && news && news.charId === id) return { label: news.label, text: news.text, tone: news.tone }
    return null
  }

  const dimStyle = (o: number) => ({ opacity: tutorial ? o : 1 })
  const scale = base * zoom

  return (
    <div className="relative h-screen w-full overflow-hidden" style={{ background: '#070b14' }}>
      {/* ================= HUD ================= */}
      <header
        className="absolute inset-x-0 top-0 z-40 flex items-center border-b px-6"
        style={{ height: HUD_H, background: 'rgba(8,14,26,0.95)', borderColor: 'var(--panel-border)' }}
      >
        <span className="h-4 w-[3px]" style={{ background: 'var(--accent)', boxShadow: '0 0 8px var(--accent)' }} />
        <h1 className="font-mono ml-3 whitespace-nowrap text-[14px] font-bold tracking-[0.3em] text-slate-100">
          MARKET RESEARCH LAB
        </h1>
        <span className="ml-3 hidden whitespace-nowrap text-[13px] font-bold text-slate-400 md:inline">トレード研究所</span>
        <Ticker price={price} dir={dir} />
        <button
          type="button"
          onClick={triggerShock}
          disabled={shocked || tutorial}
          className="font-mono whitespace-nowrap rounded-[4px] border px-3.5 py-2 text-[13px] font-bold tracking-[0.12em] transition active:translate-y-px disabled:opacity-40"
          style={{
            background: 'rgba(250,204,21,0.92)',
            borderColor: '#a16207',
            color: '#1c1607',
            boxShadow: '0 0 12px rgba(250,204,21,0.25)',
          }}
        >
          ⚡ 急変動シミュレート
        </button>
        <div className="ml-3 flex items-center gap-2">
          <span className="hidden max-w-[12rem] truncate text-[13px] text-slate-400 lg:inline">{member?.email}</span>
          {member?.role === 'admin' && (
            <Link
              to="/admin"
              className="flex h-11 items-center rounded-[4px] border px-3 text-[13px] font-bold text-slate-100"
              style={{ borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.8)' }}
            >
              管理者
            </Link>
          )}
          <button
            type="button"
            onClick={() => void logout()}
            className="h-11 rounded-[4px] border px-3 text-[13px] font-bold text-slate-100"
            style={{ borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.8)' }}
          >
            ログアウト
          </button>
        </div>
      </header>

      {/* ================= ビュー（パン・ズームの受け皿） ================= */}
      <div
        ref={viewRef}
        className={`view-grab absolute inset-x-0 bottom-0 ${dragState.current?.moved ? 'dragging' : ''} ${
          shocked ? 'anim-shake' : ''
        }`}
        style={{ top: HUD_H }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        {/* ステージ：1440×810 の固定キャンバス */}
        <div
          className={`absolute left-1/2 top-1/2 ${animate ? 'stage-anim' : ''}`}
          style={{
            width: STAGE_W,
            height: STAGE_H,
            transform: `translate(calc(-50% + ${pan.x}px), calc(-50% + ${pan.y}px)) scale(${scale})`,
            transformOrigin: 'center',
          }}
        >
          {/* ===== 壁 ===== */}
          <div
            className="absolute inset-x-0 top-0"
            style={{ height: FLOOR_TOP, background: 'linear-gradient(#0a1322, #0e1930)' }}
          />
          {/* 壁の方眼グリッド */}
          <div
            className="pointer-events-none absolute inset-x-0 top-0"
            style={{
              height: FLOOR_TOP,
              backgroundImage:
                'linear-gradient(rgba(94,204,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(94,204,255,0.035) 1px, transparent 1px), linear-gradient(rgba(94,204,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(94,204,255,0.06) 1px, transparent 1px)',
              backgroundSize: '44px 44px, 44px 44px, 220px 220px, 220px 220px',
            }}
          />

          {/* ===== 床（壁よりはっきり明るいスチール） ===== */}
          <div
            className="absolute inset-x-0 bottom-0"
            style={{
              top: FLOOR_TOP,
              background: 'linear-gradient(#33405f, #1e2842 55%, #17203a)',
              backgroundImage:
                'linear-gradient(rgba(255,255,255,0.07), transparent 14%), repeating-linear-gradient(0deg, rgba(0,0,0,0.14) 0 2px, transparent 2px 56px)',
            }}
          />
          {/* 壁と床の境目：暗い目地 + 明るいハイライト */}
          <div className="absolute inset-x-0 h-[3px]" style={{ top: FLOOR_TOP - 3, background: '#05080f' }} />
          <div className="absolute inset-x-0 h-px" style={{ top: FLOOR_TOP, background: 'rgba(255,255,255,0.22)' }} />
          {/* 床の奥行き線 */}
          <div className="absolute inset-x-0 h-px" style={{ top: 575, background: 'rgba(0,0,0,0.35)' }} />
          <div className="absolute inset-x-0 h-px" style={{ top: 576, background: 'rgba(255,255,255,0.08)' }} />
          <div className="absolute inset-x-0 h-px" style={{ top: 680, background: 'rgba(0,0,0,0.35)' }} />
          <div className="absolute inset-x-0 h-px" style={{ top: 681, background: 'rgba(255,255,255,0.08)' }} />
          {/* 全体ビネット */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{ background: 'radial-gradient(ellipse 75% 70% at 50% 42%, transparent 58%, rgba(3,6,13,0.5) 100%)' }}
          />

          {/* ===== 中央ベイ＝エンジンルーム ===== */}
          <div
            className="absolute"
            style={{
              left: `${ZONES.engine.from}%`,
              width: `${ZONES.engine.to - ZONES.engine.from}%`,
              top: 0,
              height: FLOOR_TOP,
              background: shocked
                ? 'rgba(224,75,75,0.06)'
                : 'linear-gradient(rgba(53,245,138,0.05), rgba(53,245,138,0.015))',
              boxShadow: shocked ? 'inset 0 0 60px rgba(224,75,75,0.15)' : 'inset 0 0 60px rgba(53,245,138,0.06)',
              ...dimStyle(0.5),
            }}
          >
            <div
              className="absolute inset-0"
              style={{
                background: 'repeating-linear-gradient(115deg, transparent 0 90px, rgba(255,255,255,0.015) 90px 130px)',
              }}
            />
            <div className="absolute inset-x-[8%] bottom-0 flex items-end justify-between">
              {[0, 1, 2, 3, 4].map((i) => (
                <ServerRack key={i} shocked={shocked} tall={i % 2 === 0} />
              ))}
            </div>
            {shocked && <div className="anim-alarm pointer-events-none absolute inset-0 opacity-25" />}
          </div>

          {/* ベイの区切り */}
          {[ZONES.engine.from, ZONES.engine.to].map((l) => (
            <div
              key={l}
              className="absolute top-0 w-px"
              style={{
                left: `${l}%`,
                height: FLOOR_TOP,
                background: 'linear-gradient(rgba(94,204,255,0.35), rgba(94,204,255,0.08))',
                boxShadow: '0 0 8px rgba(94,204,255,0.25)',
              }}
            />
          ))}

          {/* 床のエッジライト */}
          {(Object.keys(ZONES) as Array<keyof typeof ZONES>).map((k) => {
            const z = ZONES[k]
            const color = k === 'engine' && shocked ? '#e04b4b' : z.color
            return (
              <div
                key={k}
                className="absolute h-[3px]"
                style={{
                  left: `calc(${z.from}% + 8px)`,
                  width: `calc(${z.to - z.from}% - 16px)`,
                  top: FLOOR_TOP + 1,
                  background: color,
                  opacity: 0.6,
                  boxShadow: `0 0 14px ${color}`,
                }}
              />
            )
          })}

          {/* ゾーン見出し */}
          <div style={dimStyle(0.5)}>
            <ZoneHeader zone={ZONES.analysis} />
            <ZoneHeader zone={ZONES.engine} extra={<StatusMonitor shocked={shocked} />} />
            <ZoneHeader zone={ZONES.garage} />
          </div>
          <p
            className="font-mono absolute z-10 -translate-x-1/2 text-[10px] tracking-[0.4em] text-slate-600"
            style={{ left: '61.5%', top: 44, ...dimStyle(0.5) }}
          >
            AUTHORIZED PERSONNEL ONLY
          </p>

          {/* ===== パネル ===== */}
          <BigChart
            candles={candles}
            price={price}
            dir={dir}
            shocked={shocked}
            style={{ left: '3%', top: 64, width: '38.5%', height: 324, ...dimStyle(0.45) }}
          />
          <CodePanel style={{ right: '3%', top: 64, width: '16%', ...dimStyle(0.45) }} />

          {/* ===== 床の照明溜まり ===== */}
          {[
            { left: '22%', color: 'rgba(94,204,255,0.08)' },
            { left: '61.5%', color: shocked ? 'rgba(224,75,75,0.1)' : 'rgba(53,245,138,0.08)' },
            { left: '89%', color: 'rgba(255,157,77,0.08)' },
            { left: '50%', color: 'rgba(255,190,120,0.12)', low: true },
          ].map((p, i) => (
            <div
              key={i}
              className="pointer-events-none absolute -translate-x-1/2"
              style={{
                left: p.left,
                top: p.low ? '76%' : FLOOR_TOP,
                width: '26%',
                height: '22%',
                background: `radial-gradient(ellipse 55% 60% at 50% 30%, ${p.color}, transparent 70%)`,
              }}
            />
          ))}

          {/* ===== 家具とキャラ ===== */}
          <Chara character={CHARACTERS.rin} {...CHAR_POS.rin} onSelect={select} dimmed={tutorial} bubble={bubbleFor('rin')} />
          <Chara
            character={CHARACTERS.jin}
            {...CHAR_POS.jin}
            onSelect={select}
            dimmed={tutorial}
            surprised={shocked}
            bubble={bubbleFor('jin')}
          />
          <Desk style={{ left: '11%', bottom: '17%', width: '23%', zIndex: 12, ...dimStyle(0.5) }}>
            <div className="flex items-end justify-center gap-8">
              <DeskMonitor bars={[35, 55, 70, 45, 60, 40]} />
              <DeskMonitor bars={[60, 42, 55, 68, 47, 62]} />
            </div>
          </Desk>

          <Chara character={CHARACTERS.algo} {...CHAR_POS.algo} z={15} onSelect={select} dimmed={tutorial} bubble={bubbleFor('algo')} />

          <Chara character={CHARACTERS.gantz} {...CHAR_POS.gantz} onSelect={select} dimmed={tutorial} bubble={bubbleFor('gantz')} />
          <Desk style={{ left: '81%', bottom: '17%', width: '15%', zIndex: 12, ...dimStyle(0.5) }}>
            <div className="flex items-end justify-center gap-5">
              <ToolBox />
              <DeskMonitor bars={[45, 62, 38, 70, 52, 44]} />
            </div>
          </Desk>

          {/* ===== エントランス ===== */}
          <Chara character={CHARACTERS.yui} {...CHAR_POS.yui} z={35} onSelect={select} exclaim bubble={bubbleFor('yui')} />
          <div className="absolute z-[36] -translate-x-1/2" style={{ left: '50%', bottom: '3%', width: 380 }}>
            <div className="h-3.5 rounded-t-[4px] border border-b-0 border-[#2a1608] bg-[#8a5a2b]" />
            <div className="rounded-b-[4px] border border-t-0 border-[#2a1608] bg-[#6e4520] px-4 py-2.5 text-center">
              <p className="font-mono text-[14px] font-bold tracking-[0.35em] text-amber-100">RECEPTION</p>
            </div>
          </div>

          {/* ===== チュートリアル（ステージ内でユイに追従） ===== */}
          {tutorial && (
            <>
              <div
                className="pointer-events-none absolute inset-0 z-30"
                style={{ background: 'radial-gradient(circle at 50% 76%, transparent 0 150px, rgba(2,6,17,0.62) 300px)' }}
              />
              <div
                className="tutorial-ring pointer-events-none absolute z-30 h-52 w-52 -translate-x-1/2 rounded-full border-2 border-yellow-300/80"
                style={{ left: '50%', bottom: '5%' }}
              />
              <div className="tutorial-pop absolute z-50 w-[26rem] -translate-x-1/2" style={{ left: '50%', bottom: '46%' }}>
                <div
                  className="rounded-[5px] border px-6 py-5 text-center backdrop-blur-[2px]"
                  style={{
                    background: 'rgba(9,17,31,0.94)',
                    borderColor: 'rgba(253,224,71,0.85)',
                    boxShadow: '0 0 24px rgba(253,224,71,0.2)',
                  }}
                >
                  <p className="font-mono mb-2 text-[12px] tracking-[0.35em] text-yellow-300">TUTORIAL</p>
                  <p className="text-[18px] font-bold leading-relaxed text-white">
                    ようこそ、トレード研究所へ！
                    <br />
                    まずは受付の<span className="text-yellow-300">ユイ</span>をクリックして
                    <br />
                    初期設定を始めましょう！
                  </p>
                </div>
                <div className="mx-auto h-0 w-0 border-x-[9px] border-t-[9px] border-x-transparent border-t-yellow-300/85" />
              </div>
            </>
          )}

          {/* ===== 案内 ===== */}
          <p className="font-mono absolute inset-x-0 bottom-2 z-10 text-center text-[12px] tracking-[0.25em] text-[#5a6a88]">
            研究員をクリックすると相談できます ── 表示レートは配信の都合により実際と異なる場合があります
          </p>
        </div>
      </div>

      {/* ================= ズーム操作（大きなボタン） ================= */}
      <div className="absolute bottom-5 right-5 z-40 flex flex-col items-end gap-2">
        {[
          { label: '＋', hint: '拡大', fn: () => zoomBy(1.25) },
          { label: '−', hint: '縮小', fn: () => zoomBy(0.8) },
          { label: '⟲', hint: '全体', fn: resetView },
        ].map((b) => (
          <button
            key={b.hint}
            type="button"
            onClick={b.fn}
            className="flex h-12 w-12 flex-col items-center justify-center rounded-[6px] border text-slate-100 transition hover:brightness-125 active:translate-y-px"
            style={{ background: 'var(--panel-bg)', borderColor: 'var(--panel-border)', boxShadow: 'var(--panel-glow)' }}
            aria-label={b.hint}
          >
            <span className="text-xl font-bold leading-none">{b.label}</span>
            <span className="font-mono text-[10px] text-slate-400">{b.hint}</span>
          </button>
        ))}
        <p className="font-mono mt-1 rounded-[4px] border px-2 py-1 text-[10px] tracking-wide text-slate-500"
           style={{ background: 'rgba(8,14,26,0.8)', borderColor: 'rgba(94,204,255,0.15)' }}>
          ドラッグで移動 / ホイールで拡大
        </p>
      </div>

      {/* ================= 会話ウィンドウ（オーバーレイ） ================= */}
      {dialogueId && CHARACTERS[dialogueId] && (
        <DialogueWindow character={CHARACTERS[dialogueId]} onClose={closeDialogue} bridge={bridge} />
      )}

      {/* ===== 急変動中の赤ビネット ===== */}
      {shocked && (
        <div
          className="anim-vignette pointer-events-none absolute inset-0 z-30"
          style={{ boxShadow: 'inset 0 0 140px 30px rgba(224, 75, 75, 0.5)' }}
        />
      )}
    </div>
  )
}
