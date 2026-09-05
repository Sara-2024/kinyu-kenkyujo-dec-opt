// ジンの経済指標のお知らせ。
// /api/calendar（ForexFactory）の予定を 30 分ごとに読み、発表の 1 時間前と 10 分前に
// ジンの頭上に吹き出しを出す。ブラウザの通知が許可されていれば、画面を開いていなくても届く。
// 予定も時刻もカレンダーが返したものをそのまま使い、ここでは作らない。
import { useCallback, useEffect, useRef, useState } from 'react'
import { ECON_ALERT } from '../data/characters'
import { eventLabel, formatEventTime, loadCalendar, upcoming, type EconomicEvent } from '../data/calendar'

export interface EconAlert {
  id: number
  text: string
  tone: 'warn' | 'alert'
  event: EconomicEvent
}

const RELOAD_MS = 30 * 60 * 1000
const CHECK_MS = 30 * 1000
const SHOW_MS = 15 * 1000
/** 発表の何分前に知らせるか。重要度「高」は両方、「中」は 1 時間前だけ */
const THRESHOLDS = [60, 10] as const
const DONE_KEY = 'trelab-econ-alerted'

function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? ''))
}

function readDone(): Set<string> {
  try {
    const raw = localStorage.getItem(DONE_KEY)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

function writeDone(set: Set<string>): void {
  try {
    // 古いものは捨てる（id の先頭が ISO 時刻なので、文字列で比べられる）
    const cutoff = new Date(Date.now() - 3 * 86400_000).toISOString()
    localStorage.setItem(DONE_KEY, JSON.stringify([...set].filter((k) => k > cutoff)))
  } catch {
    // 保存できなくても動きは止めない
  }
}

export function notificationPermission(): NotificationPermission | 'unsupported' {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported'
  return Notification.permission
}

export function useEconomicAlerts(quiet: boolean) {
  const [events, setEvents] = useState<EconomicEvent[] | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [current, setCurrent] = useState<EconAlert | null>(null)
  const [permission, setPermission] = useState(notificationPermission)
  const seq = useRef(0)
  const done = useRef<Set<string> | null>(null)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const quietRef = useRef(quiet)
  quietRef.current = quiet

  // ── 予定を読む ──
  useEffect(() => {
    let alive = true
    const pull = async () => {
      try {
        const list = await loadCalendar()
        if (alive) {
          setEvents(list)
          setLoadFailed(false)
        }
      } catch {
        // 取れないときは前回の予定のまま。まだ一度も取れていなければ、そう表示する
        if (alive) setLoadFailed(true)
      }
    }
    void pull()
    const id = setInterval(pull, RELOAD_MS)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  // ── 発表前かどうかを見る ──
  const eventsRef = useRef(events)
  eventsRef.current = events
  useEffect(() => {
    const tick = () => {
      const list = eventsRef.current
      if (!list) return
      if (!done.current) done.current = readDone()
      const now = Date.now()
      for (const e of upcoming(list, now)) {
        const minutes = (new Date(e.at).getTime() - now) / 60_000
        if (minutes > THRESHOLDS[0] + 2) break
        for (const th of THRESHOLDS) {
          if (th === 10 && e.impact !== 'high') continue
          // その分数の前後 2 分の窓に入ったら一度だけ
          if (minutes > th + 2 || minutes < th - 2) continue
          const key = `${e.at}|${e.id}|${th}`
          if (done.current.has(key)) continue
          done.current.add(key)
          writeDone(done.current)
          const vars = { title: e.titleJa, country: e.countryJa || e.country, time: formatEventTime(e.at), minutes: Math.round(minutes) }
          const text = fill(th === 60 ? ECON_ALERT.hour : ECON_ALERT.soon, vars)
          const item: EconAlert = { id: ++seq.current, text, tone: th === 60 ? 'warn' : 'alert', event: e }
          setCurrent(item)
          if (hideTimer.current) clearTimeout(hideTimer.current)
          hideTimer.current = setTimeout(() => setCurrent(null), SHOW_MS)
          if (e.impact === 'high' && notificationPermission() === 'granted') {
            try {
              new Notification(ECON_ALERT.notifyLabel, { body: text.replace(/^⏰\s*/, ''), tag: key })
            } catch {
              // 通知が出せない環境でも吹き出しは出る
            }
          }
          return
        }
      }
    }
    tick()
    const id = setInterval(tick, CHECK_MS)
    return () => clearInterval(id)
  }, [events])

  useEffect(
    () => () => {
      if (hideTimer.current) clearTimeout(hideTimer.current)
    },
    [],
  )

  const requestPermission = useCallback(async () => {
    if (notificationPermission() === 'unsupported') return 'unsupported' as const
    try {
      const got = await Notification.requestPermission()
      setPermission(got)
      return got
    } catch {
      return 'denied' as const
    }
  }, [])

  const dismiss = useCallback(() => {
    setCurrent(null)
    if (hideTimer.current) clearTimeout(hideTimer.current)
  }, [])

  /** 次の重要な指標（吹き出しの定期案内やカレンダー表示に使う） */
  const next = events ? upcoming(events).find((e) => e.impact === 'high') ?? upcoming(events)[0] ?? null : null
  const nextLine = events
    ? next
      ? fill(ECON_ALERT.next, { title: next.titleJa, country: next.countryJa || next.country, time: formatEventTime(next.at) })
      : ECON_ALERT.none
    : null

  return { events, loadFailed, current: quiet ? null : current, dismiss, next, nextLine, permission, requestPermission, eventLabel }
}
