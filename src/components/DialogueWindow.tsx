// ノベルゲーム風の会話ウィンドウ（SPEC R-08-11 / R-08-12 / R-08-13 準拠）。
// 画面遷移せず、研究所の画面の上にオーバーレイで開く。
//
// 「初期設定（MT5との連携）」モードを併せ持つ。担当は受付のユイ。
// 売りたいのは “設定はAIが代わりに全部やる” という体験なので、
// お客様にしていただくのは、接続ツールをダウンロードして一度開くことだけ。
// 残りはユイが手順を案内し、つながったら管制室のアルゴに引き継ぐ。
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AI_TEXT, ECON_ALERT, SETUP, TOUR, type Character } from '../data/characters'
import { useSiteSettings } from '../hooks/SiteSettingsContext'
import { clearConnection, loadConnection, newConnection, saveConnection, applyBridgeToConnection, connectionMatchesBridge, connectionAccountKey, type Connection } from '../data/connection'
import { settingsFromGate } from '../data/eaSettings'
import { BridgeStatusBar } from './BridgeStatusBar'
import { ControlPanel } from './ControlPanel'
import type { useBridge } from '../hooks/useBridge'
import { useAuth } from '../hooks/AuthContext'
import { formatBridgeError } from '../data/bridgeErrors'
import {
  CONNECT_WAIT,
  installSteps,
  MT5_STEPS,
  mt5StepIndex,
  connectChecksFromStatus,
  formatHistoryAnswer,
  formatPositionsAnswer,
  formatTodayAnswer,
  type ConnectCheck,
  type UserStep,
} from '../data/setupFlow'
import { LiveReportView, type LiveReport } from './LiveReport'
import { SetupFigure } from './SetupFigures'
import { CONNECTOR_DOWNLOAD, CONNECTOR_WAIT_MS, DEFAULT_ROOM, DEFAULT_ROOM_FRESH_MS, DEFAULT_ROOM_POLL_MS, downloadConnector, launchConnector, probeRoom } from '../data/connector'
import { formatReviewAnswer, reviewTrades, type TradeHistory } from '../data/tradeReview'
import { PixelPerson } from './PixelPerson'
import { AI_FAILURE_TEXT, askAi, setPendingQuestion, takePendingQuestion, type AiRole } from '../data/ai'
import { algoContext, jinContext, mioContext, rinContext } from '../data/aiContext'
import type { useMarket } from '../hooks/useMarket'
import type { useEconomicAlerts } from '../hooks/useEconomicAlerts'
import { eventLabel, formatEventDate, formatEventTime, upcoming, type EconomicEvent } from '../data/calendar'

type Phase = 'talk' | 'intro' | 'tour' | 'launching' | 'download' | 'waiting' | 'connecting' | 'mt5' | 'done' | 'control'

/** ダウンロード後の手順（exe か zip かで変わる） */
const INSTALL_STEPS = installSteps(CONNECTOR_DOWNLOAD.kind)

/** この選択肢は、答えを作らずに MT5 から取ってきた数字をそのまま出す */
const LIVE_QUESTIONS: Record<string, LiveReport['kind']> = {
  '今日の成績は？': 'today',
  '過去の成績は？': 'history',
  'いまのポジションは？': 'positions',
  'トレードを添削して': 'review',
  'トレードのクセを教えて': 'review',
}

/** 過去の成績はこの日数ぶんを口座履歴から集計する */
const HISTORY_DAYS = 30

/** 添削はもう少し長く見る */
const REVIEW_DAYS = 180

/** AI に渡す取引履歴はこの日数ぶん（アルゴ・ミオ）。1分は取り直さない */
const AI_TRADE_DAYS = 30
const AI_TRADE_KEEP_MS = 60_000

function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? ''))
}

/** 呼び出し中に見せる、接続ツールの仕事 */
const CONNECTOR_STEPS = [
  'ログイン中のMT5を探しています',
  'システムをMT5に入れて、使える形にしています',
  '中継サーバーとつないでいます',
  '次回からPCを立ち上げるだけでつながるようにしています',
]

