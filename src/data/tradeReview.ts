// MT5 から受け取った約定履歴を、そのまま「クセ」に読み替える。
//
// ここでやるのは集計と、そこから言える事実の指摘だけ。
// 「買いです」「上がります」の類は書かない（相場の予想はしない）。
import { formatSigned } from './setupFlow'

export interface Trade {
  id: number
  symbol: string
  side: 'buy' | 'sell'
  volume: number
  open_price: number
  close_price: number
  digits?: number
  profit: number
  opened_at: string
  closed_at: string
  held_sec: number
  by_system: boolean
}

export interface TradeHistory {
  days: number
  from?: string
  to?: string
  total: number
  truncated?: boolean
  trades: Trade[]
}

export interface Bucket {
  key: string
  label: string
  trades: number
  wins: number
  profit: number
}

/** 添削の1項目。tone は「できている」か「見直したい」の二択 */
export interface ReviewPoint {
  tone: 'good' | 'watch'
  title: string
  detail: string
}

export interface TradeReview {
  days: number
  count: number
  wins: number
  losses: number
  winRate: number | null
  profit: number
  avgWin: number
  avgLoss: number
  /** 平均利益 ÷ 平均損失。1未満なら「損大利小」 */
  payoff: number | null
  maxWinStreak: number
  maxLossStreak: number
  avgHoldWin: number
  avgHoldLoss: number
  maxVolume: number
  medianVolume: number
  bySymbol: Bucket[]
  byHour: Bucket[]
  byWeekday: Bucket[]
  system: Bucket | null
  manual: Bucket | null
  points: ReviewPoint[]
}

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土']

function median(values: number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function average(values: number[]): number {
  if (values.length === 0) return 0
  return values.reduce((a, b) => a + b, 0) / values.length
}

function bucketOf(map: Map<string, Bucket>, key: string, label: string): Bucket {
  let hit = map.get(key)
  if (!hit) {
    hit = { key, label, trades: 0, wins: 0, profit: 0 }
    map.set(key, hit)
  }
  return hit
}

function add(bucket: Bucket, trade: Trade): void {
  bucket.trades += 1
  if (trade.profit > 0) bucket.wins += 1
  bucket.profit = Math.round((bucket.profit + trade.profit) * 100) / 100
}

/** 保有時間を「3時間20分」のような言い方にする */
export function formatHeld(sec: number): string {
  if (!sec || sec < 0) return '—'
  if (sec < 60) return `${Math.round(sec)}秒`
  const minutes = Math.round(sec / 60)
  if (minutes < 60) return `${minutes}分`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours < 24) return rest ? `${hours}時間${rest}分` : `${hours}時間`
  const days = Math.floor(hours / 24)
  return `${days}日${hours % 24}時間`
}

