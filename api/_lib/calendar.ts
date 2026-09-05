// 経済指標カレンダーの取り次ぎ。ForexFactory が配っている今週・来週の JSON を
// サイト側のサーバー関数で取り、画面が使いやすい形（日本語名・UTC時刻）に整えて返す。
//
//   /api/calendar   … これから2週間ぶんの、重要度「高」「中」の指標
//
// 数字（予想・前回）はそのまま渡すだけで、ここでは作らない。

export interface EconomicEvent {
  /** 同じ指標を二度通知しないための識別子 */
  id: string
  /** 元の英語名 */
  title: string
  /** 画面に出す名前（対訳が無ければ英語のまま） */
  titleJa: string
  /** 通貨コード（USD, JPY …） */
  country: string
  /** 画面に出す国名 */
  countryJa: string
  /** 発表時刻（ISO, UTC） */
  at: string
  impact: 'high' | 'mid'
  forecast: string
  previous: string
}

const SOURCES = [
  'https://nfs.faireconomy.media/ff_calendar_thisweek.json',
  'https://nfs.faireconomy.media/ff_calendar_nextweek.json',
]

const COUNTRY_JA: Record<string, string> = {
  USD: '米',
  JPY: '日本',
  EUR: '欧州',
  GBP: '英',
  AUD: '豪',
  NZD: 'NZ',
  CAD: 'カナダ',
  CHF: 'スイス',
  CNY: '中国',
  All: '',
}

/** よく出る指標の対訳。前方一致ではなく、含まれていれば置き換える */
const TITLE_JA: Array<[RegExp, string]> = [
  [/Non-Farm Employment Change/i, '雇用統計（非農業部門雇用者数）'],
  [/Unemployment Rate/i, '失業率'],
  [/Average Hourly Earnings/i, '平均時給'],
  [/Core CPI/i, 'コア消費者物価指数（コアCPI）'],
  [/^CPI/i, '消費者物価指数（CPI）'],
  [/Core PCE Price Index/i, 'コアPCE物価指数'],
  [/Core PPI/i, 'コア生産者物価指数'],
  [/^PPI/i, '生産者物価指数（PPI）'],
  [/Federal Funds Rate/i, 'FOMC 政策金利'],
  [/FOMC Statement/i, 'FOMC 声明'],
  [/FOMC Press Conference/i, 'FOMC 記者会見'],
  [/FOMC Meeting Minutes/i, 'FOMC 議事録'],
  [/Fed Chair Powell Speaks/i, 'パウエルFRB議長の発言'],
  [/BOJ Policy Rate/i, '日銀 政策金利'],
  [/BOJ Press Conference/i, '日銀総裁 記者会見'],
  [/BOJ Outlook Report/i, '日銀 展望レポート'],
  [/Monetary Policy Statement/i, '金融政策声明'],
  [/Main Refinancing Rate/i, 'ECB 政策金利'],
  [/ECB Press Conference/i, 'ECB 記者会見'],
  [/Official Bank Rate/i, '英中銀 政策金利'],
  [/Cash Rate/i, '政策金利'],
  [/Overnight Rate/i, '政策金利'],
  [/Advance GDP/i, 'GDP 速報値'],
  [/Prelim GDP/i, 'GDP 改定値'],
  [/Final GDP/i, 'GDP 確報値'],
  [/GDP/i, 'GDP'],
  [/Core Retail Sales/i, 'コア小売売上高'],
  [/Retail Sales/i, '小売売上高'],
  [/ISM Manufacturing PMI/i, 'ISM製造業景況指数'],
  [/ISM Services PMI/i, 'ISM非製造業景況指数'],
  [/Flash Manufacturing PMI/i, '製造業PMI 速報値'],
  [/Flash Services PMI/i, 'サービス業PMI 速報値'],
  [/Manufacturing PMI/i, '製造業PMI'],
  [/Services PMI/i, 'サービス業PMI'],
  [/JOLTS Job Openings/i, 'JOLTS 求人件数'],
  [/ADP Non-Farm Employment Change/i, 'ADP 雇用統計'],
  [/Unemployment Claims/i, '新規失業保険申請件数'],
  [/Consumer Confidence/i, '消費者信頼感指数'],
  [/Prelim UoM Consumer Sentiment/i, 'ミシガン大 消費者態度指数（速報）'],
  [/Revised UoM Consumer Sentiment/i, 'ミシガン大 消費者態度指数（確報）'],
  [/Building Permits/i, '建設許可件数'],
  [/Housing Starts/i, '住宅着工件数'],
  [/Existing Home Sales/i, '中古住宅販売件数'],
  [/New Home Sales/i, '新築住宅販売件数'],
  [/Durable Goods Orders/i, '耐久財受注'],
  [/Trade Balance/i, '貿易収支'],
  [/Current Account/i, '経常収支'],
  [/Industrial Production/i, '鉱工業生産'],
  [/Employment Change/i, '雇用者数変化'],
  [/Crude Oil Inventories/i, '原油在庫'],
  [/Tankan/i, '日銀短観'],
  [/Bank Holiday/i, '休場'],
  [/Speaks/i, 'の発言'],
]

