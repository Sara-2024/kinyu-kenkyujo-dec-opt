// /api/risk の検証まわりを、偽の Gemini を立てて確かめる。
import { createServer } from 'node:http'
import { handleRisk, checkEvidence, applyGuards } from './risk.ts'

let reply = {}
const fake = createServer((req, res) => {
  let body = ''
  req.on('data', (c) => (body += c))
  req.on('end', () => {
    res.setHeader('content-type', 'application/json')
    if (reply.status && reply.status !== 200) {
      res.statusCode = reply.status
      res.end(JSON.stringify({ error: { message: 'nope' } }))
      return
    }
    res.end(
      JSON.stringify({
        candidates: [{ content: { parts: [{ text: reply.raw ?? JSON.stringify(reply.body) }] } }],
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
const req = {
  bridge_id: 'test-room',
  seq: 7,
  account: 221520,
  account_mode: 'demo',
  symbol: 'XAUUSD',
  server_time: '2026-09-09T07:00:00',
  bar_time: 1757400000,
  strategy_profile: { name: 'Orbit', ema_period: 200 },
  features,
}
const env = { geminiKey: 'x', geminiBase: base, model: 'gemini-3.5-flash', bridgeToken: 'secret' }

let pass = 0
let fail = 0
const check = (name, cond, extra = '') => {
  if (cond) {
    pass++
    console.log(`  ok   ${name}`)
  } else {
    fail++
    console.log(`  NG   ${name} ${extra}`)
  }
}

// 1) 素直な買い停止（根拠あり・方向どおり）
reply = {
  body: {
    buy_assessment: 'BLOCK',
    sell_assessment: 'ALLOW',
    buy_reason_codes: ['NEAR_RESISTANCE', 'BREAKOUT_UNCONFIRMED'],
    sell_reason_codes: [],
    evidence: [
      { field: 'dist_to_resistance_atr', value: '0.92', why: '直上の高値まで ATR 1個未満' },
      { field: 'resistance_retest_confirmed', value: '0', why: '突破もリテストも未成立' },
    ],
    summary: '直上の高値が近いので、買いの新規だけ見送ります。',
  },
}
let r = await handleRisk(req, env, 'secret')
check('買いだけ停止できる', r.status === 200 && r.body.decision.buy === 'BLOCK' && r.body.decision.sell === 'ALLOW', JSON.stringify(r.body).slice(0, 200))
check('期限と口座はバックエンドが付ける', !!r.body.decision.expires_at && r.body.decision.account === 221520 && r.body.decision.seq === 7)
check('モデルとプロンプト版が入る', r.body.decision.model === 'gemini-3.5-flash' && !!r.body.decision.prompt_version)

// 2) 入力に無い項目を根拠にした停止は採用しない
reply = {
  body: {
    buy_assessment: 'BLOCK',
    sell_assessment: 'ALLOW',
    buy_reason_codes: ['NEAR_RESISTANCE'],
    sell_reason_codes: [],
    evidence: [{ field: 'rsi_14', value: '78', why: '買われすぎ' }],
    summary: 'RSIが高いので見送り',
  },
}
r = await handleRisk(req, env, 'secret')
check('存在しない項目の根拠は捨てる', r.body.decision.buy === 'ALLOW' && r.body.decision.dropped.some((d) => d.includes('rsi_14')))

// 3) 値をすり替えた根拠は採用しない
reply = {
  body: {
    buy_assessment: 'BLOCK',
    sell_assessment: 'ALLOW',
    buy_reason_codes: ['NEAR_RESISTANCE'],
    sell_reason_codes: [],
    evidence: [{ field: 'dist_to_resistance_atr', value: '0.05', why: 'ほぼ接触' }],
    summary: '接触寸前',
  },
}
r = await handleRisk(req, env, 'secret')
check('値が違う根拠は捨てる', r.body.decision.buy === 'ALLOW' && r.body.decision.dropped.some((d) => d.includes('dist_to_resistance_atr')))

// 4) 方向違いの理由コードは通さない（安値が近いことを理由に買いを止めない）
reply = {
  body: {
    buy_assessment: 'BLOCK',
    sell_assessment: 'ALLOW',
    buy_reason_codes: ['NEAR_SUPPORT'],
    sell_reason_codes: [],
    evidence: [{ field: 'dist_to_support_atr', value: '14.2', why: '安値が近い' }],
    summary: '安値が近い',
  },
}
r = await handleRisk(req, env, 'secret')
check('買いに売り用コードは使えない', r.body.decision.buy === 'ALLOW' && r.body.decision.dropped.some((d) => d.includes('NEAR_SUPPORT')))

// 5) 売りだけ停止
reply = {
  body: {
    buy_assessment: 'ALLOW',
    sell_assessment: 'BLOCK',
    buy_reason_codes: [],
    sell_reason_codes: ['NEAR_SUPPORT'],
    evidence: [{ field: 'nearest_support', value: '3310.1', why: '直下の安値が近い' }],
    summary: '直下の安値が近いので売りだけ見送り',
  },
}
r = await handleRisk(req, env, 'secret')
check('売りだけ停止できる', r.body.decision.sell === 'BLOCK' && r.body.decision.buy === 'ALLOW')

// 6) 材料不足
reply = {
  body: {
    buy_assessment: 'INSUFFICIENT_DATA',
    sell_assessment: 'INSUFFICIENT_DATA',
    buy_reason_codes: [],
    sell_reason_codes: [],
    evidence: [],
    summary: '判断材料が足りません',
  },
}
r = await handleRisk(req, env, 'secret')
check('材料不足はそのまま返る', r.body.decision.buy === 'INSUFFICIENT_DATA')

// 7) 壊れた JSON
reply = { raw: 'これはJSONではありません' }
r = await handleRisk(req, env, 'secret')
check('壊れた応答は502', r.status === 502, JSON.stringify(r.body))

// 8) Gemini が 500
reply = { status: 500 }
r = await handleRisk(req, env, 'secret')
check('AI側の障害は502', r.status === 502)

// 9) 合言葉
reply = { body: { buy_assessment: 'ALLOW', sell_assessment: 'ALLOW', buy_reason_codes: [], sell_reason_codes: [], evidence: [], summary: 'ok' } }
r = await handleRisk(req, env, 'wrong')
check('合言葉が違えば401', r.status === 401)
r = await handleRisk(req, { ...env, bridgeToken: '' }, '')
check('合言葉未設定なら動かさない', r.status === 503)
r = await handleRisk({ ...req, features: {} }, env, 'secret')
check('データが薄すぎる依頼は400', r.status === 400)

// 10) 純粋関数の単体
const ev = checkEvidence([{ field: 'atr_m1', value: 0.73, why: 'x' }, { field: 'nope', value: 1, why: 'y' }], features)
check('checkEvidence が未知項目を落とす', ev.kept.length === 1 && ev.dropped.length === 1)
const g = applyGuards({ buy: 'BLOCK', sell: 'ALLOW', buyCodes: ['NEAR_RESISTANCE'], sellCodes: [] }, [])
check('根拠ゼロの停止は成立しない', g.buy === 'ALLOW')

fake.close()
console.log(`\n${pass} ok / ${fail} NG`)
process.exit(fail ? 1 : 0)
