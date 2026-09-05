// サイトのボタンから、お客様のPCの接続ツールを呼び出す／配る。
//
// ブラウザは仕組み上、勝手にPCのソフトを起動できない。
// そのかわり接続ツールが自分を aitrader:// として登録しているので、
// このURLを開くとブラウザがツールを起動してくれる。
// （ツールがまだ入っていないPCでは何も起きない。その場合はここからダウンロードしてもらう）

export const CONNECTOR_SCHEME = 'aitrader'

/** 呼び出してから、ブリッジが名乗り出るのを待つ時間 */
// EA のコンパイルと MT5 の初期化を挟むので、12秒だと足りないことがある
export const CONNECTOR_WAIT_MS = 30_000

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
    // 起動できなくても画面は続ける（ダウンロードの案内に切り替わる）
  }
}

// ────────────────────────────────
// 接続ツールのダウンロード
//   既定は public/download/AITrader.exe（Windows で tools/build-windows.bat を実行して
//   できたもの。Python 不要で開くだけ）。Python 版の ZIP（tools/pack-connector.sh）も
//   同じ場所にあり、VITE_CONNECTOR_URL=/download/AITrader.zip で差し替えられる。
//   .exe なら「開くだけ」、.zip なら「展開して はじめる.bat を開く」と案内が変わる。
// ────────────────────────────────
export type ConnectorKind = 'exe' | 'zip'

export interface ConnectorDownload {
  url: string
  filename: string
  kind: ConnectorKind
}

export const CONNECTOR_DOWNLOAD: ConnectorDownload = (() => {
  const url = (import.meta.env.VITE_CONNECTOR_URL as string | undefined)?.trim() || '/download/AITrader.exe'
  const filename = url.split('?')[0].split('/').pop() || 'AITrader.zip'
  const kind: ConnectorKind = /\.exe$/i.test(filename) ? 'exe' : 'zip'
  return { url, filename, kind }
})()

/** ブラウザに保存ダイアログを出す（普通のダウンロード） */
export function downloadConnector(): void {
  if (typeof document === 'undefined') return
  const a = document.createElement('a')
  a.href = CONNECTOR_DOWNLOAD.url
  a.download = CONNECTOR_DOWNLOAD.filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