function titleJa(title: string): string {
  for (const [re, ja] of TITLE_JA) {
    if (re.test(title)) {
      // 「〇〇 Speaks」は人名を残す
      if (ja === 'の発言') return title.replace(/\s*Speaks\s*$/i, '') + 'の発言'
      return ja
    }
  }
  return title
}

interface FfRow {
  title?: string
  country?: string
  date?: string
  impact?: string
  forecast?: string
  previous?: string
}

/** 直近に取れた値。元が落ちていても画面を止めない */
let lastGood: EconomicEvent[] | null = null
let lastAt = 0
const KEEP_MS = 30 * 60 * 1000

export async function fetchCalendar(): Promise<EconomicEvent[]> {
  if (lastGood && Date.now() - lastAt < KEEP_MS) return lastGood
  const rows: FfRow[] = []
  for (const src of SOURCES) {
    try {
      const res = await fetch(src, { headers: { accept: 'application/json' } })
      if (!res.ok) continue
      const data = (await res.json()) as unknown
      if (Array.isArray(data)) rows.push(...(data as FfRow[]))
    } catch {
      // 片方が落ちていても、取れたほうだけで続ける
    }
  }
  if (rows.length === 0) {
    if (lastGood) return lastGood
    throw new Error('calendar unavailable')
  }
  const out: EconomicEvent[] = []
  const seen = new Set<string>()
  for (const r of rows) {
    const impact = r.impact === 'High' ? 'high' : r.impact === 'Medium' ? 'mid' : null
    if (!impact || !r.title || !r.date) continue
    const t = new Date(r.date)
    if (Number.isNaN(t.getTime())) continue
    const country = r.country ?? ''
    const id = `${t.toISOString()}|${country}|${r.title}`
    if (seen.has(id)) continue
    seen.add(id)
    out.push({
      id,
      title: r.title,
      titleJa: titleJa(r.title),
      country,
      countryJa: COUNTRY_JA[country] ?? country,
      at: t.toISOString(),
      impact,
      forecast: r.forecast ?? '',
      previous: r.previous ?? '',
    })
  }
  out.sort((a, b) => a.at.localeCompare(b.at))
  lastGood = out
  lastAt = Date.now()
  return out
}

export async function handleCalendar(): Promise<{ status: number; body: unknown; maxAge: number }> {
  try {
    const events = await fetchCalendar()
    return { status: 200, body: { events, at: new Date().toISOString() }, maxAge: 900 }
  } catch (err) {
    return { status: 502, body: { error: err instanceof Error ? err.message : String(err) }, maxAge: 0 }
  }
}
