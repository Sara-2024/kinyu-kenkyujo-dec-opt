// 自動売買の「おまかせ接続」フロー。
//
// 大前提: MT5はお客様のPC/VPSの中で動いているので、Web側から直接は触れない。
// 必ず「MT5と同じ機械の上で動く接続ツール（bridge）」が要る。
// したがってメールアドレスの役目は “接続ツールを届けること”。
//
// 見せたいのは「ツールを入れたあとの作業がゼロ」であること。
// 下の工程はすべて、実際に接続ツールが自動でやる内容と対応している。

/** お客様がやること（3ステップ。3つめは「待つだけ」） */
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

/** 接続ツールが自動でやる工程 */
export interface ConnectStep {
  /** 作業中に出す文言 */
  working: string
  /** 終わったときに出す結果 */
  done: string
  /** この工程にかかる見せかけの時間(ms) */
  ms: number
}

export const CONNECT_STEPS: ConnectStep[] = [
  { working: 'お使いのMT5を探しています', done: 'MetaTrader 5 (build 4260) を検出しました', ms: 1200 },
  { working: 'ログイン中の口座を読み取っています', done: '口座 70418552 ／ XMTrading-Real 3', ms: 1300 },
  { working: '売買エンジンを組み込んでいます', done: 'TRELAB-EA v1.2 を配置しました', ms: 1500 },
  { working: '緊急停止スイッチを取り付けています', done: 'この画面から止められる状態になりました', ms: 1200 },
  { working: '研究所とつないでいます', done: '接続 良好（応答 12ms）', ms: 1000 },
]

/** 接続中にアルゴが話す一言（工程の節目で切り替える） */
export const CONNECT_TALK: string[] = [
  'ツールの起動を確認しました。ここから先は私が進めます。画面はそのままで大丈夫です。',
  'お使いのMT5が見つかりました。ログイン中の口座も、こちらで読み取ります。',
  'エンジンを組み込んでいます。口座のパスワードは、いつもどおり MT5 の画面だけで大丈夫です。',
  'あとは停止スイッチを取り付けるだけです。もう少しお待ちください。',
]

export function validateEmail(value: string): string | null {
  const s = value.trim()
  if (!s) return 'メールアドレスを入力してください'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s)) return 'メールアドレスの形式を確認してください'
  return null
}