export function reviewTrades(history: TradeHistory | undefined, currency?: string): TradeReview | null {
  const trades = history?.trades ?? []
  if (!history || trades.length === 0) return null

  const wins = trades.filter((t) => t.profit > 0)
  const losses = trades.filter((t) => t.profit < 0)
  const profit = Math.round(trades.reduce((sum, t) => sum + t.profit, 0) * 100) / 100
  const avgWin = Math.round(average(wins.map((t) => t.profit)) * 100) / 100
  const avgLoss = Math.round(Math.abs(average(losses.map((t) => t.profit))) * 100) / 100
  const payoff = avgLoss > 0 ? Math.round((avgWin / avgLoss) * 100) / 100 : null
  const winRate = trades.length ? Math.round((wins.length / trades.length) * 1000) / 10 : null

  // 連勝・連敗は「決済した順」に見る
  const ordered = [...trades].sort((a, b) => a.closed_at.localeCompare(b.closed_at))
  let maxWinStreak = 0
  let maxLossStreak = 0
  let runWin = 0
  let runLoss = 0
  for (const t of ordered) {
    if (t.profit > 0) {
      runWin += 1
      runLoss = 0
    } else if (t.profit < 0) {
      runLoss += 1
      runWin = 0
    }
    maxWinStreak = Math.max(maxWinStreak, runWin)
    maxLossStreak = Math.max(maxLossStreak, runLoss)
  }

  const symbolMap = new Map<string, Bucket>()
  const hourMap = new Map<string, Bucket>()
  const weekdayMap = new Map<string, Bucket>()
  const system: Bucket = { key: 'system', label: 'システム', trades: 0, wins: 0, profit: 0 }
  const manual: Bucket = { key: 'manual', label: '手動', trades: 0, wins: 0, profit: 0 }

  for (const t of trades) {
    add(bucketOf(symbolMap, t.symbol, t.symbol), t)
    const opened = new Date(t.opened_at)
    if (!Number.isNaN(opened.getTime())) {
      const hour = opened.getHours()
      add(bucketOf(hourMap, String(hour).padStart(2, '0'), `${hour}時台`), t)
      add(bucketOf(weekdayMap, String(opened.getDay()), `${WEEKDAYS[opened.getDay()]}曜`), t)
    }
    add(t.by_system ? system : manual, t)
  }

  const bySymbol = [...symbolMap.values()].sort((a, b) => b.trades - a.trades)
  const byHour = [...hourMap.values()].sort((a, b) => a.key.localeCompare(b.key))
  const byWeekday = [...weekdayMap.values()].sort((a, b) => Number(a.key) - Number(b.key))

  const volumes = trades.map((t) => t.volume)
  const maxVolume = Math.max(...volumes)
  const medianVolume = median(volumes)
  const avgHoldWin = Math.round(average(wins.map((t) => t.held_sec)))
  const avgHoldLoss = Math.round(average(losses.map((t) => t.held_sec)))

  const review: TradeReview = {
    days: history.days,
    count: trades.length,
    wins: wins.length,
    losses: losses.length,
    winRate,
    profit,
    avgWin,
    avgLoss,
    payoff,
    maxWinStreak,
    maxLossStreak,
    avgHoldWin,
    avgHoldLoss,
    maxVolume,
    medianVolume,
    bySymbol,
    byHour,
    byWeekday,
    system: system.trades ? system : null,
    manual: manual.trades ? manual : null,
    points: [],
  }
  review.points = buildPoints(review, currency)
  return review
}

