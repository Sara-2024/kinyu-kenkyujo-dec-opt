// サイトのボタンから、お客様のPCの接続ツールを呼び出す／配る。
//
// ブラウザは仕組み上、勝手にPCのソフトを起動できない。
// そのかわり接続ツールが自分を aitrader:// として登録しているので、
// このURLを開くとブラウザがツールを起動してくれる。
// （ツールがまだ入っていないPCでは何も起きない。その場合はここからダウンロードしてもらう）

import { issueConnectToken, memberPlatformSet } from './auth'

export const CONNECTOR_SCHEME = 'aitrader'

/**
 * 新しいMT5連携の受付を、一時的に止めるスイッチ。
 *
 * サイトは合図（token）方式に切り替わったが、配っている接続ツールがまだ古い。
 * 古いツールは合図を読めず、そのまま既定の部屋でブリッジを動かしてしまうので、
 * 新しいツールを配り終えるまで、新規の連携を受け付けない。
 *
 * 止まるのは「これから連携する人」だけ。すでに連携済みのお客様のブリッジは
 * サイトとは関係なく動き続けるし、つなぎ直し（relaunchConnector）も使える。
 *
 * 再開するときは、ここを false に戻すだけでよい（他は何も変えなくてよい）。
 */
export const CONNECT_PAUSED = false

/**
 * 部屋（会員ID）を知らずに起動した接続ツールが入る、既定の部屋。
 * ダウンロードした exe を「開くだけ」の初回は aitrader:// を通らないので、ここに来る。
 * サイトはこの部屋にブリッジが現れたら、登録の済んだ aitrader:// で部屋を伝えて呼び直す。
 */
export const DEFAULT_ROOM = 'vps-01'

/** 既定の部屋を見に行く間隔と、「いま起動したもの」とみなす新しさ */
export const DEFAULT_ROOM_POLL_MS = 3_000
export const DEFAULT_ROOM_FRESH_MS = 10 * 60_000

/**
 * 中継の /health（ブリッジが「いるか／いつ来たか」だけを返す）の URL。
 * 画面は会員ID以外の部屋には入れないので、既定の部屋はこれで見る。
 */
export function relayHealthUrl(room: string): string {
  const ws = (import.meta.env.VITE_RELAY_URL as string | undefined) || 'ws://localhost:8080/app'
  const http = ws.replace(/^wss:/, 'https:').replace(/^ws:/, 'http:').replace(/\/app(\?.*)?$/, '')
  return `${http}/health?room=${encodeURIComponent(room)}`
}

export interface RoomProbe {
  bridge: boolean
  /** ブリッジがつながった時刻（ms）。いなければ null */
  since: number | null
}

/** 既定の部屋にブリッジがいるかを中継に聞く。中継に届かなければ null */
export async function probeRoom(room: string): Promise<RoomProbe | null> {
  try {
    const res = await fetch(relayHealthUrl(room), { cache: 'no-store' })
    if (!res.ok) return null
    const body = (await res.json()) as { room?: { bridge?: boolean; since?: number | null } }
    if (!body.room) return null
    return { bridge: Boolean(body.room.bridge), since: typeof body.room.since === 'number' ? body.room.since : null }
  } catch {
    return null
  }
}

/** 呼び出してから、ブリッジが名乗り出るのを待つ時間 */
// EA のコンパイルと MT5 の初期化を挟むので、12秒だと足りないことがある
export const CONNECTOR_WAIT_MS = 30_000

/**
 * 接続ツールを呼び出す。
 *
 * URL に載せるのは、その場で作った短命の合図（token）だけ。
 * 会員IDそのものは載せない（記録や履歴に残ると、他人に使われうるため）。
 *
 * 合図をもらえなかったときは何もしない。呼び出し側は false を見て案内を出す。
 * 古い形（room=）はツール側に互換として残してあるが、ここからは発行しない。
 */
export async function launchConnector(sessionToken?: string | null): Promise<boolean> {
  if (typeof window === 'undefined') return false
  if (CONNECT_PAUSED) return false
  if (!sessionToken) return false

  let connectToken: string | null = null
  try {
    connectToken = await issueConnectToken(sessionToken)
  } catch {
    connectToken = null
  }
  if (!connectToken) return false

  const params = new URLSearchParams()
  params.set('from', window.location.origin)
  params.set('token', connectToken)
  const url = `${CONNECTOR_SCHEME}://connect?${params.toString()}`
  try {
    // location を書き換えると、未登録のPCでは何も起きずにページも遷移しない
    window.location.href = url
    return true
  } catch {
    // 起動できなくても画面は続ける（ダウンロードの案内に切り替わる）
    return false
  }
}

/**
 * すでに連携しているPCに「つなぎ直して」と伝える。
 *
 * 合図（token）を付けないので、この URL では新しい連携はできない。
 *   古いツール … 覚えている部屋（会員ID）につなぎ直すだけ
 *   新しいツール … 連携済みならつなぎ直し、未連携なら EA を置くだけで終わる
 * どちらでも、これで新しく連携されることはない。
 *
 * 使うのは「一度つないだことがあるお客様」の画面だけ（管理画面の再接続）。
 */
