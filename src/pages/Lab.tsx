// ---------------------------------------------------------------
// 研究所のメイン画面。
//  - 1440×810 の固定ステージを画面にフィットさせ、
//    ホイールで拡大縮小・ドラッグで移動できる（40〜50代向けに大きなボタンも用意）
//  - キャラをクリックするとズームインして、その場に会話ウィンドウを開く
//  - 部屋は2つ。研究所（分析デスク・アルゴ管制室・情報センター）と、
//    右奥の扉の先にある SYSTEM LAB（ガンツの部屋）
//  - アルゴは管制室のモニターに映る数字（MT5 の実データ）を頭上の吹き出しで報告する
//  - 経済指標・要人発言などの AI 通知は研究員の頭上に随時ポップアップする
// ---------------------------------------------------------------
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { DialogueWindow } from '../components/DialogueWindow'
import {
  ConsoleDesk,
  ConsoleMonitors,
  DeskScreen,
  Door,
  InfoCenter,
  MiniRates,
  NoticesList,
  Overlay,
  ReportsList,
  Sparkline,
  SystemBoard,
  systemName,
  systemStateOf,
} from '../components/LabSets'
import { PixelPerson } from '../components/PixelPerson'
import { BigChart, Desk, ServerRack, ToolBox } from '../components/Panels'
import { YUI_GUIDE, YUI_HINTS, type Character } from '../data/characters'
import { useAuth } from '../hooks/AuthContext'
import { useAlgoReports } from '../hooks/useAlgoReports'
import { useEconomicAlerts } from '../hooks/useEconomicAlerts'
import { useBridge } from '../hooks/useBridge'
import { useSiteSettings } from '../hooks/SiteSettingsContext'
import { useMarket } from '../hooks/useMarket'
import { TICKER_SYMBOLS, formatMarketPrice, type Quote } from '../data/market'

const STAGE_W = 1440
const STAGE_H = 810
const HUD_H = 52
const FLOOR_TOP = 470 // ステージ内の壁と床の境目(px)
const MAX_ZOOM = 3
const BLEED = 700 // ステージの外に描き足す壁と床（画面の余りを埋める）

const ZONES = {
  analysis: { from: 0, to: 40, color: '#5eccff', en: 'ANALYSIS DESK', jp: '分析デスク' },
  control: { from: 40, to: 74, color: '#35f58a', en: 'ALGO CONTROL ROOM', jp: 'アルゴ管制室' },
  info: { from: 74, to: 100, color: '#ffb454', en: 'INFO CENTER', jp: '情報センター' },
} as const
const SYSTEM_ZONE = { from: 0, to: 100, color: '#ff9d4d', en: 'SYSTEM LAB', jp: 'システム研究室' } as const
const YELLOW = '#ffd23e'

/** キャラの立ち位置（ステージ%）。描画とズームインの両方で使う */
const CHAR_POS: Record<string, { x: number; bottom: number; s: number }> = {
  rin: { x: 12, bottom: 28, s: 5 },
  jin: { x: 30, bottom: 28, s: 5.4 },
  algo: { x: 63, bottom: 30, s: 5.4 },
  yui: { x: 50, bottom: 12, s: 5.6 },
  mio: { x: 85, bottom: 21, s: 5 },
}
/** SYSTEM LAB での立ち位置 */
const SYSTEM_POS: Record<string, { x: number; bottom: number; s: number }> = {
  gantz: { x: 50, bottom: 30, s: 5.4 },
}

const JIN_SHOCK_LINE = 'おや…？ 妙な動きだ。指標か、それとも──ちょっと金利を見てくる。'

/** AI通知のネタ帳。tone で吹き出しの色が変わる */
interface NewsItem {
  charId: string
  tone: 'alert' | 'warn' | 'info'
  label: string
  text: string
}
// 相場や指標の中身はここに書かない（ジンの予定はカレンダー API、リンの形はチャートから）
const NEWS_POOL: NewsItem[] = [
  { charId: 'rin', tone: 'info', label: '案内', text: '👀 大画面の銘柄について、直近の高値・安値や移動平均との位置関係をお話しできます。' },
  { charId: 'algo', tone: 'info', label: '稼働報告', text: '🤖 稼働状況は、管制室のモニターと右の情報センターでいつでも確認できます。' },
  { charId: 'mio', tone: 'info', label: '案内', text: '📋 取引履歴から、勝ち負けの幅・保有時間・時間帯のクセを読み取ります。' },
  { charId: 'yui', tone: 'info', label: '案内', text: '🔧 右奥の SYSTEM LAB では、新しいインジケーターのテストが進んでいます。' },
]

type BubbleTone = NewsItem['tone'] | 'good' | 'bad'
const TONE_STYLE: Record<BubbleTone, { border: string; glow: string; labelColor: string }> = {
  alert: { border: 'rgba(255,107,107,0.8)', glow: '0 0 18px rgba(224,75,75,0.3)', labelColor: '#ff6b6b' },
  warn: { border: 'rgba(255,210,62,0.8)', glow: '0 0 18px rgba(255,210,62,0.25)', labelColor: '#ffd23e' },
  info: { border: 'rgba(94,204,255,0.8)', glow: '0 0 18px rgba(94,204,255,0.25)', labelColor: '#5eccff' },
  good: { border: 'rgba(53,245,138,0.8)', glow: '0 0 18px rgba(53,245,138,0.25)', labelColor: '#35f58a' },
  bad: { border: 'rgba(255,132,132,0.8)', glow: '0 0 18px rgba(255,132,132,0.25)', labelColor: '#ff8484' },
}

