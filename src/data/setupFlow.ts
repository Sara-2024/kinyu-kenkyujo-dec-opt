// 自動売買の接続フロー。工程の結果はブリッジが返した実データだけを使う。

export interface UserStep {
  no: number
  title: string
  detail: string
}

export const USER_STEPS: UserStep[] = [
  { no: 1, title: 'メールを受け取る', detail: '接続ツールのリンクをお送りします' },
  { no: 2, title: 'ツールを起動する', detail: 'ダウンロードして開くだけです' },
  { no: 3, title: 'MT5にログインする', detail: 'いつも通り、MT5の画面で口座に入るだけです' },
]

export const CONNECT_WAIT = 'MT5の状態を読み取っています'

export interface ConnectCheck {
  working: string
  done: string
  ok: boolean
}

export interface TodayStats {
  today_closed?: number
  today_profit?: number
  today_wins?: number
  today_losses?: number
  open_positions?: number
  open_profit?: number
}

/** 接続工程に必要な、ブリッジが返す実フィールド */
export interface ConnectStatus {
  mt5_ready?: boolean
  account?: number | string | null
  server?: string | null
  build?: number | null
  terminal_name?: string | null
  ea_installed?: boolean
  ea_found?: string[]
  ea_compiled?: string[]
  value?: number | null
  today?: TodayStats
  currency?: string
}

export function connectChecksFromStatus(s: ConnectStatus): ConnectCheck[] {
  const account = s.account != null && String(s.account) !== '' ? String(s.account) : ''
  const server = s.server ? String(s.server) : ''
  const build = s.build != null ? `build ${s.build}` : ''
  const name = s.terminal_name ? String(s.terminal_name) : ''
  const found = s.ea_found ?? []
  const compiled = s.ea_compiled ?? []
  const installed = Boolean(s.ea_installed)
  const gateOk = typeof s.value === 'number'

  return [
    {
      working: '接続ツールを確認しています',
      done: s.mt5_ready
        ? `MT5に接続しました${name ? `（${name}）` : ''}${build ? ` ${build}` : ''}`
        : 'MT5に接続できませんでした',
      ok: Boolean(s.mt5_ready),
    },
    {
      working: '口座情報を読み取っています',
      done: account ? `口座 ${account}${server ? ` ／ ${server}` : ''}` : '口座情報を読み取れませんでした',
      ok: Boolean(account),
    },
    {
      working: 'Experts フォルダを確認しています',
      done: installed
        ? compiled.length > 0
          ? `システムを確認しました（${compiled.join(', ')}）`
          : `ソースを確認しました（${found.join(', ')}）。MetaEditor でコンパイルしてください`
        : 'Experts にシステムが見つかりません。接続ツールを起動するか、チャートへドラッグしてください',
      ok: installed,
    },
    {
      working: '停止スイッチを確認しています',
      done: gateOk
        ? Number(s.value) !== 0
          ? '停止スイッチは届いています（稼働許可）'
          : '停止スイッチは届いています（停止中）'
        : '停止スイッチの状態を確認できませんでした',
      ok: gateOk,
    },
  ]
}

function formatSigned(n: number, currency?: string): string {
  const body = n.toLocaleString('ja-JP', { maximumFractionDigits: 2, minimumFractionDigits: 0 })
  const signed = n > 0 ? `+${body}` : body
  return currency ? `${signed} ${currency}` : signed
}

export function formatTodayAnswer(s: ConnectStatus): string {
  const t = s.today
  if (!t) return '口座の実績を読み取れませんでした。'
  const cur = s.currency
  const closed = t.today_closed ?? 0
  const open = t.open_positions ?? 0
  if (closed === 0 && open === 0) {
    return '本日ここまで、決済も建玉もありません。数字は口座の実績をそのまま出しています。'
  }
  return (
    `本日ここまで、決済は${closed}回、損益は ${formatSigned(t.today_profit ?? 0, cur)} です。` +
    `勝ち${t.today_wins ?? 0}・負け${t.today_losses ?? 0}。` +
    `建玉は${open}件（含み損益 ${formatSigned(t.open_profit ?? 0, cur)}）です。` +
    '数字は口座の実績をそのまま出しています。'
  )
}

export function validateEmail(value: string): string | null {
  const s = value.trim()
  if (!s) return 'メールアドレスを入力してください'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s)) return 'メールアドレスの形式を確認してください'
  return null
}
