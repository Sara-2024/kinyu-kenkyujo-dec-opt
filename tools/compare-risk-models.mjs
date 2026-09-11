// 判定の突き合わせ。安いモデルに替えてよいかを、勘ではなく実データで決めるための道具。
//
//   お客様のPCに溜まった判定の記録（risk_decisions.jsonl）を読み、
//   同じ場面をそのまま別のモデルに見せ直して、止める／止めないが一致するかを数える。
//
// 使い方:
//   node --experimental-strip-types tools/compare-risk-models.mjs <risk_decisions.jsonl> \
//     --models gemini-3.5-flash-lite,deepseek:deepseek-flash \
//     --limit 200 --out hikaku.md
//
//   鍵は環境変数から読む（GEMINI_API_KEY / GEMINI_RISK_API_KEY / DEEPSEEK_API_KEY）。
//   --dry-run を付けると、AI を呼ばずに記録の中身だけ確かめる。
//
// 記録の場所（お客様のPC）:
//   %LOCALAPPDATA%\AITrader\risk_decisions.jsonl
//
// 大事な読み方:
//   * 「記録」は本番でいま使っているモデルの判定。これを正解ではなく **基準** として比べる。
//   * 見たいのは一致率そのものより **「記録が止めた場面を、候補が通してしまった数」**（＝見逃し）。
//     ここが増えるモデルには替えない。逆向き（余計に止める）は機会損失で、許容度は運用判断。
import { readFile, writeFile } from 'node:fs/promises'
import { handleRisk } from '../api/_lib/risk.ts'

// 100万トークンあたりの単価（2026-09-10 時点の各社の料金表）。
// 変わっていることがあるので、金額を根拠に決めるときは必ず最新を確認すること。
const PRICES = {
  'gemini-3.5-flash': { in: 1.5, out: 9.0 },
  'gemini-3.5-flash-lite': { in: 0.3, out: 2.5 },
  'gemini-3.1-flash-lite': { in: 0.25, out: 1.5 },
  'deepseek-flash': { in: 0.15, out: 0.6 }, // 協定時間帯（平日 01-04, 06-10 UTC）は倍
}

const TOKEN = 'compare-tool'

function parseArgs(argv) {
  const args = { models: [], limit: 0, concurrency: 4, out: '', dryRun: false, file: '' }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--models') args.models = String(argv[++i] ?? '').split(',').map((s) => s.trim()).filter(Boolean)
    else if (a === '--limit') args.limit = Number(argv[++i]) || 0
    else if (a === '--concurrency') args.concurrency = Math.max(1, Number(argv[++i]) || 4)
    else if (a === '--out') args.out = String(argv[++i] ?? '')
    else if (a === '--dry-run') args.dryRun = true
    else if (!a.startsWith('--') && !args.file) args.file = a
  }
  return args
}

/** "deepseek:deepseek-flash" / "gemini-3.5-flash-lite" を、handleRisk に渡す環境に変える */
function envForModel(spec) {
  const [head, tail] = spec.includes(':') ? spec.split(':', 2) : ['gemini', spec]
  const provider = head === 'deepseek' ? 'deepseek' : 'gemini'
  const model = provider === 'deepseek' ? tail || 'deepseek-flash' : spec.startsWith('gemini:') ? tail : spec
  if (provider === 'deepseek') {
    const key = (process.env.DEEPSEEK_API_KEY || '').trim()
    if (!key) throw new Error(`${spec}: DEEPSEEK_API_KEY がありません`)
    return {
      label: model,
      env: {
        provider,
        deepseekKey: key,
        deepseekModel: model,
        deepseekBase: (process.env.DEEPSEEK_BASE_URL || '').trim() || undefined,
        bridgeToken: TOKEN,
      },
    }
  }
  const key = (process.env.GEMINI_RISK_API_KEY || process.env.GEMINI_API_KEY || '').trim()
  if (!key) throw new Error(`${spec}: GEMINI_API_KEY がありません`)
  return {
    label: model,
    env: {
      provider,
      geminiKey: key,
      model,
      geminiBase: (process.env.GEMINI_BASE_URL || '').trim() || undefined,
      bridgeToken: TOKEN,
    },
  }
}