/** 集計から言える事実だけを並べる。相場の予想はしない。 */
function buildPoints(r: TradeReview, currency?: string): ReviewPoint[] {
  const points: ReviewPoint[] = []
  const money = (n: number) => formatSigned(n, currency)

  // 損小利大になっているか
  if (r.payoff != null && r.avgWin > 0) {
    if (r.payoff >= 1.2) {
      points.push({
        tone: 'good',
        title: '利益のほうが損より大きい',
        detail: `平均の利益が ${money(r.avgWin)}、平均の損失が ${money(-r.avgLoss)} で、${r.payoff} 倍です。勝率が5割を切っても残る形になっています。`,
      })
    } else if (r.payoff < 0.8) {
      points.push({
        tone: 'watch',
        title: '利益より損のほうが大きい',
        detail: `平均の利益 ${money(r.avgWin)} に対して、平均の損失は ${money(-r.avgLoss)}。1回の負けを取り返すのに ${Math.ceil(r.avgLoss / Math.max(r.avgWin, 1))} 回勝つ必要があります。利益を伸ばす前に決済していないか、損切りの位置が遠すぎないかを見てください。`,
      })
    }
  }

  // 勝率と期待値の関係
  if (r.winRate != null && r.payoff != null) {
    if (r.winRate >= 60 && r.payoff < 0.6) {
      points.push({
        tone: 'watch',
        title: '勝率は高いのに、残っていない',
        detail: `勝率 ${r.winRate}% は高いほうですが、1回の負けが大きいので合計は ${money(r.profit)} です。「勝った回数」ではなく「1回あたりの幅」を見る癖をつけると変わります。`,
      })
    } else if (r.winRate < 40 && r.profit > 0) {
      points.push({
        tone: 'good',
        title: '勝率が低くても残っている',
        detail: `勝率 ${r.winRate}% でも合計は ${money(r.profit)}。当てにいくのではなく、伸ばすところで伸ばせています。`,
      })
    }
  }

  // 塩漬けの癖（負けを長く持っている）
  if (r.avgHoldLoss > 0 && r.avgHoldWin > 0 && r.avgHoldLoss > r.avgHoldWin * 1.5) {
    points.push({
      tone: 'watch',
      title: '負けているほうを長く持っている',
      detail: `勝ちトレードの保有が平均 ${formatHeld(r.avgHoldWin)}、負けトレードが ${formatHeld(r.avgHoldLoss)}。含み損が戻るのを待つ時間のほうが長い形です。決済の基準を、値段ではなく時間でも決めておくと崩れにくくなります。`,
    })
  } else if (r.avgHoldWin > r.avgHoldLoss && r.avgHoldLoss > 0) {
    points.push({
      tone: 'good',
      title: '損切りが早い',
      detail: `負けたときの保有が平均 ${formatHeld(r.avgHoldLoss)}、勝ったときが ${formatHeld(r.avgHoldWin)}。だめなほうを先に切れています。`,
    })
  }

  // ロットのばらつき（ムキになっていないか）
  if (r.medianVolume > 0 && r.maxVolume >= r.medianVolume * 3) {
    points.push({
      tone: 'watch',
      title: 'ロットが一定でない',
      detail: `ふだんは ${r.medianVolume} ロットですが、最大で ${r.maxVolume} ロットまで上げた場面があります。負けたあとに枚数を上げると、1回で流れが決まってしまいます。`,
    })
  } else if (r.medianVolume > 0) {
    points.push({
      tone: 'good',
      title: 'ロットが揃っている',
      detail: `だいたい ${r.medianVolume} ロットで統一されています。1回の取引が全体に与える影響が読める状態です。`,
    })
  }

  // 連敗
  if (r.maxLossStreak >= 5) {
    points.push({
      tone: 'watch',
      title: `${r.maxLossStreak} 連敗があった`,
      detail: '連敗そのものは避けられませんが、連敗中に枚数や回数が増えていないかは見ておきたいところです。',
    })
  }

  // 銘柄のかたより
  const worst = [...r.bySymbol].sort((a, b) => a.profit - b.profit)[0]
  const best = [...r.bySymbol].sort((a, b) => b.profit - a.profit)[0]
  if (r.bySymbol.length > 1 && worst && worst.profit < 0 && worst.trades >= 3) {
    points.push({
      tone: 'watch',
      title: `${worst.key} で負けが集中している`,
      detail: `${worst.key} は ${worst.trades} 回で ${money(worst.profit)}。ほかの銘柄と同じやり方が合っていない可能性があります。`,
    })
  }
  if (best && best.profit > 0 && best.trades >= 3) {
    points.push({
      tone: 'good',
      title: `${best.key} は相性がいい`,
      detail: `${best.key} は ${best.trades} 回で ${money(best.profit)}。得意な形がはっきりしています。`,
    })
  }

  // 時間帯のかたより
  const hourLoss = [...r.byHour].filter((b) => b.trades >= 3).sort((a, b) => a.profit - b.profit)[0]
  if (hourLoss && hourLoss.profit < 0) {
    points.push({
      tone: 'watch',
      title: `${hourLoss.label}の成績が悪い`,
      detail: `${hourLoss.label}に建てた ${hourLoss.trades} 回で ${money(hourLoss.profit)}。この時間を避けるだけで形が変わることがあります。`,
    })
  }

  // システムと手動の差（どちらも負けているときに「勝っている」とは言わない）
  if (r.system && r.manual && r.system.trades >= 3 && r.manual.trades >= 3) {
    const diff = r.system.profit - r.manual.profit
    const both = `システム ${r.system.trades} 回で ${money(r.system.profit)}、手動 ${r.manual.trades} 回で ${money(r.manual.profit)} です。`
    if (r.system.profit > 0 && r.manual.profit <= 0) {
      points.push({ tone: 'good', title: 'システムのほうが残っている', detail: both })
    } else if (r.manual.profit > 0 && r.system.profit <= 0) {
      points.push({ tone: 'watch', title: '手動のほうが残っている', detail: `${both}システムの設定を見直す余地があります。` })
    } else {
      points.push({
        tone: 'watch',
        title: 'システムと手動の差',
        detail: `${both}${diff >= 0 ? 'システム' : '手動'}のほうが ${money(Math.abs(diff))} ぶん良い形です。`,
      })
    }
  }

  return points
}

export function formatReviewAnswer(r: TradeReview | null, currency?: string): string {
  if (!r) return '添削できる履歴がまだありません。決済が何回か終わってから、もう一度お声がけください。'
  const watch = r.points.filter((p) => p.tone === 'watch').length
  const head =
    `過去${r.days}日の${r.count}回を見ました。勝率 ${r.winRate ?? 0}%、合計 ${formatSigned(r.profit, currency)}、` +
    `1回の平均は勝ち ${formatSigned(r.avgWin, currency)} ／ 負け ${formatSigned(-r.avgLoss, currency)} です。`
  const tail = watch
    ? `気になったところが${watch}点あります。下に並べましたので、上から順に見ていきましょう。`
    : '大きく崩れているところはありません。いまの形を続けてください。'
  return `${head}${tail}`
}