interface Bubble {
  label: string
  text: string
  tone: BubbleTone
  /** 吹き出し自体をクリックしたときの動き（詳細を開くなど） */
  onClick?: () => void
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
  status,
  react = false,
}: {
  character: Character
  x: number
  bottom: number
  s: number
  onSelect: (id: string) => void
  z?: number
  dimmed?: boolean
  surprised?: boolean
  bubble?: Bubble | null
  exclaim?: boolean
  /** 名札の3行目。指定がなければキャラ既定の statusEn */
  status?: { text: string; color: string }
  /** データが更新された瞬間に小さく跳ねる */
  react?: boolean
}) {
  const tone = bubble ? TONE_STYLE[bubble.tone] : null
  const st = status ?? { text: character.statusEn, color: character.color }
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
      {/* AI通知・運用報告・イベント吹き出し */}
      {bubble && !dimmed && tone && (
        <div className="absolute bottom-full left-1/2 z-40 mb-3 w-64 -translate-x-1/2">
          <div
            className="rise-in"
            onClick={
              bubble.onClick
                ? (e) => {
                    e.stopPropagation()
                    bubble.onClick?.()
                  }
                : undefined
            }
            role={bubble.onClick ? 'button' : undefined}
          >
            <div
              className="rounded-[5px] border px-4 py-3 text-left backdrop-blur-[2px]"
              style={{ background: 'rgba(9,17,31,0.94)', borderColor: tone.border, boxShadow: tone.glow }}
            >
              <p className="font-mono mb-1 flex justify-between text-[10px] font-bold tracking-[0.3em]" style={{ color: tone.labelColor }}>
                <span>▎{bubble.label}</span>
                {bubble.onClick && <span className="tracking-[0.15em] text-slate-500">詳しく ▶</span>}
              </p>
              <p className="text-[14px] font-bold leading-relaxed text-slate-100">{bubble.text}</p>
            </div>
            <div
              className="mx-auto h-0 w-0 border-x-[8px] border-t-[8px] border-x-transparent"
              style={{ borderTopColor: tone.border }}
            />
          </div>
        </div>
      )}

      <div className={`relative flex flex-col items-center ${react ? 'hop' : ''}`}>
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
          <p className="font-mono flex items-center justify-center gap-1 whitespace-nowrap text-[9px] tracking-[0.2em]" style={{ color: st.color }}>
            <span className="soft-blink inline-block h-1.5 w-1.5 rounded-full" style={{ background: st.color, boxShadow: `0 0 5px ${st.color}` }} />
            {st.text}
          </p>
          {/* 「話せる」ことを示すマイクロコピー（机の陰に隠れないよう名札の中に） */}
          {!dimmed && <p className="font-mono text-[9px] tracking-[0.25em] text-slate-500">▶ CLICK</p>}
        </div>
        <PixelPerson look={character.look} s={s} surprised={surprised} />
      </div>
    </button>
  )
}