/** 記録の1行を、そのときサイトへ送られたのと同じ問い合わせに戻す */
function toRequest(row, index) {
  return {
    bridge_id: `compare-${index}`,
    seq: Number(row.seq) || index,
    account: 0,
    account_mode: row.account_mode ?? 'demo',
    symbol: row.symbol || 'XAUUSD',
    server_time: row.server_time || row.at,
    bar_time: Number(row.bar_time) || 0,
    strategy_profile: row.strategy_profile,
    features: row.features,
  }
}

/** 問い合わせを作り直せる行だけを残す（古い版の記録には材料が足りない） */
function usable(row) {
  if (!row || typeof row !== 'object') return '行がJSONではない'
  if (!row.features || typeof row.features !== 'object') return 'features が無い'
  if (Object.keys(row.features).length < 5) return 'features が薄い'
  if (!row.strategy_profile || typeof row.strategy_profile !== 'object') {
    return 'strategy_profile が無い（このツールを入れる前の記録）'
  }
  if (!row.buy || !row.sell) return '記録側の判定が無い'
  return ''
}

async function mapWithLimit(items, limit, fn) {
  const out = new Array(items.length)
  let next = 0
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (true) {
      const i = next++
      if (i >= items.length) return
      out[i] = await fn(items[i], i)
    }
  })
  await Promise.all(workers)
  return out
}

function blankTally() {
  return {
    ok: 0,
    failed: 0,
    agree: { buy: 0, sell: 0 },
    // 記録が止めた場面を通した＝見逃し。ここが増えるモデルには替えない
    missed: { buy: 0, sell: 0 },
    // 記録が通した場面を止めた＝余計な停止（機会損失）
    extra: { buy: 0, sell: 0 },
    // 記録が止めていて候補も止めたが、理由コードが違う
    reasonDiff: 0,
    usage: { input: 0, output: 0, calls: 0 },
    samples: [],
  }
}

function compareSide(tally, side, recorded, got) {
  const wasBlock = recorded === 'BLOCK'
  const isBlock = got === 'BLOCK'
  if (wasBlock === isBlock) tally.agree[side]++
  else if (wasBlock && !isBlock) tally.missed[side]++
  else tally.extra[side]++
}

function pct(n, d) {
  return d === 0 ? '—' : `${((n / d) * 100).toFixed(1)}%`
}

