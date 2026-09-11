// tools/compare-risk-models.mjs の通し試験。偽の Gemini を立てて、実際に走らせる。
// 鍵も MT5 も要らない:  node --experimental-strip-types tools/tests/compare_risk_models_test.mjs
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { mkdtemp, writeFile, readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const tool = join(here, '..', 'compare-risk-models.mjs')

let pass = 0
let fail = 0
function check(name, ok, detail = '') {
  if (ok) {
    pass++
    console.log(`  ok   ${name}`)
  } else {
    fail++
    console.log(`  NG   ${name}${detail ? `  … ${detail}` : ''}`)
  }
}

// 何を聞かれても「両方とも通してよい」と答える偽モデル。
// 記録側は買いを止めているので、突き合わせでは「見逃し」に数えられるはず。
let seenModels = []
const fake = createServer((req, res) => {
  seenModels.push(req.url.split('/models/')[1]?.split(':')[0])
  let body = ''
  req.on('data', (c) => (body += c))
  req.on('end', () => {
    res.setHeader('content-type', 'application/json')
    res.end(
      JSON.stringify({
        candidates: [
          {
            content: {
              parts: [
                {
                  text: JSON.stringify({
                    buy_assessment: 'ALLOW',
                    sell_assessment: 'ALLOW',
                    buy_reason_codes: [],
                    sell_reason_codes: [],
                    evidence: [],
                    summary: '問題なし',
                  }),
                },
              ],
            },
          },
        ],
        usageMetadata: { promptTokenCount: 1500, candidatesTokenCount: 200 },
      }),
    )
  })
})
await new Promise((r) => fake.listen(0, r))
const base = `http://127.0.0.1:${fake.address().port}/v1beta`

const features = {
  price_mid: 3320.5,
  atr_m1: 0.73,
  nearest_resistance: 3321.17,
  nearest_resistance_name: 'swing_h1_high',
  dist_to_resistance_atr: 0.92,
  nearest_support: 3310.1,
  dist_to_support_atr: 14.2,
  resistance_retest_confirmed: 0,
  move_m1_15bars_atr: 2.8,
}
const profile = { name: 'Orbit', ema_period: 200, retest_bars: 6 }

// 記録の1行（bridge/risk_gate.py の _record が書く形）
const blockRow = {
  at: '2026-09-09T16:00:00',
  seq: 7,
  mode: '反映',
  enforced: true,
  buy: 'BLOCK',
  sell: 'ALLOW',
  reason_codes: { buy: ['NEAR_RESISTANCE'], sell: [] },
  summary: '高値が近い',
  evidence: [{ field: 'dist_to_resistance_atr', value: 0.92, why: '近い' }],
  model: 'gemini-3.5-flash',
  bar_time: 1757400000,
  symbol: 'XAUUSD',
  account_mode: 'demo',
  server_time: '2026-09-09T07:00:00',
  strategy_profile: profile,
  features,
}
const allowRow = { ...blockRow, at: '2026-09-09T16:02:00', seq: 8, buy: 'ALLOW', reason_codes: { buy: [], sell: [] } }
// このツールを入れる前の記録（strategy_profile が無い）。とばされるはず
const oldRow = { at: '2026-09-08T10:00:00', seq: 1, buy: 'ALLOW', sell: 'ALLOW', features }

const dir = await mkdtemp(join(tmpdir(), 'risk-compare-'))
const log = join(dir, 'risk_decisions.jsonl')
await writeFile(log, [blockRow, allowRow, oldRow].map((r) => JSON.stringify(r)).join('\n') + '\n', 'utf8')

function run(args, env = {}) {
  return new Promise((resolve) => {
    const p = spawn(process.execPath, ['--experimental-strip-types', tool, ...args], {
      env: { ...process.env, ...env },
    })
    let out = ''
    p.stdout.on('data', (c) => (out += c))
    p.stderr.on('data', (c) => (out += c))
    p.on('close', (code) => resolve({ code, out }))
  })
}

// ── 1. 材料の足りない古い記録はとばす ──
const dry = await run([log, '--dry-run'])
check('材料の足りない古い記録はとばす', dry.out.includes('strategy_profile が無い'), dry.out.slice(-300))
check('読めた件数を出す', /読めた記録: 2 件/.test(dry.out), dry.out.slice(0, 200))
check('記録が止めた場面の数を出す', /記録が止めた場面: 1 件/.test(dry.out), dry.out.slice(0, 300))
check('AI を呼ばない（--dry-run）', seenModels.length === 0, seenModels.join(','))

// ── 2. 実際に突き合わせる ──
const outFile = join(dir, 'hikaku.md')
const res = await run([log, '--models', 'gemini-3.5-flash-lite', '--out', outFile], {
  GEMINI_API_KEY: 'test-key',
  GEMINI_BASE_URL: base,
})
check('終了コードは0', res.code === 0, res.out.slice(-400))
check('指定したモデルに聞きにいく', seenModels.every((m) => m === 'gemini-3.5-flash-lite'), seenModels.join(','))
check('記録の件数ぶん聞く', seenModels.length === 2, String(seenModels.length))

const report = await readFile(outFile, 'utf8')
check('報告ファイルを書く', report.includes('判定の突き合わせ'), report.slice(0, 120))
// 記録は「買いを止めた」、偽モデルは「通す」。見逃し1件として数えられていること
check('記録が止めた場面を通したら見逃しに数える', /\| \*\*1\*\* \|/.test(report), report)
check('食い違った場面を並べる', report.includes('で食い違った場面') && report.includes('高値が近い'), report.slice(-400))
// 申告されたトークン数から実費を出せていること（1500in/200out・Flash-Lite の単価）
check('実測トークンから1000回あたりの費用を出す', /\$\d+\.\d\d \|/.test(report), report)

fake.close()
console.log(`\n${pass} ok / ${fail} NG`)
process.exit(fail ? 1 : 0)
