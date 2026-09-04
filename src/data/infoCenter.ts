// 情報センター（研究所の右側）に並べる、相場の予定とお知らせ。
// 成績や建玉の数字はここには置かない（それらはブリッジが返した値だけを使う）。

/** 定例の経済イベント。日付ではなく「いつも何時か」で持つ（日本時間） */
export interface MarketEvent {
  name: string
  /** 発表のタイミング */
  when: string
  /** 何が動きやすいか */
  note: string
  impact: 'high' | 'mid'
}

export const MARKET_SCHEDULE: MarketEvent[] = [
  { name: '米・雇用統計', when: '毎月第1金曜 21:30', note: 'ドル円が最も飛びやすい', impact: 'high' },
  { name: '米・消費者物価指数（CPI）', when: '毎月中旬 21:30', note: '利下げ観測を左右', impact: 'high' },
  { name: 'FOMC 政策金利', when: '年8回 03:00', note: 'ドル全般', impact: 'high' },
  { name: '日銀 金融政策決定会合', when: '年8回 正午前後', note: '円絡み全般', impact: 'high' },
  { name: 'ECB 理事会', when: '年8回 21:15', note: 'ユーロ', impact: 'mid' },
  { name: '米・小売売上高', when: '毎月中旬 21:30', note: 'ドル', impact: 'mid' },
]

export const SCHEDULE_NOTE = '時刻は日本時間の夏時間。冬時間は1時間遅くなります。'

/** お知らせ・アップデート情報・今後の予定 */
export interface Notice {
  date: string
  tag: 'お知らせ' | 'アップデート' | '予定'
  title: string
  body: string
}

export const NOTICES: Notice[] = [
  {
    date: '2026-09-04',
    tag: 'アップデート',
    title: 'アルゴ管制室と情報センターを新設',
    body: '研究所の画面を作り直しました。アルゴが運用状況を頭上の吹き出しで随時お知らせし、右の情報センターに取引の記録が残ります。',
  },
  {
    date: '2026-09-01',
    tag: 'アップデート',
    title: '受付をリニューアル',
    body: 'ログインと会員登録を、受付のユイが順に案内する形にしました。',
  },
  {
    date: '2026-08-20',
    tag: 'アップデート',
    title: 'トレードの添削',
    body: 'リンがMT5の約定履歴（既定180日）から、勝ち負けの幅・保有時間・時間帯のクセを読み取ります。',
  },
  {
    date: '2026-08-10',
    tag: 'お知らせ',
    title: '接続ツールは黒い画面を出しません',
    body: 'AIトレーダーは裏側で動きます。経過は connect.log に残るので、うまくいかないときはそちらをお送りください。',
  },
  {
    date: '',
    tag: '予定',
    title: '運用報告のメール配信',
    body: 'アルゴの1日の運用報告を、毎晩メールでもお届けする準備をしています。',
  },
  {
    date: '',
    tag: '予定',
    title: 'スマートフォン表示の最適化',
    body: '外出先でも稼働状況を確認できるよう、縦画面のレイアウトを用意します。',
  },
]

/** SYSTEM LAB に並べる拡張機能の一覧（状態つき） */
export interface Extension {
  name: string
  desc: string
  state: '稼働中' | '開発中' | '予定'
}

export const EXTENSIONS: Extension[] = [
  { name: '自動売買システム', desc: 'MT5 に載せて稼働。ロット・同時保有数はサイトから変更', state: '稼働中' },
  { name: 'トレード添削', desc: '約定履歴からクセを読み取る', state: '稼働中' },
  { name: '新インジケーター', desc: '移動平均とRSIを組み合わせた確認用の道具', state: '開発中' },
  { name: '運用報告メール', desc: '1日の成績を毎晩お届け', state: '予定' },
]