function costPer1k(tally, model) {
  const price = PRICES[model]
  if (!price || tally.usage.calls === 0) return '—'
  const perCall = (tally.usage.input / tally.usage.calls) * (price.in / 1e6)
    + (tally.usage.output / tally.usage.calls) * (price.out / 1e6)
  return `$${(perCall * 1000).toFixed(2)}`
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  if (!args.file) {
    console.error('使い方: node --experimental-strip-types tools/compare-risk-models.mjs <risk_decisions.jsonl> --models gemini-3.5-flash-lite,deepseek:deepseek-flash')
    process.exit(2)
  }

  const text = await readFile(args.file, 'utf8')
  const rows = []
  const skipped = new Map()
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    let row
    try {
      row = JSON.parse(line)
    } catch {
      skipped.set('JSONとして読めない行', (skipped.get('JSONとして読めない行') ?? 0) + 1)
      continue
    }
    const why = usable(row)
    if (why) {
      skipped.set(why, (skipped.get(why) ?? 0) + 1)
      continue
    }
    rows.push(row)
  }
  const target = args.limit > 0 ? rows.slice(0, args.limit) : rows

  console.log(`読めた記録: ${rows.length} 件（比べるのは ${target.length} 件）`)
  for (const [why, n] of skipped) console.log(`  とばした: ${why} … ${n} 件`)
  const baseModels = new Set(target.map((r) => r.model).filter(Boolean))
  console.log(`記録側のモデル: ${[...baseModels].join(', ') || '不明'}`)
  const blocked = target.filter((r) => r.buy === 'BLOCK' || r.sell === 'BLOCK').length
  console.log(`うち、記録が止めた場面: ${blocked} 件（${pct(blocked, target.length)}）`)
  if (blocked === 0) {
    console.log('⚠ 止めた場面が1件も無い記録です。見逃しを比べられないので、期間を広げて集め直してください。')
  }
  if (args.dryRun || args.models.length === 0) {
    if (!args.dryRun) console.log('\n--models が指定されていないので、記録の確認だけで終わります。')
    return
  }

  const targets = args.models.map(envForModel)
  const results = new Map(targets.map((t) => [t.label, blankTally()]))

  for (const t of targets) {
    const tally = results.get(t.label)
    process.stdout.write(`\n${t.label} に同じ場面を見せています`)
    await mapWithLimit(target, args.concurrency, async (row, i) => {
      let res
      try {
        res = await handleRisk(toRequest(row, i), t.env, TOKEN)
      } catch (err) {
        tally.failed++
        return
      }
      if (res.status !== 200 || !res.body?.decision) {
        tally.failed++
        if (tally.samples.length < 3) tally.samples.push({ kind: 'error', detail: JSON.stringify(res.body).slice(0, 160) })
        return
      }
      tally.ok++
      const got = res.body.decision
      if (res.body.usage) {
        tally.usage.input += Number(res.body.usage.input) || 0
        tally.usage.output += Number(res.body.usage.output) || 0
        tally.usage.calls++
      }
      compareSide(tally, 'buy', row.buy, got.buy)
      compareSide(tally, 'sell', row.sell, got.sell)
      const sameBlock = row.buy === got.buy && row.sell === got.sell
      if (sameBlock && JSON.stringify(row.reason_codes ?? {}) !== JSON.stringify(got.reason_codes ?? {})) {
        tally.reasonDiff++
      }
      const missed = (row.buy === 'BLOCK' && got.buy !== 'BLOCK') || (row.sell === 'BLOCK' && got.sell !== 'BLOCK')
      if (missed && tally.samples.length < 8) {
        tally.samples.push({
          kind: 'missed',
          at: row.at,
          recorded: `買い=${row.buy} 売り=${row.sell} / ${row.summary ?? ''}`,
          got: `買い=${got.buy} 売り=${got.sell} / ${got.summary ?? ''}`,
        })
      }
      if (tally.ok % 20 === 0) process.stdout.write('.')
    })
    process.stdout.write('\n')
  }

  const lines = []
  const say = (s = '') => {
    lines.push(s)
    console.log(s)
  }

  say('')
  say(`# 判定の突き合わせ（${target.length} 件）`)
  say('')
  say(`記録側（いまの本番）: ${[...baseModels].join(', ') || '不明'} ／ 止めた場面 ${blocked} 件`)
  say('')
  say('| 候補モデル | 判定できた | 一致(買い) | 一致(売り) | **見逃し** | 余計に停止 | 理由コード違い | 1000回あたり |')
  say('| --- | --- | --- | --- | --- | --- | --- | --- |')
  for (const t of targets) {
    const x = results.get(t.label)
    const missed = x.missed.buy + x.missed.sell
    const extra = x.extra.buy + x.extra.sell
    say(
      `| ${t.label} | ${x.ok}/${x.ok + x.failed} | ${pct(x.agree.buy, x.ok)} | ${pct(x.agree.sell, x.ok)} `
      + `| **${missed}** | ${extra} | ${x.reasonDiff} | ${costPer1k(x, t.label)} |`,
    )
  }
  say('')
  say('「見逃し」= 記録が止めた場面を、候補モデルが通した数。**ここが 0 でないモデルには替えない。**')
  say('「余計に停止」= 記録が通した場面を候補が止めた数。安全側だが機会損失になる。')

  for (const t of targets) {
    const x = results.get(t.label)
    if (x.samples.length === 0) continue
    say('')
    say(`## ${t.label} で食い違った場面`)
    for (const s of x.samples) {
      if (s.kind === 'error') say(`- 失敗: ${s.detail}`)
      else {
        say(`- ${s.at}`)
        say(`  - 記録: ${s.recorded}`)
        say(`  - 候補: ${s.got}`)
      }
    }
  }

  if (args.out) {
    await writeFile(args.out, lines.join('\n') + '\n', 'utf8')
    console.log(`\n${args.out} に書きました`)
  }
}

await main()
