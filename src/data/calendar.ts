// 経済指標カレンダー。/api/calendar が ForexFactory から取ってきたものだけを使い、
// ここでは予定を作らない。時刻は日本時間で表示する。
import type { EconomicEvent } from '../../api/_lib/calendar'

export type { EconomicEvent }

export async function loadCalendar(): Promise<EconomicEvent[]> {
  const res = await fetch('/api/calendar')
  if (!res.ok) throw new Error(`calendar ${res.status}`)
  const data = (await res.json()) as { events?: EconomicEvent[] }
  return data.events ?? []
}

const JST = 'Asia/Tokyo'

/** 「9/5 21:30」 */
export function formatEventDay(iso: string): string {
  const d = new Date(iso)
  const md = d.toLocaleDateString('ja-JP', { timeZone: JST, month: 'numeric', day: 'numeric' })
  return `${md} ${formatEventTime(iso)}`
}

/** 「21:30」 */
export function formatEventTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('ja-JP', { timeZone: JST, hour: '2-digit', minute: '2-digit', hour12: false })
}

/** 「9/5（金）」 */
export function formatEventDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ja-JP', { timeZone: JST, month: 'numeric', day: 'numeric', weekday: 'narrow' }).replace(/\((.)\)/, '（$1）')
}

/** これから（いま以降）の予定だけ、時刻順に */
export function upcoming(events: EconomicEvent[], now = Date.now()): EconomicEvent[] {
  return events.filter((e) => new Date(e.at).getTime() >= now)
}

/** 画面に出す短い名前。「米・雇用統計」 */
export function eventLabel(e: EconomicEvent): string {
  return e.countryJa ? `${e.countryJa}・${e.titleJa}` : e.titleJa
}
