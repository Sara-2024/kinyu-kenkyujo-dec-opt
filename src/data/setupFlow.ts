// 自動売買の接続フロー。工程の結果はブリッジが返した実データだけを使う。

export interface UserStep {
  no: number
  title: string
  detail: string
  /** 押す場所を示す絵（署名の無いプログラムなので Windows / Mac が確認を出す） */
  figure?: 'browserWarning' | 'smartScreen' | 'macNotOpened' | 'macOpenAnyway'
}

/**
 * ダウンロードしたあと、お客様にしていただくこと。
 * exe（1本にまとめた版）は「開くだけ」。zip はいったん展開して はじめる.bat を開く。
 * Mac は署名が無いので、macOS 15 以降は「システム設定 → このまま開く」を一度だけ通す
 * （右クリック→開く は macOS 14 までの通し方。15 からは出てこない）。
 */
export function installSteps(kind: 'exe' | 'zip' | 'mac'): UserStep[] {
  if (kind === 'mac') {
    return [
      {
        no: 1,
        title: 'ダウンロードした ZIP を開く',
        detail: 'ダウンロード欄の「DreamlandPassport-mac.zip」をクリック（Safari は自動で展開されます）。「ドリームランド・パスポート」が出ます',
      },
      {
        no: 2,
        title: '「ドリームランド・パスポート」をダブルクリック → 「完了」',
        detail: '「開けません」「Apple は確認できませんでした」と出たら「完了」を押します。「ゴミ箱に入れる」は押さないでください',
        figure: 'macNotOpened',
      },
      {
        no: 3,
        title: 'システム設定 →「このまま開く」',
        detail:
          '画面左上の  →「システム設定」→ 左の「プライバシーとセキュリティ」→ 下へスクロール →「"ドリームランド・パスポート" は Mac を保護するためにブロックされました」の「このまま開く」→ Mac のパスワード（または Touch ID）→ もう一度「このまま開く」。これは初回だけです。macOS 14 以前は、右クリック →「開く」→「開く」で通ります',
        figure: 'macOpenAnyway',
      },
      { no: 4, title: 'ログインした MT5 を、このパソコンで開いておく', detail: '口座にログインした MT5 を、この画面を開いているのと同じパソコンで開いたままにしてください（最小化していても大丈夫です）' },
      { no: 5, title: 'あとは待つだけ', detail: 'ツールが起動すると、この画面が自動で先へ進みます' },
    ]
  }
  if (kind === 'exe') {
    return [
      {
        no: 1,
        title: 'ブラウザの警告が出たら「保存」',
        detail:
          '「一般的にダウンロードされていません」と出たら、ダウンロード欄のファイルにある「…」→「保存」（Edge は「保持」→「詳細表示」→「それでも保持」）を押してください',
        figure: 'browserWarning',
      },
      {
        no: 2,
        title: 'ダウンロードしたファイルを開く',
        detail: '「ドリームランド・パスポート」をダブルクリック。「WindowsによってPCが保護されました」と出たら「詳細情報」→「実行」。黒い画面は出ません',
        figure: 'smartScreen',
      },
      { no: 3, title: 'ログインした MT5 を、このパソコンで開いておく', detail: '口座にログインした MT5 を、この画面を開いているのと同じパソコンで開いたままにしてください（最小化していても大丈夫です）' },
      { no: 4, title: 'あとは待つだけ', detail: 'ツールが起動すると、この画面が自動で先へ進みます' },
    ]
  }
  return [
    { no: 1, title: 'ZIPを展開する', detail: 'ダウンロードした DreamlandPassport.zip を右クリック →「すべて展開」' },
    { no: 2, title: '「はじめる.bat」を開く', detail: '展開したフォルダの中にあります。画面の案内どおり Enter を押すだけ（初回は数分かかります）' },
    { no: 3, title: 'ログインした MT5 を、このパソコンで開いておく', detail: '口座にログインした MT5 を、この画面を開いているのと同じパソコンで開いたままにしてください（最小化していても大丈夫です）' },
    { no: 4, title: 'あとは待つだけ', detail: 'ツールが起動すると、この画面が自動で先へ進みます' },
  ]
}

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

/** 過去 N 日ぶんの決済実績（1日ごとの内訳つき） */
export interface HistoryDay {
  date: string
  closed: number
  profit: number
}