export function DialogueWindow({
  character,
  onClose,
  bridge,
  market,
  econ,
  onSelect,
  onFocus,
}: {
  character: Character
  onClose: () => void
  bridge: ReturnType<typeof useBridge>
  /** 大画面のチャート（リンが読む） */
  market: ReturnType<typeof useMarket>
  /** 経済指標カレンダーと通知（ジンが読む） */
  econ: ReturnType<typeof useEconomicAlerts>
  /** 別の研究員へ引き継ぐ（その研究員の会話を開く） */
  onSelect?: (id: string) => void
  /** メンバー紹介中、カメラをその研究員に向ける。null で受付に戻す */
  onFocus?: (id: string | null) => void
}) {
  const { member } = useAuth()
  const { characters, t } = useSiteSettings()
  // はじめての方には、ユイが最初にメンバー紹介から入る（会員ごとに一度だけ）
  const introKey = member ? `lab-intro-done:${member.id}` : 'lab-intro-done'
  const [aiText, setAiText] = useState(character.greeting)
  const [shown, setShown] = useState(0)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)

  // ── おまかせ接続 ──
  const [phase, setPhase] = useState<Phase>('talk')
  const [stepIndex, setStepIndex] = useState(0)
  const [checks, setChecks] = useState<ConnectCheck[]>([])
  const [error, setError] = useState<string | null>(null)
  const [conn, setConn] = useState<Connection | null>(() => loadConnection())
  const [report, setReport] = useState<LiveReport | null>(null)
  const [reportAt, setReportAt] = useState<Date | null>(null)
  /** メンバー紹介で、いま誰を紹介しているか */
  const [tourIndex, setTourIndex] = useState(0)
  /** 紹介を見終わった直後（「初期設定をはじめる」を大きく出す） */
  const [tourDone, setTourDone] = useState(false)
  /** 直前に押した選択肢（引き継ぎボタンを出すため） */
  const [lastAsked, setLastAsked] = useState<string | null>(null)
  /** AI が担当外と言った → 案内先と、そのまま持っていく質問 */
  const [redirect, setRedirect] = useState<{ to: string; question: string } | null>(null)
  /** AI に聞いている最中 */
  const [thinking, setThinking] = useState(false)
  /** AI 用の取引履歴（取り直しを減らす） */
  const aiTrades = useRef<{ at: number; history: TradeHistory | null } | null>(null)
  const askRef = useRef<(q: string, from?: string) => void>(() => {})

  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  const reconnectTried = useRef(false)
  // この画面でブリッジが一度でも動いていたか（キャラを切り替えても覚えておく）
  const bridgeSeenLive = useRef(false)

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
    setChecks([])
    setError(null)
    setReport(null)
    reconnectTried.current = false

    setTourIndex(0)
    setTourDone(false)
    setLastAsked(null)
    setRedirect(null)
    setThinking(false)

    // 別の研究員から質問を引き継いできた → そのまま聞く
    const handed = takePendingQuestion(character.id)
    if (handed) {
      setPhase('talk')
      setAiText(character.greeting)
      askRef.current(handed.question, handed.from)
      return
    }

    if (saved && character.id === 'algo') {
      setPhase('control')
      setAiText(saved.running ? (character.returningRunning ?? character.greeting) : (character.returningStopped ?? character.greeting))
      return
    }
    if (character.id === 'yui') {
      if (saved) {
        // つながっているのに MT5 側の操作が残っていれば、その案内から再開する
        if (bridge.live && bridge.status && mt5StepIndex(bridge.status) != null) {
          setPhase('mt5')
          setAiText(t(SETUP.mt5Again))
          return
        }
        setPhase('talk')
        setAiText(t(SETUP.already))
        return
      }
      if (!localStorage.getItem(introKey)) {
        setPhase('intro')
        setAiText(t(SETUP.intro))
        return
      }
    }
    setPhase('talk')
    setAiText(character.greeting)
    // t は名前の設定が変わったときだけ変わる。ここではキャラの切り替えだけを見る
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // 紹介中はカメラをその研究員へ。紹介を抜けたら話し相手に戻す
  const tourFocus = useRef(false)
  useEffect(() => {
    if (!onFocus) return
    if (phase === 'tour') {
      tourFocus.current = true
      onFocus(TOUR[tourIndex]?.id ?? null)
    } else if (tourFocus.current) {
      tourFocus.current = false
      onFocus(null)
    }
  }, [phase, tourIndex, onFocus])

  const typing = shown < aiText.length

  // ── MT5 から実データを取る（会話からも、開いたままの自動更新からも使う）──
  const fetchLive = useCallback(
    async (kind: LiveReport['kind']): Promise<{ report: LiveReport; text: string } | null> => {
      if (kind === 'today') {
        const ack = await bridge.send('get_status')
        if (!ack.ok || !ack.today) return null
        return { report: { kind: 'today', today: ack.today, currency: ack.currency }, text: formatTodayAnswer(ack) }
      }
      if (kind === 'history') {
        const ack = await bridge.send('get_history', { days: HISTORY_DAYS })
        if (!ack.ok || !ack.history) return null
        return {
          report: { kind: 'history', history: ack.history, currency: ack.currency },
          text: formatHistoryAnswer(ack.history, ack.currency),
        }
      }
      if (kind === 'review') {
        const ack = await bridge.send('get_trades', { days: REVIEW_DAYS })
        if (!ack.ok || !ack.trades) return null
        const review = reviewTrades(ack.trades, ack.currency)
        return {
          report: { kind: 'review', review, history: ack.trades, currency: ack.currency },
          text: formatReviewAnswer(review, ack.currency),
        }
      }
      const ack = await bridge.send('get_positions')
      if (!ack.ok) return null
      const rows = ack.positions ?? []
      return {
        report: { kind: 'positions', positions: rows, currency: ack.currency },
        text: formatPositionsAnswer(rows, ack.currency),
      }
    },
    [bridge],
  )

  // 出しっぱなしの「今日の成績」「いまのポジション」は、届いた値で書き換える。
  //
  // こちらから定期的に聞きにいくと、Lab が 450ms ごとに再描画する都合で
  // タイマーが張り直され続けて動かない。ブリッジが数秒ごとに送ってくるので、
  // それを受けるだけでよい（通信も処理も増えない）。
  const shownKind = report?.kind
  useEffect(() => {
    if (shownKind !== 'today' && shownKind !== 'positions') return
    const status = bridge.status
    if (!status) return
    if (shownKind === 'today' && status.today) {
      setReport({ kind: 'today', today: status.today, currency: status.currency })
      setReportAt(new Date())
    } else if (shownKind === 'positions' && status.positions) {
      setReport({ kind: 'positions', positions: status.positions, currency: status.currency })
      setReportAt(new Date())
    }
  }, [bridge.status, shownKind])

  // ── 通常会話 ──
  /** 初期設定のはじまり。接続ツールを呼び出し、入っていなければダウンロードの案内へ */
  const startSetup = () => {
    clearTimers()
    setInput('')
    setError(null)
    setReport(null)
    setChecks([])
    setStepIndex(0)
    if (member && !member.can_trade) {
      setPhase('talk')
      setAiText('このアカウントでは自動売買の操作が許可されていません。運営に確認してください。')
      return
    }
    // すでにつながっているPCなら、そのまま接続の確認へ進む
    if (bridge.live) {
      setPhase('connecting')
      setAiText(CONNECT_WAIT)
      return
    }
    setPhase('launching')
    setAiText(t(SETUP.checking))
    launchConnector(member?.id)
  }

  const startTour = () => {
    clearTimers()
    setInput('')
    setReport(null)
    setTourIndex(0)
    setPhase('tour')
    setAiText(t(TOUR[0].text))
  }

  const finishIntro = () => {
    localStorage.setItem(introKey, '1')
  }

  /** AI に渡す取引履歴（アルゴ・ミオ）。1分以内なら前回のものを使う */
  const loadAiTrades = async (): Promise<TradeHistory | null> => {
    const cached = aiTrades.current
    if (cached && Date.now() - cached.at < AI_TRADE_KEEP_MS) return cached.history
    const ack = await bridge.send('get_trades', { days: AI_TRADE_DAYS })
    const history = ack.ok && ack.trades ? ack.trades : null
    aiTrades.current = { at: Date.now(), history }
    return history
  }

  /**
   * AI に聞く。担当ぶんのデータだけを添える。担当外なら案内ボタンを出す。
   * @param from 引き継ぎ元の研究員（引き継がれた質問のとき）
   */
  // 手元のデータを読むだけで答えられる質問は AI に聞かない（費用ゼロ）。
  //   リン: 直近の高値と安値は？   ジン: 次の指標はいつ？ / 今週の重要指標は？
  const localAnswer = (question: string): string | null => {
    if (character.id === 'rin' && question === '直近の高値と安値は？') {
      const c = rinContext(market.marketForAi())
      if (!c) return null
      const maLine = c.ma20 ? fill(c.ma20.priceIs === 'above' ? AI_TEXT.maAbove : AI_TEXT.maBelow, { ma: c.ma20.value }) : ''
      return fill(AI_TEXT.highLow, {
        symbol: c.symbol,
        period: c.period,
        high: c.high.price,
        highAt: c.high.at,
        low: c.low.price,
        lowAt: c.low.at,
        price: c.price,
        toHigh: c.high.distance,
        toLow: c.low.distance,
        maLine,
      })
    }
    if (character.id !== 'jin' || !econ.events) return null
    const when = (e: EconomicEvent) => `${formatEventDate(e.at)}${formatEventTime(e.at)}`
    if (question === '次の指標はいつ？') {
      const e = econ.next
      return e ? fill(ECON_ALERT.nextAnswer, { day: when(e), country: e.countryJa || e.country, title: e.titleJa }) : ECON_ALERT.none
    }
    if (question === '今週の重要指標は？') {
      const all = upcoming(econ.events)
      const high = all.filter((e) => e.impact === 'high')
      const list = (high.length >= 3 ? high : all).slice(0, 6)
      return list.length ? fill(ECON_ALERT.weekAnswer, { list: list.map((e) => `${when(e)} ${eventLabel(e)}`).join('、') }) : ECON_ALERT.none
    }
    return null
  }

  const askViaAi = async (role: AiRole, question: string, from?: string) => {
    setRedirect(null)
    if (character.ai?.needsBridge && !bridge.live) {
      setAiText(character.ai.noBridge ?? character.fallback)
      setBusy(false)
      return
    }
    let context: unknown = null
    let dataError: string | null = null
    if (role === 'rin') {
      context = rinContext(market.marketForAi())
      if (!context) dataError = AI_TEXT.noData
    } else if (role === 'jin') {
      context = jinContext(econ.events, market.quoteMap)
      if (!context) dataError = AI_TEXT.noData
    } else {
      const history = await loadAiTrades()
      context = role === 'algo' ? algoContext(bridge.status ?? null, history) : mioContext(bridge.status ?? null, history)
      if (!context) dataError = '口座の数字を読み取れませんでした。接続ツールが起動しているか見てください。'
    }
    if (dataError) {
      setAiText(dataError)
      setBusy(false)
      return
    }
    const intro = from && characters[from] ? fill(AI_TEXT.handoffIntro, { from: characters[from].name, question }) : ''
    if (intro) setAiText(intro)
    setThinking(true)
    const names: Record<string, string> = {}
    for (const c of Object.values(characters)) names[c.id] = c.name
    const res = await askAi({ role, question, context, names })
    setThinking(false)
    if (!res.ok) {
      // まだ AI の鍵が入っていないときは、用意した受け答えで返す（画面を止めない）
      setAiText(res.why === 'unavailable' ? (character.answers[question] ?? character.fallback) : AI_FAILURE_TEXT[res.why])
    } else if (res.reply.redirect && characters[res.reply.redirect] && res.reply.redirect !== character.id) {
      const to = characters[res.reply.redirect]
      setAiText(fill(AI_TEXT.redirect, { name: to.name, role: to.role }))
      setRedirect({ to: to.id, question })
    } else {
      setAiText(intro ? `${intro} ${res.reply.answer}` : res.reply.answer)
    }
    setBusy(false)
  }

  const ask = (q: string, from?: string) => {
    if (busy || !q.trim()) return
    if (character.startsSetup && q.trim() === character.startsSetup) {
      startSetup()
      return
    }
    if (character.startsTour && q.trim() === character.startsTour) {
      startTour()
      return
    }
    const question = q.trim()
    setTourDone(false)
    setLastAsked(question)
    setBusy(true)
    setAiText('…')
    setReport(null)

    const liveKind = LIVE_QUESTIONS[question]
    if (liveKind) {
      void (async () => {
        if (!bridge.live) {
          setAiText(character.answers[question] ?? character.fallback)
          setBusy(false)
          return
        }
        const got = await fetchLive(liveKind)
        if (got) {
          setAiText(got.text)
          setReport(got.report)
          setReportAt(new Date())
        } else {
          setAiText('口座の数字を読み取れませんでした。接続ツールが起動しているか見てください。')
        }
        setBusy(false)
      })()
      return
    }

    if (question === '調子はどう？') {
      if (bridge.live && bridge.status?.mt5_ready) {
        setAiText(
          Number(bridge.status.value) !== 0
            ? 'MT5との接続は生きています。チャート上の「システム」の表示も合わせてご確認ください。'
            : 'MT5とはつながっています。いまは停止中です。再開は管理画面からできます。',
        )
      } else {
        setAiText(character.answers[question] ?? character.fallback)
      }
      setBusy(false)
      return
    }

    // AI が答える研究員（リン・ジン・アルゴ・ミオ）。それ以外は用意した受け答え
    const local = localAnswer(question)
    if (local) {
      setRedirect(null)
      setAiText(local)
      setBusy(false)
      return
    }
    if (character.ai) {
      void askViaAi(character.id as AiRole, question, from)
      return
    }

    timers.current.push(
      setTimeout(() => {
        setAiText(character.answers[question] ?? character.fallback)
        setBusy(false)
      }, 700),
    )
  }
  askRef.current = ask

  // 「初期設定をはじめる」→ 接続ツールを呼び出したあと。
  // ツールが入っていれば数秒でブリッジが名乗り出る。無ければダウンロードの案内に切り替える。
  useEffect(() => {
    if (phase !== 'launching') return
    if (bridge.live) {
      setPhase('connecting')
      setAiText(CONNECT_WAIT)
      return
    }
    const id = setTimeout(() => {
      setPhase('download')
      setAiText(t(SETUP.needDownload))
    }, CONNECTOR_WAIT_MS)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, bridge.live])

  // ダウンロードを始めたら、ツールの起動を待つ（起動すると実応答で接続に進む）
  const startDownload = () => {
    downloadConnector()
    setError(null)
    setChecks([])
    setStepIndex(0)
    setPhase('waiting')
    setAiText(t(SETUP.waiting))
  }

  // 初回はダウンロードした exe を「開くだけ」なので、ツールは部屋（会員ID）を知らないまま
  // 既定の部屋につながる。画面は会員ID以外の部屋には入れないので、中継の /health で
  // 「その部屋に、いまブリッジが来たか」だけを見る。来ていたら、ツールが登録したばかりの
  // aitrader:// で部屋を伝えて呼び直す（ツールは既定の部屋のブリッジを止め、正しい部屋でつなぎ直す）。
  const watchDefaultRoom = phase === 'waiting' && !!member?.id && member.id !== DEFAULT_ROOM
  const firstRunRelaunched = useRef(false)
  useEffect(() => {
    if (!watchDefaultRoom) {
      firstRunRelaunched.current = false
      return
    }
    const startedAt = Date.now()
    let alive = true
    const check = async () => {
      const probe = await probeRoom(DEFAULT_ROOM)
      if (!alive || !probe?.bridge || firstRunRelaunched.current) return
      // 古い置き去りのブリッジ（別のPC）に反応しないよう、最近つながったものだけ
      if (probe.since != null && probe.since < startedAt - DEFAULT_ROOM_FRESH_MS) return
      firstRunRelaunched.current = true
      launchConnector(member?.id)
      setAiText(t(SETUP.firstRunDetected))
    }
    void check()
    const id = setInterval(() => void check(), DEFAULT_ROOM_POLL_MS)
    return () => {
      alive = false
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchDefaultRoom, member?.id])

  // 接続ツール（ブリッジ）が生きたら、タイマーではなく実応答で接続を進める
  useEffect(() => {
    if (phase !== 'waiting' && phase !== 'download') return
    if (!bridge.live) return
    setError(null)
    setPhase('connecting')
    setStepIndex(0)
    setChecks([])
    setAiText(CONNECT_WAIT)
  }, [phase, bridge.live])

  useEffect(() => {
    if (phase !== 'connecting') return
    if (!bridge.live) {
      setError(
        bridge.error
          ? formatBridgeError(bridge.error)
          : 'E008: MT5 連携なしでは接続を完了できません',
      )
      setAiText('接続ツールからの応答がありません。中継サーバーとブリッジが起動しているか確認してください。')
      return
    }
    let cancelled = false
    ;(async () => {
      const ack = await bridge.send('get_status')
      if (cancelled) return
      const account = ack.account != null && String(ack.account) !== '' ? String(ack.account) : ''
      if (!ack.ok || !ack.mt5_ready || !account) {
        setChecks(connectChecksFromStatus(ack))
        setStepIndex(4)
        setError(
          ack.error
            ? ack.error
            : bridge.error
              ? formatBridgeError(bridge.error)
              : 'E008: MT5 連携なしでは接続を完了できません',
        )
        setAiText('MT5の口座情報を読み取れませんでした。接続ツールとMT5が起動しているか確認してください。')
        return
      }
      const lines = connectChecksFromStatus(ack)
      setChecks(lines)
      setStepIndex(lines.length)
      // 初期設定は「つなぐ」まで。稼働に入れるのは、お客様がアルゴの管理画面で
      // 「自動売買をはじめる」を押したときだけ（ブリッジは自分から稼働にはしない）。
      const running = typeof ack.value === 'number' ? Number(ack.value) !== 0 : false
      const created = newConnection(member?.email ?? '', account, String(ack.server ?? ''), {
        settings: settingsFromGate(ack.gate),
        running,
      })
      saveConnection(created)
      setConn(created)
      setError(null)
      finishIntro()
      // チャートに載せる・自動売買ボタンを押すのは MT5 の画面でしかできない。
      // 残っていればその案内へ。済んでいれば完了。
      if (mt5StepIndex(ack) != null) {
        setPhase('mt5')
        setAiText(t(SETUP.mt5Intro))
      } else {
        setPhase('done')
        setAiText(t(SETUP.done))
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, bridge.live, bridge.send, bridge.error])

  // MT5 側の操作を見張る。ブリッジが送ってくる状態を見るだけで、こちらからは何もしない。
  // 手順が1つ進んだら台詞を切り替え、すべて済んだら完了へ。
  const mt5Step = useRef<number | null>(null)
  useEffect(() => {
    if (phase !== 'mt5') {
      mt5Step.current = null
      return
    }
    if (!bridge.live) return
    const idx = mt5StepIndex(bridge.status)
    if (idx == null) {
      setPhase('done')
      setAiText(t(SETUP.done))
      return
    }
    if (mt5Step.current !== null && idx !== mt5Step.current) {
      setAiText(t(idx === 0 ? SETUP.mt5Attach : SETUP.mt5Button))
    }
    mt5Step.current = idx
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, bridge.live, bridge.status])

  // MT5 が返した口座を常に正とする（保存済み口座よりブリッジを優先）
  useEffect(() => {
    if (!conn || !bridge.live || bridge.status?.account == null) return
    const next = applyBridgeToConnection(conn, bridge.status)
    const unchanged =
      connectionAccountKey(next) === connectionAccountKey(conn) &&
      next.running === conn.running &&
      JSON.stringify(next.settings) === JSON.stringify(conn.settings)
    if (unchanged) return

    const accountChanged = !connectionMatchesBridge(conn, bridge.status)
    saveConnection(next)
    setConn(next)
    if (accountChanged && character.id === 'algo' && (phase === 'control' || phase === 'talk')) {
      setAiText(`MT5の口座（${next.account}／${next.server}）に合わせて接続を更新しました。`)
    }
  }, [conn, bridge.live, bridge.status, character.id, phase])

  // 連携済みで戻ってきたのにブリッジが切れている → 接続ツールを一度だけ呼び直す。
  // ただし、この画面でいちど動いていたブリッジが消えたときは呼ばない
  // （お客様が「停止する」で止めた直後に、サイトが勝手に起こし直してしまうため）。
  useEffect(() => {
    if (character.id !== 'algo' || phase !== 'control' || !conn) return
    if (bridge.live) {
      bridgeSeenLive.current = true
      return
    }
    if (bridge.phase !== 'no_bridge') return
    if (reconnectTried.current || bridgeSeenLive.current) return
    reconnectTried.current = true
    launchConnector(member?.id)
    if (character.reconnecting) setAiText(character.reconnecting)
  }, [character, phase, conn, bridge.live, bridge.phase, member?.id])

  // 管理画面は ControlPanel 側で出すので、ここでは出さない（二重表示になる）
  const showBridgeBar = phase === 'waiting' || phase === 'connecting' || phase === 'mt5' || phase === 'done'

  /** 別の研究員に引き継ぐ。カメラは受付から離れるので、紹介のフォーカスも外す */
  const handoffTo = (id: string) => {
    if (onSelect) onSelect(id)
    else onClose()
  }

  /** 設定の途中でやめて、通常会話に戻る */
  const backToTalk = () => {
    clearTimers()
    setError(null)
    setChecks([])
    setPhase('talk')
    setAiText(character.greeting)
  }

  const reconnect = () => {
    launchConnector(member?.id)
    if (character.reconnecting) setAiText(character.reconnecting)
  }

  /** 連携後だけ出す「設定 / 相談」の切り替え */
  const canSwitch = !!conn && character.id === 'algo' && (phase === 'control' || phase === 'talk')

  const switchTo = (next: 'control' | 'talk') => {
    if (phase === next) return
    clearTimers()
    setBusy(false)
    setInput('')
    setReport(null)
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
              {phase === 'intro'
                ? 'はじめまして'
                : phase === 'tour'
                  ? `メンバー紹介 ${tourIndex + 1}/${TOUR.length}`
                  : phase === 'launching'
                    ? '呼び出し中…'
                    : phase === 'download'
                      ? '初期設定'
                      : phase === 'waiting'
                        ? '起動を待っています'
                        : phase === 'connecting'
                          ? '接続中…'
                          : phase === 'mt5'
                            ? 'MT5の準備'
                          : phase === 'control'
                            ? '管理画面'
                            : '連携完了'}
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
        {showBridgeBar && <div className="px-6 pt-3"><BridgeStatusBar bridge={bridge} /></div>}
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
            {thinking && (
              <div className="flex items-center gap-3 px-6 pb-3">
                <span className="spin h-4 w-4 shrink-0 rounded-full" style={{ border: '2px solid rgba(94,204,255,0.2)', borderTopColor: 'var(--accent)' }} />
                <p className="font-mono text-[13px] text-slate-400">{fill(AI_TEXT.thinking, { name: character.name })}</p>
              </div>
            )}
            {/* 担当外だった → 担当の研究員へ、質問ごと引き継ぐ */}
            {redirect && characters[redirect.to] && !typing && !busy && (
              <div className="px-6 pb-3">
                <button
                  type="button"
                  onClick={() => {
                    setPendingQuestion({ to: redirect.to, from: character.id, question: redirect.question })
                    handoffTo(redirect.to)
                  }}
                  className="flex h-12 items-center gap-3 rounded-[5px] border px-5 text-[15px] font-bold transition hover:brightness-110 active:translate-y-px"
                  style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607', boxShadow: '0 0 14px rgba(250,204,21,0.3)' }}
                >
                  <PixelPerson look={characters[redirect.to].look} s={1.6} />
                  ▶ {fill(AI_TEXT.redirectButton, { name: characters[redirect.to].name })}
                  <span className="font-mono text-[12px] font-bold opacity-70">{characters[redirect.to].role}</span>
                </button>
              </div>
            )}
            {report && !typing && (
              <div className="px-6 pb-3">
                <LiveReportView report={report} updatedAt={reportAt} />
              </div>
            )}
            {/* 別の担当へ案内する（例: アルゴ →「初期設定は受付のユイ」） */}
            {character.handoff && !conn && !typing && !busy && lastAsked === character.handoff.choice && (
              <div className="px-6 pb-3">
                <button
                  type="button"
                  onClick={() => handoffTo(character.handoff!.to)}
                  className="h-12 rounded-[5px] border px-6 text-[15px] font-bold transition hover:brightness-110 active:translate-y-px"
                  style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607', boxShadow: '0 0 14px rgba(250,204,21,0.3)' }}
                >
                  ▶ {t(character.handoff.button)}
                </button>
              </div>
            )}
            {tourDone && !typing && (
              <div className="flex flex-wrap items-center gap-3 px-6 pb-3">
                <SetupButton
                  primary
                  onClick={() => {
                    setTourDone(false)
                    startSetup()
                  }}
                >
                  ▶ {SETUP.tourDoneNext}
                </SetupButton>
                <SetupButton
                  onClick={() => {
                    setTourDone(false)
                    setAiText(character.greeting)
                  }}
                >
                  {SETUP.tourDoneLater}
                </SetupButton>
              </div>
            )}
            {/* ジン：発表前のブラウザ通知 */}
            {character.id === 'jin' && !typing && !busy && econ.permission !== 'unsupported' && (
              <div className="flex flex-wrap items-center gap-3 px-6 pb-3">
                {econ.permission === 'default' ? (
                  <button
                    type="button"
                    onClick={() => {
                      void econ.requestPermission().then((got) => {
                        if (got === 'granted') setAiText(ECON_ALERT.notifyOn)
                        else if (got === 'denied') setAiText(ECON_ALERT.notifyDenied)
                      })
                    }}
                    className="h-11 rounded-[5px] border px-4 text-[14px] font-bold text-slate-100 transition hover:brightness-125 active:translate-y-px"
                    style={{ borderColor: 'rgba(255,200,61,0.5)', background: 'rgba(255,200,61,0.1)' }}
                  >
                    {ECON_ALERT.notifyButton}
                  </button>
                ) : (
                  <span className="font-mono text-[12px] text-slate-400">
                    {econ.permission === 'granted' ? '🔔 発表前のブラウザ通知: オン' : '🔕 ブラウザの通知は許可されていません'}
                  </span>
                )}
                {econ.nextLine && <span className="font-mono text-[12px] text-slate-500">{econ.nextLine}</span>}
              </div>
            )}
            {!tourDone && (
            <>
            <div className="flex flex-wrap gap-2.5 px-6 pb-3">
              {(conn && character.connectedChoices ? character.connectedChoices : character.choices).map((c) => {
                const isSetup = character.startsSetup === c || character.handoff?.choice === c
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
          </>
        )}

        {/* ══════ はじめまして：紹介を見るか、すぐ初期設定へ ══════ */}
        {phase === 'intro' && (
          <div className="flex flex-wrap items-center gap-3 border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <SetupButton primary onClick={startTour}>
              ▶ {SETUP.introTour}
            </SetupButton>
            <SetupButton
              onClick={() => {
                finishIntro()
                startSetup()
              }}
            >
              {SETUP.introSkip}
            </SetupButton>
          </div>
        )}

        {/* ══════ メンバー紹介：一人ずつ ══════ */}
        {phase === 'tour' && (() => {
          const step = TOUR[tourIndex]
          const who = characters[step.id]
          const last = tourIndex >= TOUR.length - 1
          return (
            <div className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
              <div className="flex items-center gap-5">
                <div
                  className="flex h-[92px] w-[92px] shrink-0 items-center justify-center rounded-[6px] border"
                  style={{ borderColor: `${who.color}66`, background: `${who.color}14`, boxShadow: `0 0 18px ${who.color}33` }}
                >
                  <PixelPerson look={who.look} s={3.4} />
                </div>
                <div className="min-w-0">
                  <p className="text-[17px] font-bold text-white">
                    {who.role}
                    <span className="font-dot ml-2 text-[16px]" style={{ color: who.color }}>
                      {who.name}
                    </span>
                  </p>
                  <p className="mt-1 text-[13px] font-bold text-slate-400">こんなことをお願いできます</p>
                  <div className="mt-1.5 flex flex-wrap gap-2">
                    {step.can.map((c) => (
                      <span
                        key={c}
                        className="rounded-[4px] border px-2.5 py-1 text-[13px] font-bold text-slate-200"
                        style={{ borderColor: 'rgba(94,204,255,0.35)', background: 'rgba(94,204,255,0.07)' }}
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                {tourIndex > 0 && (
                  <SetupButton
                    onClick={() => {
                      setTourIndex((i) => i - 1)
                      setAiText(t(TOUR[tourIndex - 1].text))
                    }}
                  >
                    ◀ 前へ
                  </SetupButton>
                )}
                <SetupButton
                  primary
                  onClick={() => {
                    if (last) {
                      finishIntro()
                      setPhase('talk')
                      setAiText(t(SETUP.tourDone))
                      setTourDone(true)
                      return
                    }
                    setTourIndex((i) => i + 1)
                    setAiText(t(TOUR[tourIndex + 1].text))
                  }}
                >
                  {last ? '紹介はここまで ▶' : '次へ ▶'}
                </SetupButton>
                <span className="font-mono ml-auto text-[12px] text-slate-500">
                  {tourIndex + 1} / {TOUR.length}
                </span>
              </div>
            </div>
          )
        })()}

        {/* ══════ 接続ツールを呼び出している間 ══════ */}
        {phase === 'launching' && (
          <div className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <div
              className="mb-3 flex flex-wrap items-center gap-4 rounded-[6px] border px-5 py-4"
              style={{ borderColor: 'rgba(94,204,255,0.4)', background: 'rgba(94,204,255,0.06)' }}
            >
              <span
                className="spin h-5 w-5 shrink-0 rounded-full"
                style={{ border: '2px solid rgba(94,204,255,0.2)', borderTopColor: 'var(--accent)' }}
              />
              <p className="text-[15px] font-bold text-slate-200">{SETUP.checkingLabel}</p>
              <span className="font-mono ml-auto text-[12px] tracking-wide text-slate-500">画面は出ません</span>
            </div>

            <p className="mb-2 text-[13px] font-bold text-slate-400">入っていれば、お客様のパソコンでこう進みます</p>
            <ol className="space-y-2">
              {CONNECTOR_STEPS.map((step) => (
                <li key={step} className="flex items-start gap-3">
                  <span
                    className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[12px] font-bold"
                    style={{ background: 'rgba(94,204,255,0.12)', color: 'var(--accent)', border: '1px solid rgba(94,204,255,0.4)' }}
                  >
                    ・
                  </span>
                  <span className="text-[15px] font-bold text-slate-300">{step}</span>
                </li>
              ))}
            </ol>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <SetupButton
                onClick={() => {
                  setPhase('download')
                  setAiText(t(SETUP.needDownload))
                }}
              >
                {SETUP.notYet}
              </SetupButton>
              <button type="button" onClick={backToTalk} className="font-mono ml-auto text-[12px] text-slate-400 underline-offset-4 hover:underline">
                {SETUP.back}
              </button>
            </div>
          </div>
        )}

        {/* ══════ 接続ツールのダウンロード ══════ */}
        {phase === 'download' && (
          <div className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1.5">
              {['MT5のパスワードは不要', '口座番号の入力も不要', '設定画面はありません'].map((m) => (
                <span
                  key={m}
                  className="rounded-[4px] border px-2.5 py-1 text-[12px] font-bold text-[#35f58a]"
                  style={{ borderColor: 'rgba(53,245,138,0.4)', background: 'rgba(53,245,138,0.08)' }}
                >
                  ✓ {m}
                </span>
              ))}
            </div>

            <button
              type="button"
              onClick={startDownload}
              className="flex h-14 w-full items-center justify-center gap-3 rounded-[6px] border text-[17px] font-bold transition hover:brightness-110 active:translate-y-px"
              style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607', boxShadow: '0 0 18px rgba(250,204,21,0.3)' }}
            >
              ⬇ {SETUP.downloadButton}
              <span className="font-mono text-[12px] font-bold opacity-70">{CONNECTOR_DOWNLOAD.saveAs}</span>
            </button>
            <p className="font-mono mt-2 text-center text-[12px] text-slate-500">{SETUP.downloadNote}</p>

            <p className="mb-2 mt-4 text-[13px] font-bold text-slate-400">ダウンロードしたあとの手順（私が順にご案内します）</p>
            <InstallSteps active={0} />

            <div className="mt-3 flex">
              <button type="button" onClick={backToTalk} className="font-mono ml-auto text-[12px] text-slate-400 underline-offset-4 hover:underline">
                {SETUP.back}
              </button>
            </div>
          </div>
        )}

        {/* ══════ ダウンロードしたあと：起動を待つ ══════ */}
        {phase === 'waiting' && (
          <div className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <InstallSteps active={1} />

            <div
              className="mt-4 flex flex-wrap items-center gap-4 rounded-[6px] border px-5 py-4"
              style={{ borderColor: 'rgba(250,204,21,0.4)', background: 'rgba(250,204,21,0.06)' }}
            >
              <span className="spin h-5 w-5 shrink-0 rounded-full" style={{ border: '2px solid rgba(250,204,21,0.25)', borderTopColor: '#ffd23e' }} />
              <p className="text-[15px] font-bold text-slate-200">{SETUP.waitingLabel}</p>
              <span className="font-mono ml-auto text-[12px] tracking-wide text-slate-500">{SETUP.waitingNote}</span>
            </div>

            {error && <p className="mt-3 text-[13px] font-bold leading-relaxed text-[#ff8484]">⚠ {error}</p>}

            <div className="mt-3 flex flex-wrap items-center gap-3">
              <SetupButton onClick={startDownload}>⬇ {SETUP.redownload}</SetupButton>
              <SetupButton onClick={() => launchConnector(member?.id)}>{SETUP.retry}</SetupButton>
              <button type="button" onClick={backToTalk} className="font-mono ml-auto text-[12px] text-slate-400 underline-offset-4 hover:underline">
                {SETUP.back}
              </button>
            </div>
          </div>
        )}

        {/* ══════ つながったあと、MT5 の画面でお客様がすること（終わると自動で進む） ══════ */}
        {phase === 'mt5' && (
          <div className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
            <p className="mb-2.5 text-[13px] font-bold text-slate-400">MT5 の画面で、一度だけお願いします。</p>
            <InstallSteps steps={MT5_STEPS} active={mt5StepIndex(bridge.status) ?? MT5_STEPS.length} />

            <div
              className="mt-4 flex flex-wrap items-center gap-4 rounded-[6px] border px-5 py-4"
              style={{ borderColor: 'rgba(250,204,21,0.4)', background: 'rgba(250,204,21,0.06)' }}
            >
              <span className="spin h-5 w-5 shrink-0 rounded-full" style={{ border: '2px solid rgba(250,204,21,0.25)', borderTopColor: '#ffd23e' }} />
              <p className="text-[15px] font-bold text-slate-200">{SETUP.mt5Label}</p>
              <span className="font-mono ml-auto text-[12px] tracking-wide text-slate-500">{SETUP.mt5Note}</span>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-3">
              <SetupButton
                onClick={() => {
                  setPhase('done')
                  setAiText(t(SETUP.done))
                }}
              >
                {SETUP.mt5Later}
              </SetupButton>
              <button type="button" onClick={backToTalk} className="font-mono ml-auto text-[12px] text-slate-400 underline-offset-4 hover:underline">
                {SETUP.back}
              </button>
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
              {checks.length === 0 && phase === 'connecting' && (
                <li className="step-in flex items-center gap-3">
                  <span
                    className="spin h-5 w-5 shrink-0 rounded-full"
                    style={{
                      border: '2px solid rgba(94,204,255,0.2)',
                      borderTopColor: 'var(--accent)',
                    }}
                  />
                  <span className="text-[15px] font-bold text-white">{CONNECT_WAIT}…</span>
                </li>
              )}
              {checks.map((step) => (
                <li key={step.working} className="step-in flex items-center gap-3">
                  <span
                    className="check-pop flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[12px] font-bold"
                    style={
                      step.ok
                        ? { background: 'rgba(53,245,138,0.15)', color: '#35f58a', border: '1px solid rgba(53,245,138,0.5)' }
                        : { background: 'rgba(250,204,21,0.12)', color: '#ffd23e', border: '1px solid rgba(250,204,21,0.5)' }
                    }
                  >
                    {step.ok ? '✓' : '!'}
                  </span>
                  <span className="text-[15px] font-bold text-slate-300">{step.done}</span>
                </li>
              ))}
            </ol>

            {/* 進捗バー */}
            <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full" style={{ background: 'rgba(94,204,255,0.12)' }}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${checks.length === 0 ? 12 : (stepIndex / Math.max(checks.length, 1)) * 100}%`,
                  background: 'var(--accent)',
                  boxShadow: '0 0 10px var(--accent)',
                }}
              />
            </div>

            {error && phase === 'connecting' && (
              <>
                <p className="mt-3 text-[13px] font-bold leading-relaxed text-[#ff8484]">⚠ {error}</p>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <SetupButton primary onClick={startSetup}>
                    {SETUP.retry}
                  </SetupButton>
                  <SetupButton
                    onClick={() => {
                      setPhase('download')
                      setAiText(t(SETUP.needDownload))
                    }}
                  >
                    ⬇ {SETUP.downloadButton}
                  </SetupButton>
                  <button type="button" onClick={backToTalk} className="font-mono ml-auto text-[12px] text-slate-400 underline-offset-4 hover:underline">
                    {SETUP.back}
                  </button>
                </div>
              </>
            )}

            {/* 連携できた：稼働やロットの操作はアルゴへ引き継ぐ */}
            {phase === 'done' && (
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <SetupButton primary onClick={() => handoffTo('algo')}>
                  ▶ {t(SETUP.doneAlgo)}
                </SetupButton>
                <SetupButton onClick={onClose}>{SETUP.doneBack}</SetupButton>
              </div>
            )}
          </div>
        )}

        {/* ══════ 管理画面（接続ずみのお客様が次に開くのはここ） ══════ */}
        {phase === 'control' && conn && (
          <ControlPanel
            bridge={bridge}
            conn={conn}
            onReconnect={reconnect}
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

/** 初期設定の流れで使うボタン（高さ 48px、黄色が主・暗色が従） */
function SetupButton({ primary, onClick, children }: { primary?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="h-12 rounded-[5px] border px-5 text-[15px] font-bold transition hover:brightness-110 active:translate-y-px"
      style={
        primary
          ? { background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607', boxShadow: '0 0 14px rgba(250,204,21,0.3)' }
          : { borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.6)', color: '#e8edf5' }
      }
    >
      {children}
    </button>
  )
}

/** お客様がする手順の一覧。active より前は済み、active はいま、あとは待ち */
function InstallSteps({ active, steps = INSTALL_STEPS }: { active: number; steps?: UserStep[] }) {
  // ダウンロード手順の最後は「あとは待つだけ」なので、やる前から緑で出す
  const lastIsWait = steps === INSTALL_STEPS
  return (
    <ol className="space-y-2.5">
      {steps.map((u, i) => {
        const done = i < active
        const now = i === active
        const last = lastIsWait && i === steps.length - 1
        const color = done ? '#35f58a' : now ? '#ffd23e' : last ? '#35f58a' : 'var(--accent)'
        return (
          <li key={u.no} className="flex items-start gap-3" style={{ opacity: done ? 0.55 : 1 }}>
            <span
              className="font-mono mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-bold"
              style={{ color, border: `1px solid ${color}`, background: now ? 'rgba(250,204,21,0.15)' : 'rgba(94,204,255,0.08)' }}
            >
              {done ? '✓' : u.no}
            </span>
            <span>
              <span className="text-[15px] font-bold text-white">{u.title}</span>
              <span className="ml-2 text-[13px] text-slate-400">{u.detail}</span>
              {u.figure && now && <SetupFigure kind={u.figure} />}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