function Ticker({ quotes }: { quotes: Quote[] }) {
  const byId = new Map(quotes.map((q) => [q.symbol, q]))
  const items = TICKER_SYMBOLS.map((info) => ({ info, q: byId.get(info.symbol) })).filter((r) => r.q)
  const row = (key: string) => (
    <span key={key} className="flex shrink-0 items-center gap-7 pr-7">
      {items.map(({ info, q }) => {
        const up = q!.changePct >= 0
        const color = up ? '#2fbf62' : '#e04b4b'
        return (
          <span key={info.symbol} className="font-mono flex items-baseline gap-2 text-[13px] tracking-wide">
            <span className="text-slate-400">{info.label}</span>
            <span className="tabular-nums font-bold text-slate-100">{formatMarketPrice(q!.price, info)}</span>
            <span className="tabular-nums text-[12px]" style={{ color }}>
              {up ? '▲' : '▼'} {Math.abs(q!.changePct).toFixed(2)}%
            </span>
          </span>
        )
      })}
    </span>
  )
  return (
    <div className="relative mx-4 h-full min-w-0 flex-1 overflow-hidden">
      {items.length > 0 && (
        <div className="anim-marquee flex h-full w-max items-center">
          {row('a')}
          {row('b')}
        </div>
      )}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-10 bg-gradient-to-r from-[#080e1a] to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-[#080e1a] to-transparent" />
    </div>
  )
}

function ZoneHeader({ zone, extra }: { zone: { from: number; to: number; color: string; en: string; jp: string }; extra?: React.ReactNode }) {
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

/** HUD の小さなボタン（通知・案内・部屋の移動） */
function HudButton({
  onClick,
  children,
  color = 'var(--panel-border)',
  badge = 0,
  title,
}: {
  onClick: () => void
  children: React.ReactNode
  color?: string
  badge?: number
  title?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="relative flex h-11 items-center whitespace-nowrap rounded-[4px] border px-3 text-[13px] font-bold text-slate-100 transition hover:brightness-125 active:translate-y-px"
      style={{ borderColor: color, background: 'rgba(8,14,26,0.8)' }}
    >
      {children}
      {badge > 0 && (
        <span
          className="font-mono absolute -right-1.5 -top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-[11px] font-bold text-[#1c1607]"
          style={{ background: YELLOW, boxShadow: `0 0 8px ${YELLOW}` }}
        >
          {badge > 9 ? '9+' : badge}
        </span>
      )}
    </button>
  )
}

type OverlayKind = 'chart' | 'reports' | 'notices'
type Room = 'main' | 'system'

export function Lab() {
  const { member, logout } = useAuth()
  const { characters: CHARACTERS, t } = useSiteSettings()
  const tutorialKey = member ? `lab-tutorial-done:${member.id}` : 'lab-tutorial-done'
  const guideKey = member ? `lab-guide-done:${member.id}` : 'lab-guide-done'
  // チュートリアルは会員ごとに初回だけ
  const [tutorial, setTutorial] = useState(() => !localStorage.getItem(tutorialKey))
  const market = useMarket()
  const { shocked, triggerShock } = market
  const bridge = useBridge(member?.id)
  const [news, setNews] = useState<NewsItem | null>(null)
  const [dialogueId, setDialogueId] = useState<string | null>(null)

  // ───── 見せ方だけの状態（部屋・オーバーレイ・案内） ─────
  const [room, setRoom] = useState<Room>('main')
  const [overlay, setOverlay] = useState<OverlayKind | null>(null)
  /** ユイの案内。-1 = 出していない */
  const [guideStep, setGuideStep] = useState(() => (localStorage.getItem(guideKey) ? -1 : 0))
  const [yuiHint, setYuiHint] = useState<string | null>(null)
  const [seenReports, setSeenReports] = useState(0)
  const [reacting, setReacting] = useState(false)

  const state = systemStateOf(bridge, shocked)
  const running = state.key === 'running'
  const algoReports = useAlgoReports(bridge, !!dialogueId || tutorial || room === 'system' || overlay !== null)
  const econ = useEconomicAlerts(!!dialogueId || tutorial || room === 'system' || overlay !== null)

  // ───── パン・ズーム ─────
  //  - ズームの下限は「画面にぴったり収まる倍率」（zoom = 1）。それより縮めない
  //  - 収まりきらない向きにだけ動かせる。ステージの外が見えるところまでは動かせない
  //  - 画面の縦横比が 16:9 でないときの余りは、壁と床の続き（BLEED）で埋める
  const viewRef = useRef<HTMLDivElement>(null)
  const viewSize = useRef({ w: 1, h: 1 })
  const [base, setBase] = useState(0.5)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [animate, setAnimate] = useState(false)
  const baseRef = useRef(base)
  const zoomRef = useRef(zoom)
  const panRef = useRef(pan)
  baseRef.current = base
  zoomRef.current = zoom
  panRef.current = pan
  const dragState = useRef<{ sx: number; sy: number; px: number; py: number; moved: boolean } | null>(null)
  const suppressClick = useRef(false)

  /** これより縮めない。base がフィット倍率なので 1 = 画面にぴったり */
  const minZoom = useCallback(() => 1, [])

  /** ズームと位置を許される範囲に収めて反映する */
  const applyView = useCallback(
    (nextZoom: number, nextPan: { x: number; y: number }, withAnim: boolean) => {
      const { w, h } = viewSize.current
      const z = Math.min(MAX_ZOOM, Math.max(minZoom(), nextZoom))
      const scale = baseRef.current * z
      const maxX = Math.max(0, (STAGE_W * scale - w) / 2)
      const maxY = Math.max(0, (STAGE_H * scale - h) / 2)
      setAnimate(withAnim)
      setZoom(z)
      setPan({ x: Math.min(maxX, Math.max(-maxX, nextPan.x)), y: Math.min(maxY, Math.max(-maxY, nextPan.y)) })
    },
    [minZoom],
  )

  useEffect(() => {
    const fit = () => {
      const w = window.innerWidth
      const h = window.innerHeight - HUD_H
      viewSize.current = { w, h }
      const b = Math.min(w / STAGE_W, h / STAGE_H)
      baseRef.current = b
      setBase(b)
      applyView(zoomRef.current, panRef.current, false)
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [applyView])

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
      const z1 = Math.min(MAX_ZOOM, Math.max(minZoom(), z0 * Math.exp(-e.deltaY * 0.0014)))
      const k = z1 / z0
      applyView(z1, { x: panRef.current.x - cx * (k - 1), y: panRef.current.y - cy * (k - 1) }, false)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [applyView, minZoom])

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
    if (d.moved) applyView(zoomRef.current, { x: d.px + dx, y: d.py + dy }, false)
  }
  const onPointerUp = () => {
    if (dragState.current?.moved) {
      suppressClick.current = true
      setTimeout(() => (suppressClick.current = false), 0)
    }
    dragState.current = null
  }

  const resetView = useCallback(() => {
    applyView(minZoom(), { x: 0, y: 0 }, true)
  }, [applyView, minZoom])
  const zoomBy = useCallback(
    (k: number) => {
      // 画面の中心を保ったまま倍率だけ変える
      const z0 = zoomRef.current
      const z1 = Math.min(MAX_ZOOM, Math.max(minZoom(), z0 * k))
      const r = z1 / z0
      applyView(z1, { x: panRef.current.x * r, y: panRef.current.y * r }, true)
    },
    [applyView, minZoom],
  )

  /** キャラが会話ウィンドウの上（画面のやや上寄り）に来るようにカメラを寄せる */
  const focusOn = useCallback(
    (id: string): boolean => {
      const pos = (room === 'system' ? SYSTEM_POS : CHAR_POS)[id]
      if (!pos) return false
      const targetZoom = Math.max(1.7, minZoom() * 1.5)
      const vh = viewSize.current.h
      const cx = (pos.x / 100) * STAGE_W - STAGE_W / 2
      const footY = STAGE_H * (1 - pos.bottom / 100)
      const cy = footY - 70 - STAGE_H / 2
      applyView(targetZoom, { x: -cx * base * targetZoom, y: -cy * base * targetZoom - vh * 0.18 }, true)
      return true
    },
    [base, applyView, minZoom, room],
  )

  /** キャラへズームインして、その場に会話ウィンドウを開く（画面遷移しない） */
  const select = useCallback(
    (id: string) => {
      if (suppressClick.current) return
      if (tutorial && id !== 'yui') return
      if (!focusOn(id)) return
      setDialogueId(id)
      if (tutorial) {
        setTutorial(false)
        localStorage.setItem(tutorialKey, '1')
      }
    },
    [tutorial, tutorialKey, focusOn],
  )

  /** メンバー紹介中、ユイが話している研究員へカメラを向ける。null で話し相手に戻す */
  const focusFor = useCallback(
    (id: string | null) => {
      focusOn(id ?? dialogueId ?? 'yui')
    },
    [focusOn, dialogueId],
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
  const econNextRef = useRef(econ.nextLine)
  econNextRef.current = econ.nextLine
  useEffect(() => {
    if (tutorial) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    let clearTimer: ReturnType<typeof setTimeout>
    let idx = 0
    const schedule = (delay: number) => {
      timer = setTimeout(() => {
        if (!alive) return
        // ジンは本物のカレンダーから「次の指標」を挟む
        const pool: NewsItem[] = econNextRef.current
          ? [...NEWS_POOL, { charId: 'jin', tone: 'warn', label: '指標', text: `📅 ${econNextRef.current}` }]
          : NEWS_POOL
        const item = pool[idx % pool.length]
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

  // オーバーレイは Esc でも閉じる（会話ウィンドウの Esc とは別に持つ）
  useEffect(() => {
    if (!overlay) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOverlay(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [overlay])

  // ユイのひとこと案内（6秒で消える）
  const hintTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sayHint = useCallback(
    (text: string) => {
      setYuiHint(t(text))
      if (hintTimer.current) clearTimeout(hintTimer.current)
      hintTimer.current = setTimeout(() => setYuiHint(null), 6000)
    },
    [t],
  )
  useEffect(
    () => () => {
      if (hintTimer.current) clearTimeout(hintTimer.current)
    },
    [],
  )

  const openOverlay = useCallback(
    (kind: OverlayKind) => {
      setOverlay(kind)
      if (kind === 'reports') {
        setSeenReports(algoReports.reports.length)
        sayHint(YUI_HINTS.reportsOpened)
      }
      if (kind === 'chart') sayHint(YUI_HINTS.chartOpened)
    },
    [algoReports.reports.length, sayHint],
  )

  /** 部屋を移る。会話は閉じ、全体表示に戻す */
  const goRoom = useCallback(
    (next: Room) => {
      if (next === room) return
      setDialogueId(null)
      setOverlay(null)
      setRoom(next)
      resetView()
      if (next === 'main') sayHint(YUI_HINTS.backFromLab)
    },
    [room, resetView, sayHint],
  )

  const finishGuide = useCallback(() => {
    setGuideStep(-1)
    localStorage.setItem(guideKey, '1')
  }, [guideKey])
  const restartGuide = useCallback(() => {
    setOverlay(null)
    setDialogueId(null)
    if (room !== 'main') goRoom('main')
    setGuideStep(0)
  }, [room, goRoom])

  // 決済数やポジション数が変わった瞬間、アルゴが小さく跳ねる
  const reactKey = `${bridge.status?.today?.today_closed ?? ''}|${bridge.status?.positions?.length ?? bridge.status?.today?.open_positions ?? ''}`
  const prevReactKey = useRef(reactKey)
  useEffect(() => {
    if (prevReactKey.current === reactKey) return
    prevReactKey.current = reactKey
    if (!bridge.live) return
    setReacting(true)
    const timer = setTimeout(() => setReacting(false), 600)
    return () => clearTimeout(timer)
  }, [reactKey, bridge.live])

  const unread = Math.max(0, algoReports.reports.length - seenReports)
  const showGuide = guideStep >= 0 && !tutorial && !dialogueId && room === 'main' && !overlay
  const guideLine = showGuide ? t(YUI_GUIDE[Math.min(guideStep, YUI_GUIDE.length - 1)]) : null
  const guideLast = guideStep >= YUI_GUIDE.length - 1
  /** 案内の各ステップで光らせる場所 */
  const guideRing: Array<{ left: string; bottom: string } | null> = [
    null,
    { left: '20%', bottom: '66%' },
    { left: `${CHAR_POS.algo.x}%`, bottom: `${CHAR_POS.algo.bottom}%` },
    { left: '86%', bottom: '38%' },
    null,
  ]
  const ring = showGuide ? guideRing[guideStep] ?? null : null

  const bubbleFor = (id: string): Bubble | null => {
    if (dialogueId) return null
    if (shocked && id === 'jin') return { label: '急変動', text: JIN_SHOCK_LINE, tone: 'alert' }
    if (id === 'jin' && econ.current) return { label: '指標', text: econ.current.text, tone: econ.current.tone, onClick: econ.dismiss }
    if (id === 'algo' && algoReports.current && !shocked) {
      const r = algoReports.current
      return {
        label: r.kind === 'trade' ? '決済' : r.kind === 'system' ? 'システム' : '運用報告',
        text: r.text,
        tone: r.tone,
        onClick: () => openOverlay('reports'),
      }
    }
    if (id === 'yui' && yuiHint && !showGuide) return { label: '案内', text: yuiHint, tone: 'info' }
    if (!shocked && news && news.charId === id) return { label: news.label, text: news.text, tone: news.tone }
    return null
  }

  const dimStyle = (o: number) => ({ opacity: tutorial ? o : 1 })
  const scale = base * zoom
  const wallProps = {
    candles: market.candles,
    symbol: market.symbol,
    onSymbol: market.setSymbol,
    interval: market.interval,
    price: market.price,
    prevClose: market.prevClose,
    dir: market.dir,
    ready: market.ready,
    shocked,
  }
  const controlColor = shocked ? '#e04b4b' : ZONES.control.color

  return (
    <div className="relative h-screen w-full overflow-hidden" style={{ background: '#070b14' }}>
      {/* ================= HUD ================= */}
      <header
        className="absolute inset-x-0 top-0 z-40 flex items-center border-b px-5"
        style={{ height: HUD_H, background: 'rgba(8,14,26,0.95)', borderColor: 'var(--panel-border)' }}
      >
        <span className="h-4 w-[3px]" style={{ background: 'var(--accent)', boxShadow: '0 0 8px var(--accent)' }} />
        <h1 className="font-mono ml-3 whitespace-nowrap text-[14px] font-bold tracking-[0.3em] text-slate-100">
          MARKET RESEARCH LAB
        </h1>
        <span className="ml-3 hidden whitespace-nowrap text-[13px] font-bold text-slate-400 md:inline">トレード研究所</span>
        <Ticker quotes={market.quotes} />
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
          <HudButton onClick={restartGuide} title="研究所の案内をもう一度見る">
            ？ 案内
          </HudButton>
          {room === 'main' ? (
            <HudButton onClick={() => goRoom('system')} color={`${SYSTEM_ZONE.color}88`} title="SYSTEM LAB（システム設定・拡張機能）へ">
              SYSTEM LAB ▶
            </HudButton>
          ) : (
            <HudButton onClick={() => goRoom('main')} color="var(--panel-border)" title="研究所へ戻る">
              ◀ 研究所
            </HudButton>
          )}
          <span className="hidden max-w-[12rem] truncate text-[13px] text-slate-400 xl:inline">{member?.email}</span>
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
          {/* ===== 画面の余りを埋める壁と床の続き ===== */}
          <div
            className="pointer-events-none absolute"
            style={{ left: -BLEED, right: -BLEED, top: -BLEED, height: FLOOR_TOP + BLEED, background: 'linear-gradient(#070d18, #0a1322 70%, #0e1930)' }}
          />
          <div
            className="pointer-events-none absolute"
            style={{
              left: -BLEED,
              right: -BLEED,
              top: FLOOR_TOP,
              bottom: -BLEED,
              background: 'linear-gradient(#33405f, #1e2842 30%, #141b30 60%, #0b1020)',
              backgroundImage:
                'linear-gradient(rgba(255,255,255,0.07), transparent 8%), repeating-linear-gradient(0deg, rgba(0,0,0,0.14) 0 2px, transparent 2px 56px)',
            }}
          />
          <div className="pointer-events-none absolute h-[3px]" style={{ left: -BLEED, right: -BLEED, top: FLOOR_TOP - 3, background: '#05080f' }} />
          <div className="pointer-events-none absolute h-px" style={{ left: -BLEED, right: -BLEED, top: FLOOR_TOP, background: 'rgba(255,255,255,0.18)' }} />
          <div
            className="pointer-events-none absolute"
            style={{
              left: -BLEED,
              right: -BLEED,
              top: -BLEED,
              bottom: -BLEED,
              background: 'radial-gradient(ellipse 45% 45% at 50% 40%, transparent 60%, rgba(3,6,13,0.85) 100%)',
            }}
          />

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

          {room === 'main' ? (
            <>
              {/* ===== 中央ベイ＝アルゴ管制室（壁の色を変えて、部屋として際立たせる） ===== */}
              <div
                className="absolute"
                style={{
                  left: `${ZONES.control.from}%`,
                  width: `${ZONES.control.to - ZONES.control.from}%`,
                  top: 0,
                  height: FLOOR_TOP,
                  background: shocked
                    ? 'linear-gradient(rgba(224,75,75,0.1), rgba(224,75,75,0.03))'
                    : 'linear-gradient(rgba(53,245,138,0.08), rgba(53,245,138,0.02) 70%, rgba(53,245,138,0.05))',
                  boxShadow: shocked ? 'inset 0 0 80px rgba(224,75,75,0.18)' : 'inset 0 0 80px rgba(53,245,138,0.08)',
                  ...dimStyle(0.5),
                }}
              >
                {/* 壁面パネルの継ぎ目 */}
                <div
                  className="absolute inset-0"
                  style={{
                    backgroundImage:
                      'repeating-linear-gradient(0deg, transparent 0 78px, rgba(53,245,138,0.06) 78px 79px)',
                  }}
                />
                {/* 奥のサーバーラック（稼働中だけランプが点く） */}
                <div className="absolute inset-x-[12%] bottom-0 flex items-end justify-between">
                  {[0, 1, 2, 3].map((i) => (
                    <ServerRack key={i} shocked={shocked} tall={i % 2 === 1} active={running || shocked} />
                  ))}
                </div>
                {shocked && <div className="anim-alarm pointer-events-none absolute inset-0 opacity-25" />}
              </div>
              {/* 管制室の床（一段暗い床材＋縁のライン） */}
              <div
                className="pointer-events-none absolute"
                style={{
                  left: `${ZONES.control.from}%`,
                  width: `${ZONES.control.to - ZONES.control.from}%`,
                  top: FLOOR_TOP,
                  bottom: 0,
                  background: shocked ? 'rgba(224,75,75,0.05)' : 'rgba(53,245,138,0.045)',
                  boxShadow: `inset 3px 0 0 ${controlColor}33, inset -3px 0 0 ${controlColor}33`,
                  ...dimStyle(0.5),
                }}
              />

              {/* ベイの区切り */}
              {[ZONES.control.from, ZONES.control.to].map((l) => (
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
                const color = k === 'control' ? controlColor : z.color
                return (
                  <div
                    key={k}
                    className="absolute h-[3px]"
                    style={{
                      left: `calc(${z.from}% + 8px)`,
                      width: `calc(${z.to - z.from}% - 16px)`,
                      top: FLOOR_TOP + 1,
                      background: color,
                      opacity: k === 'control' && !running && !shocked ? 0.3 : 0.6,
                      boxShadow: `0 0 14px ${color}`,
                    }}
                  />
                )
              })}

              {/* ゾーン見出し */}
              <div style={dimStyle(0.5)}>
                <ZoneHeader zone={ZONES.analysis} />
                <ZoneHeader zone={{ ...ZONES.control, color: controlColor }} />
                <ZoneHeader zone={ZONES.info} />
              </div>

              {/* ===== 分析デスクの壁：リンのチャート（クリックで大きく） ===== */}
              <BigChart
                {...wallProps}
                compact
                onOpen={() => openOverlay('chart')}
                style={{ left: '3%', top: 56, width: '34%', height: 290, ...dimStyle(0.45) }}
              />

              {/* ===== 管制室の壁：稼働状況と成績のモニター ===== */}
              <ConsoleMonitors
                bridge={bridge}
                state={state}
                reacting={reacting}
                style={{ left: '42%', width: '30%', top: 48, ...dimStyle(0.45) }}
              />

              {/* ===== 情報センター（カード）と SYSTEM LAB への扉 ===== */}
              <InfoCenter
                bridge={bridge}
                state={state}
                reports={algoReports.reports}
                events={econ.events}
                eventsFailed={econ.loadFailed}
                unread={unread}
                onOpen={openOverlay}
                style={{ left: '76%', top: 56, width: '17.5%', ...dimStyle(0.45) }}
              />
              <Door
                label="SYSTEM LAB"
                sub={`${CHARACTERS.gantz.name}の部屋`}
                color={SYSTEM_ZONE.color}
                onClick={() => goRoom('system')}
                style={{ left: '94.4%', top: 262, ...dimStyle(0.45) }}
              />

              {/* ===== 床の照明溜まり ===== */}
              {[
                { left: '20%', color: 'rgba(94,204,255,0.08)' },
                { left: '63%', color: shocked ? 'rgba(224,75,75,0.1)' : running ? 'rgba(53,245,138,0.1)' : 'rgba(53,245,138,0.04)' },
                { left: '86%', color: 'rgba(255,180,84,0.07)' },
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

              {/* ===== 分析デスク：リンとジン ===== */}
              <Chara character={CHARACTERS.rin} {...CHAR_POS.rin} onSelect={select} dimmed={tutorial} bubble={bubbleFor('rin')} />
              <Chara
                character={CHARACTERS.jin}
                {...CHAR_POS.jin}
                onSelect={select}
                dimmed={tutorial}
                surprised={shocked}
                bubble={bubbleFor('jin')}
              />
              <Desk style={{ left: '4%', bottom: '17%', width: '34%', zIndex: 12, ...dimStyle(0.5) }}>
                <div className="flex w-full items-end justify-between px-8">
                  <DeskScreen label="CHART" color={CHARACTERS.rin.color}>
                    <Sparkline candles={market.candles} color={market.dir < 0 ? '#ff8484' : CHARACTERS.rin.color} />
                  </DeskScreen>
                  <DeskScreen label="RATES" color={CHARACTERS.jin.color}>
                    <MiniRates quotes={market.quotes} />
                  </DeskScreen>
                </div>
              </Desk>

              {/* ===== 管制室：アルゴと司令席 ===== */}
              {/* アルゴを照らすスポットライトと足元のリング */}
              <div
                className="pointer-events-none absolute -translate-x-1/2"
                style={{
                  left: `${CHAR_POS.algo.x}%`,
                  top: 0,
                  width: 300,
                  height: STAGE_H * (1 - CHAR_POS.algo.bottom / 100) + 8,
                  clipPath: 'polygon(44% 0, 56% 0, 100% 100%, 0 100%)',
                  background: shocked
                    ? 'linear-gradient(rgba(224,75,75,0.02), rgba(224,75,75,0.16))'
                    : `linear-gradient(rgba(53,245,138,0.02), rgba(53,245,138,${running ? 0.13 : 0.06}))`,
                  ...dimStyle(0.5),
                }}
              />
              <div
                className="pointer-events-none absolute -translate-x-1/2 rounded-full border"
                style={{
                  left: `${CHAR_POS.algo.x}%`,
                  bottom: `calc(${CHAR_POS.algo.bottom}% - 12px)`,
                  width: 150,
                  height: 34,
                  borderColor: shocked ? 'rgba(255,132,132,0.7)' : `rgba(53,245,138,${running ? 0.7 : 0.35})`,
                  background: shocked
                    ? 'radial-gradient(ellipse at center, rgba(224,75,75,0.35), rgba(224,75,75,0.05) 70%)'
                    : 'radial-gradient(ellipse at center, rgba(53,245,138,0.35), rgba(53,245,138,0.05) 70%)',
                  boxShadow: shocked ? '0 0 24px rgba(224,75,75,0.5)' : '0 0 24px rgba(53,245,138,0.45)',
                  zIndex: 14,
                  ...dimStyle(0.5),
                }}
              />
              <Chara
                character={CHARACTERS.algo}
                {...CHAR_POS.algo}
                z={15}
                onSelect={select}
                dimmed={tutorial}
                bubble={bubbleFor('algo')}
                status={{ text: state.en, color: state.color }}
                react={reacting}
              />
              <ConsoleDesk state={state} style={{ left: '52.5%', width: '21%', bottom: '17%', zIndex: 16, ...dimStyle(0.5) }} />

              {/* ===== 情報センター：ミオ ===== */}
              <Chara character={CHARACTERS.mio} {...CHAR_POS.mio} onSelect={select} dimmed={tutorial} bubble={bubbleFor('mio')} />

              {/* ===== エントランス ===== */}
              <Chara character={CHARACTERS.yui} {...CHAR_POS.yui} z={35} onSelect={select} exclaim bubble={bubbleFor('yui')} />
              <div className="absolute z-[36] -translate-x-1/2" style={{ left: '50%', bottom: '3%', width: 380 }}>
                <div className="h-3.5 rounded-t-[4px] border border-b-0 border-[#2a1608] bg-[#8a5a2b]" />
                <div className="rounded-b-[4px] border border-t-0 border-[#2a1608] bg-[#6e4520] px-4 py-2.5 text-center">
                  <p className="font-mono text-[14px] font-bold tracking-[0.35em] text-amber-100">RECEPTION</p>
                </div>
              </div>

              {/* ===== ユイの案内（初回だけ。HUD の「案内」でいつでも） ===== */}
              {showGuide && guideLine && (
                <>
                  {ring && (
                    <div
                      className="tutorial-ring pointer-events-none absolute z-30 h-44 w-44 -translate-x-1/2 rounded-full border-2 border-yellow-300/80"
                      style={{ left: ring.left, bottom: `calc(${ring.bottom} - 20px)` }}
                    />
                  )}
                  <div className="absolute z-50 w-[25rem] -translate-x-1/2" style={{ left: '50%', bottom: '40%' }}>
                    <div
                      key={guideStep}
                      className="rise-in rounded-[5px] border px-6 py-4 text-left backdrop-blur-[2px]"
                      style={{ background: 'rgba(9,17,31,0.95)', borderColor: 'rgba(253,224,71,0.85)', boxShadow: '0 0 24px rgba(253,224,71,0.2)' }}
                    >
                      <p className="font-mono mb-1.5 flex justify-between text-[11px] tracking-[0.35em] text-yellow-300">
                        <span>▎GUIDE ／ {CHARACTERS.yui.name}</span>
                        <span className="text-slate-500">
                          {guideStep + 1} / {YUI_GUIDE.length}
                        </span>
                      </p>
                      <p className="text-[16px] font-bold leading-relaxed text-white">{guideLine}</p>
                      <div className="mt-3 flex justify-end gap-2">
                        {!guideLast && (
                          <button
                            type="button"
                            onClick={finishGuide}
                            className="h-11 rounded-[4px] border px-4 text-[14px] font-bold text-slate-300"
                            style={{ borderColor: 'rgba(148,163,184,0.4)' }}
                          >
                            閉じる
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => (guideLast ? finishGuide() : setGuideStep((n) => n + 1))}
                          className="h-11 rounded-[4px] border px-5 text-[15px] font-bold text-[#1c1607]"
                          style={{ background: 'rgba(253,224,71,0.92)', borderColor: '#a16207', boxShadow: '0 0 12px rgba(253,224,71,0.25)' }}
                        >
                          {guideLast ? 'わかりました' : '次へ ▶'}
                        </button>
                      </div>
                    </div>
                    <div className="mx-auto h-0 w-0 border-x-[9px] border-t-[9px] border-x-transparent border-t-yellow-300/85" />
                  </div>
                </>
              )}
            </>
          ) : (
            <>
              {/* ===== SYSTEM LAB：ガンツの部屋 ===== */}
              <div
                className="absolute inset-x-0 top-0"
                style={{
                  height: FLOOR_TOP,
                  background: 'linear-gradient(rgba(255,157,77,0.07), rgba(255,157,77,0.02) 60%, rgba(255,157,77,0.04))',
                  boxShadow: 'inset 0 0 80px rgba(255,157,77,0.08)',
                  backgroundImage:
                    'repeating-linear-gradient(115deg, transparent 0 90px, rgba(255,255,255,0.015) 90px 130px), repeating-linear-gradient(0deg, transparent 0 78px, rgba(255,157,77,0.06) 78px 79px)',
                }}
              >
                {/* ガンツの背後に並ぶラック（本体のサーバー群） */}
                <div className="absolute bottom-0 left-[34%] flex w-[32%] items-end justify-between">
                  {[0, 1, 2, 3, 4, 5].map((i) => (
                    <ServerRack key={i} shocked={shocked} tall={i % 2 === 1} active={running || shocked} />
                  ))}
                </div>
              </div>
              <div
                className="absolute h-[3px]"
                style={{ left: 8, right: 8, top: FLOOR_TOP + 1, background: SYSTEM_ZONE.color, opacity: 0.6, boxShadow: `0 0 14px ${SYSTEM_ZONE.color}` }}
              />
              <ZoneHeader zone={SYSTEM_ZONE} />
              <SystemBoard bridge={bridge} state={state} part="system" color={SYSTEM_ZONE.color} style={{ left: '8%', top: 68, width: '24%' }} />
              <SystemBoard bridge={bridge} state={state} part="extensions" color={SYSTEM_ZONE.color} style={{ left: '68%', top: 68, width: '26%' }} />
              <Door
                label="研究所"
                sub="もどる"
                color="var(--accent)"
                arrow="left"
                onClick={() => goRoom('main')}
                style={{ left: '1.4%', top: 262 }}
              />
              <div
                className="pointer-events-none absolute -translate-x-1/2"
                style={{
                  left: '50%',
                  top: FLOOR_TOP,
                  width: '30%',
                  height: '22%',
                  background: 'radial-gradient(ellipse 55% 60% at 50% 30%, rgba(255,157,77,0.1), transparent 70%)',
                }}
              />
              <Chara character={CHARACTERS.gantz} {...SYSTEM_POS.gantz} onSelect={select} bubble={bubbleFor('gantz')} />
              <Desk style={{ left: '38%', bottom: '17%', width: '24%', zIndex: 12 }}>
                <div className="flex w-full items-end justify-between px-8">
                  <ToolBox />
                  <DeskScreen label="BUILD" color={CHARACTERS.gantz.color}>
                    <p className="font-mono flex h-full flex-col justify-center text-[9px] leading-tight text-slate-300">
                      <span className="truncate">{(bridge.live && systemName(bridge.status)) || 'SYSTEM'}</span>
                      <span className="text-slate-500">{bridge.live && bridge.status?.build ? `MT5 build ${bridge.status.build}` : state.jp}</span>
                    </p>
                  </DeskScreen>
                </div>
              </Desk>
            </>
          )}

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
                    まずは受付の<span className="text-yellow-300">{CHARACTERS.yui.name}</span>をクリックして
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
            {room === 'main'
              ? '研究員をクリックすると相談できます ── 表示レートは配信の都合により実際と異なる場合があります'
              : `${CHARACTERS.gantz.name}をクリックすると、ロットや同時保有数などの設定を変更できます`}
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

      {/* ================= オーバーレイ（チャート拡大・通知・お知らせ・相場） ================= */}
      {overlay === 'chart' && (
        <Overlay title="チャート分析" sub={`${CHARACTERS.rin.name} ─ チャート分析`} onClose={() => setOverlay(null)}>
          <div className="p-4">
            <BigChart {...wallProps} style={{ position: 'relative', width: '100%', height: 'min(62vh, 560px)' }} />
          </div>
        </Overlay>
      )}
      {overlay === 'reports' && (
        <Overlay title="運用報告" sub={`${CHARACTERS.algo.name} ─ 自動売買`} onClose={() => setOverlay(null)} width="min(92vw, 760px)">
          <ReportsList reports={algoReports.reports} name={CHARACTERS.algo.name} />
        </Overlay>
      )}
      {overlay === 'notices' && (
        <Overlay title="お知らせ" sub="NOTICE ／ UPDATE ／ ROADMAP" onClose={() => setOverlay(null)} width="min(92vw, 760px)">
          <NoticesList />
        </Overlay>
      )}
      {/* ================= 会話ウィンドウ（オーバーレイ） ================= */}
      {dialogueId && CHARACTERS[dialogueId] && (
        <DialogueWindow character={CHARACTERS[dialogueId]} onClose={closeDialogue} bridge={bridge} market={market} econ={econ} onSelect={select} onFocus={focusFor} />
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