export function relaunchConnector(): void {
  if (typeof window === 'undefined') return
  try {
    window.location.href = `${CONNECTOR_SCHEME}://connect`
  } catch {
    // 起動できなくても画面は続ける
  }
}

// ────────────────────────────────
// 接続ツールのダウンロード
//   既定は public/download/MT5Automatic.exe（Windows で tools/build-windows.bat を実行して
//   できたもの。Python 不要で開くだけ）。Python 版の ZIP（tools/pack-connector.sh）も
//   同じ場所にあり、VITE_CONNECTOR_URL=/download/MT5Automatic.zip で差し替えられる。
//   .exe なら「開くだけ」、.zip なら「展開して はじめる.bat を開く」と案内が変わる。
// ────────────────────────────────
export type ConnectorKind = 'exe' | 'zip' | 'mac'

/**
 * お客様のパソコン。配るものと手順が変わる。
 *   windows … MT5Automatic.exe（Python 部品で MT5 を直接読む）
 *   mac     … MT5Automatic-mac.zip（EA が書くファイルを読む。tools/mac/ 参照）
 * サイト・中継・一斉制御はどちらも同じ。
 */
export type Platform = 'windows' | 'mac'

export interface ConnectorDownload {
  url: string
  /** サーバー上の置き場所から決まる名前（ビルドの都合） */
  filename: string
  /** お客様のPCに保存されるときの名前。ここが画面にも出る */
  saveAs: string
  kind: ConnectorKind
  platform: Platform
}

/** お客様が受け取るファイルの名前。中身は同じで、名前だけ分かりやすくする */
const SAVE_AS = 'MT5 Automatic.exe'
const SAVE_AS_MAC = 'MT5 Automatic.zip'

function windowsDownload(): ConnectorDownload {
  const url = (import.meta.env.VITE_CONNECTOR_URL as string | undefined)?.trim() || '/download/MT5Automatic.exe'
  const filename = url.split('?')[0].split('/').pop() || 'MT5Automatic.zip'
  const kind: ConnectorKind = /\.exe$/i.test(filename) ? 'exe' : 'zip'
  // ZIP を配るときは中身が違うので、名前もそのまま使う
  return { url, filename, saveAs: kind === 'exe' ? SAVE_AS : filename, kind, platform: 'windows' }
}

function macDownload(): ConnectorDownload {
  const url = (import.meta.env.VITE_CONNECTOR_URL_MAC as string | undefined)?.trim() || '/download/MT5Automatic-mac.zip'
  const filename = url.split('?')[0].split('/').pop() || 'MT5Automatic-mac.zip'
  return { url, filename, saveAs: SAVE_AS_MAC, kind: 'mac', platform: 'mac' }
}

/** Windows 用（これまでどおり。古い呼び出し口のために残す） */
export const CONNECTOR_DOWNLOAD: ConnectorDownload = windowsDownload()

export const CONNECTOR_DOWNLOADS: Record<Platform, ConnectorDownload> = {
  windows: CONNECTOR_DOWNLOAD,
  mac: macDownload(),
}

export function connectorDownload(platform: Platform): ConnectorDownload {
  return CONNECTOR_DOWNLOADS[platform]
}

/** ブラウザの申告から、お使いのパソコンを推定する（画面で選び直せる） */
export function detectPlatform(): Platform {
  if (typeof navigator === 'undefined') return 'windows'
  const ua = navigator.userAgent || ''
  return /Mac OS X|Macintosh/.test(ua) && !/Windows/.test(ua) ? 'mac' : 'windows'
}

const PLATFORM_KEY = 'mt5automatic.platform'

/** 選んだパソコン。選んでいなければブラウザから推定 */
export function loadPlatform(): Platform {
  try {
    const saved = localStorage.getItem(PLATFORM_KEY)
    if (saved === 'mac' || saved === 'windows') return saved
  } catch {
    // 保存できない環境では推定だけ
  }
  return detectPlatform()
}

export function savePlatform(platform: Platform): void {
  try {
    localStorage.setItem(PLATFORM_KEY, platform)
  } catch {
    // 保存できなくても画面は続ける
  }
}

/** 運営が「誰が何を使っているか」を見られるように、サイト側に記録する。失敗しても画面は止めない */
export async function recordPlatform(sessionToken: string | null | undefined, platform: Platform): Promise<void> {
  if (!sessionToken) return
  try {
    await memberPlatformSet(sessionToken, platform)
  } catch {
    // 記録は見るためのもの。連携そのものには影響させない
  }
}

/** ブラウザに保存ダイアログを出す（普通のダウンロード） */
export function downloadConnector(platform: Platform = loadPlatform()): void {
  if (typeof document === 'undefined') return
  // 古い接続ツールを新しく配らない（受付を止めているあいだ）
  if (CONNECT_PAUSED) return
  const target = connectorDownload(platform)
  const a = document.createElement('a')
  a.href = target.url
  a.download = target.saveAs
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
