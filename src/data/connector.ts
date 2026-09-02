// サイトのボタンから、お客様のPCの接続ツールを呼び出す。
//
// ブラウザは仕組み上、勝手にPCのソフトを起動できない。
// そのかわり接続ツールが自分を aitrader:// として登録しているので、
// このURLを開くとブラウザがツールを起動してくれる。
// （ツールがまだ入っていないPCでは何も起きない。その場合はメールでお送りする）

export const CONNECTOR_SCHEME = 'aitrader'

/** 呼び出してから、ブリッジが名乗り出るのを待つ時間 */
export const CONNECTOR_WAIT_MS = 12_000

export function launchConnector(roomId?: string | null): void {
  if (typeof window === 'undefined') return
  const params = new URLSearchParams()
  params.set('from', window.location.origin)
  if (roomId) params.set('room', roomId)
  const url = `${CONNECTOR_SCHEME}://connect?${params.toString()}`
  try {
    // location を書き換えると、未登録のPCでは何も起きずにページも遷移しない
    window.location.href = url
  } catch {
    // 起動できなくても画面は続ける（メール送付に切り替わる）
  }
}
