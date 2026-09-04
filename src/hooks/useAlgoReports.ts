// アルゴの運用報告。
// ブリッジが数秒ごとに送ってくる status を見て、変化があったときと定期的に
// ひとこと作る。数字は status に入っている値を当てはめるだけで、ここでは作らない。
// 取引の処理やブリッジへの問い合わせは一切しない（読むだけ）。
import { useEffect, useRef, useState } from 'react'
import { ALGO_REPORT } from '../data/characters'
import { formatSigned, winRate } from '../data/setupFlow'
import type { useBridge } from './useBridge'

export interface AlgoReport {
  id: number
  at: Date
  kind: 'trade' | 'system' | 'periodic'
  text: string
  tone: 'info' | 'good' | 'bad'
}

const MAX_HISTORY = 60
/** 定期報告の間隔 */
const PERIODIC_MS = 45_000
/** 変化の報告のあと、定期報告を少し待つ */
const FIRST_DELAY_MS = 12_000

function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? ''))
}

function toneOf(n: number): AlgoReport['tone'] {
  return n > 0 ? 'good' : n < 0 ? 'bad' : 'info'
}

/**
 * @param bridge  useBridge の戻り値
 * @param quiet   会話中など、定期報告を出したくないとき true
 */
export function useAlgoReports(bridge: ReturnType<typeof useBridge>, quiet: boolean) {
  const [reports, setReports] = useState<AlgoReport[]>([])
  /** いま頭上に出している報告 */
  const [current, setCurrent] = useState<AlgoReport | null>(null)
  const seq = useRef(0)
  const prev = useRef<{ closed: number; profit: number; running: boolean | null; live: boolean } | null>(null)
  const rotate = useRef(0)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const push = (kind: AlgoReport['kind'], text: string, tone: AlgoReport['tone'] = 'info') => {
    const item: AlgoReport = { id: ++seq.current, at: new Date(), kind, text, tone }
    setReports((list) => [item, ...list].slice(0, MAX_HISTORY))
    setCurrent(item)
    if (hideTimer.current) clearTimeout(hideTimer.current)
    hideTimer.current = setTimeout(() => setCurrent(null), kind === 'periodic' ? 8000 : 11000)
  }
  const pushRef = useRef(push)
  pushRef.current = push

  // ── 変化を見る（接続・停止／再開・決済） ──
  const status = bridge.status
  const live = bridge.live
  useEffect(() => {
    const today = status?.today
    const closed = today?.today_closed ?? 0
    const profit = today?.today_profit ?? 0
    const running = live && typeof status?.value === 'number' ? Number(status.value) !== 0 : null
    const cur = status?.currency
    const p = prev.current

    if (!p) {
      // 最初の1回は覚えるだけ（開いた瞬間に「決済されました」と言わない）
      if (live && status) prev.current = { closed, profit, running, live }
      else if (!live) prev.current = { closed: 0, profit: 0, running: null, live: false }
      return
    }

    if (live && !p.live) {
      pushRef.current(
        'system',
        fill(ALGO_REPORT.connected, { account: String(status?.account ?? ''), server: String(status?.server ?? '') }),
        'good',
      )
      prev.current = { closed, profit, running, live: true }
      return
    }
    if (!live && p.live) {
      pushRef.current('system', ALGO_REPORT.disconnected, 'bad')
      prev.current = { ...p, live: false }
      return
    }
    if (!live) return

    if (running !== null && p.running !== null && running !== p.running) {
      pushRef.current('system', running ? ALGO_REPORT.resumed : ALGO_REPORT.stopped, running ? 'good' : 'info')
    }

    if (closed > p.closed) {
      const n = closed - p.closed
      const delta = profit - p.profit
      const todayText = formatSigned(profit, cur)
      if (n === 1) {
        pushRef.current('trade', fill(ALGO_REPORT.tradeClosed, { profit: formatSigned(delta, cur), today: todayText }), toneOf(delta))
      } else {
        pushRef.current('trade', fill(ALGO_REPORT.tradesClosed, { count: n, today: todayText }), toneOf(delta))
      }
    }
    prev.current = { closed, profit, running, live }
  }, [status, live])

  // ── 定期報告（接続中だけ。会話中は出さない） ──
  const statusRef = useRef(status)
  statusRef.current = status
  useEffect(() => {
    if (!live || quiet) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const tick = () => {
      if (!alive) return
      const s = statusRef.current
      const today = s?.today
      const closed = today?.today_closed ?? 0
      const profit = today?.today_profit ?? 0
      const wins = today?.today_wins ?? 0
      const losses = today?.today_losses ?? 0
      const positions = s?.positions?.length ?? today?.open_positions ?? 0
      const floating = s?.positions ? s.positions.reduce((a, r) => a + (r.profit ?? 0), 0) : (today?.open_profit ?? 0)
      const running = typeof s?.value === 'number' ? Number(s.value) !== 0 : true
      const cur = s?.currency
      const rate = winRate(wins, closed)

      const menu: Array<[string, AlgoReport['tone']]> = [
        closed > 0
          ? [fill(ALGO_REPORT.todayProfit, { today: formatSigned(profit, cur), count: closed }), toneOf(profit)]
          : [ALGO_REPORT.todayNone, 'info'],
        positions > 0
          ? [fill(ALGO_REPORT.positions, { positions, floating: formatSigned(floating, cur) }), toneOf(floating)]
          : [ALGO_REPORT.positionsNone, 'info'],
        ...(closed > 0 && rate != null
          ? [[fill(ALGO_REPORT.winRate, { rate, wins, losses }), 'info'] as [string, AlgoReport['tone']]]
          : []),
        running ? [ALGO_REPORT.watching, 'info'] : [ALGO_REPORT.paused, 'info'],
      ]
      const [text, tone] = menu[rotate.current % menu.length]
      rotate.current++
      pushRef.current('periodic', text, tone)
      timer = setTimeout(tick, PERIODIC_MS)
    }
    timer = setTimeout(tick, FIRST_DELAY_MS)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [live, quiet])

  useEffect(
    () => () => {
      if (hideTimer.current) clearTimeout(hideTimer.current)
    },
    [],
  )

  const dismiss = () => {
    setCurrent(null)
    if (hideTimer.current) clearTimeout(hideTimer.current)
  }

  return { reports, current, dismiss }
}