export interface HistoryStats {
  days: number
  from?: string
  to?: string
  closed: number
  profit: number
  wins: number
  losses: number
  best?: number
  worst?: number
  gross_win?: number
  gross_loss?: number
  daily?: HistoryDay[]
}

/** いま持っている建玉。price_current は MT5 の現在値そのまま */
export interface PositionRow {
  ticket: number
  symbol: string
  side: 'buy' | 'sell'
  volume: number
  price_open: number
  price_current: number
  sl?: number
  tp?: number
  profit: number
  swap?: number
  digits?: number
  opened_at?: string
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
      working: 'パスポートを確認しています',
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
        : 'Experts にシステムが見つかりません。パスポートを起動するか、チャートへドラッグしてください',
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

export function formatSigned(n: number, currency?: string): string {
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

/** 価格。銘柄の桁数（MT5 の digits）に合わせる */
export function formatPrice(n: number, digits?: number): string {
  const d = typeof digits === 'number' && digits >= 0 && digits <= 8 ? digits : 3
  return n.toLocaleString('ja-JP', { minimumFractionDigits: d, maximumFractionDigits: d })
}

/** 勝率（％）。決済がなければ null */
export function winRate(wins: number, closed: number): number | null {
  if (!closed) return null
  return Math.round((wins / closed) * 1000) / 10
}

/** 「M/D」表記。ブリッジは YYYY-MM-DD で返す */
export function formatDay(date: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  if (!m) return date
  return `${Number(m[2])}/${Number(m[3])}`
}

/** 「M/D HH:MM」表記。ブリッジは ISO で返す */
export function formatStamp(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function formatHistoryAnswer(h: HistoryStats | undefined, currency?: string): string {
  if (!h) return '口座の履歴を読み取れませんでした。'
  if (!h.closed) {
    return `過去${h.days}日ぶんの履歴を見ましたが、決済はありませんでした。数字は口座の履歴をそのまま出しています。`
  }
  const rate = winRate(h.wins, h.closed)
  return (
    `過去${h.days}日で、決済は${h.closed}回、損益は ${formatSigned(h.profit, currency)} です。` +
    `勝ち${h.wins}・負け${h.losses}${rate != null ? `（勝率${rate}%）` : ''}。` +
    `いちばん取れた取引が ${formatSigned(h.best ?? 0, currency)}、いちばん損した取引が ${formatSigned(h.worst ?? 0, currency)} でした。` +
    '数字は口座の履歴をそのまま出しています。'
  )
}

export function formatPositionsAnswer(rows: PositionRow[] | undefined, currency?: string): string {
  const list = rows ?? []
  if (list.length === 0) {
    return 'いまお持ちの建玉はありません。次の条件がそろうまで、システムは待っている状態です。'
  }
  const floating = list.reduce((sum, r) => sum + (r.profit ?? 0), 0)
  const symbols = [...new Set(list.map((r) => r.symbol))].join('・')
  return (
    `いまの建玉は${list.length}件（${symbols}）、含み損益は ${formatSigned(floating, currency)} です。` +
    '下に、それぞれの値段と現在値を出しました。'
  )
}

/** つながったあと、MT5 の画面でお客様が一度だけやること（外からは自動化できない） */
export const MT5_STEPS: UserStep[] = [
  {
    no: 1,
    title: 'システムをチャートに載せる',
    detail: 'ナビゲーター →「エキスパートアドバイザ」→ YumekkuEA_win（Mac は YumekkuEA_mac）をゴールド（XAUUSD または GOLD）のチャートへドラッグ →「アルゴ取引を許可」にチェック → OK',
  },
  {
    no: 2,
    title: '「アルゴ取引」ボタンを ON にする',
    detail: 'MT5 上部のボタンが緑になれば OK（「自動売買」と表示される版もあります）',
  },
]

/**
 * MT5 側の準備がどこまで済んだか。ブリッジが返した状態だけを見る。
 * 返り値は「いまやってもらう手順」の添字。すべて済んでいれば null。
 */
export function mt5StepIndex(
  s: { ea_alive?: boolean; ea_symbol_ok?: boolean | null; ea_state?: string | null; terminal_trade_allowed?: boolean } | null | undefined,
): number | null {
  if (!s || s.ea_alive !== true) return 0
  // 動いていても、ゴールド以外のチャートなら「載せる」からやり直し
  if (s.ea_symbol_ok === false) return 0
  if (s.terminal_trade_allowed === false || s.ea_state === '自動売買ボタンがオフ') return 1
  return null
}
