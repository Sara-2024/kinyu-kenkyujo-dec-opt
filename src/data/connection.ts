// 接続の状態をブラウザに覚えさせる。
// 一度つないだら、次からは設定のやり直しではなく管理画面に入る。
import { defaultSettings, settingsFromGate } from './eaSettings'

const KEY = 'trelab-connection'

export interface Connection {
  email: string
  account: string
  server: string
  connectedAt: string
  running: boolean
  settings: Record<string, number>
}

export function loadConnection(): Connection | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Connection
    // 以前の画面が埋め込んでいたダミー口座は、実接続とみなさない
    if (parsed.account === '70418552') return null
    // 設定項目が増えた場合に備えて既定値で埋める
    parsed.settings = { ...defaultSettings(), ...(parsed.settings ?? {}) }
    return parsed
  } catch {
    return null
  }
}

export function saveConnection(conn: Connection): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(conn))
  } catch {
    // 保存できなくても操作は続けられるようにする
  }
}

export function clearConnection(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // 同上
  }
}

export function newConnection(
  email: string,
  account: string,
  server: string,
  extra?: { settings?: Record<string, number>; running?: boolean },
): Connection {
  return {
    email,
    account: String(account),
    server: String(server),
    connectedAt: new Date().toISOString(),
    running: extra?.running ?? true,
    settings: { ...defaultSettings(), ...(extra?.settings ?? {}) },
  }
}

/** MT5 ブリッジが返した口座の同一性キー */
export function bridgeAccountKey(status: { account?: number | string | null; server?: string | null }): string | null {
  if (status.account == null || String(status.account) === '') return null
  return `${String(status.account)}@${String(status.server ?? '')}`
}

export function connectionAccountKey(conn: Connection): string {
  return `${conn.account}@${conn.server}`
}

/** ブラウザに保存した口座と、いま MT5 が返している口座が一致するか */
export function connectionMatchesBridge(
  conn: Connection,
  status: { account?: number | string | null; server?: string | null },
): boolean {
  const live = bridgeAccountKey(status)
  if (!live) return false
  return connectionAccountKey(conn) === live
}

/** ブリッジの実口座・稼働状態を Connection に反映する（口座番号は常に MT5 側を優先） */
export function applyBridgeToConnection(
  conn: Connection,
  status: {
    account?: number | string | null
    server?: string | null
    value?: number | null
    gate?: Record<string, number> | null
  },
): Connection {
  const account = status.account != null ? String(status.account) : conn.account
  const server = status.server != null ? String(status.server) : conn.server
  const fromGate = settingsFromGate(status.gate)
  const running = typeof status.value === 'number' ? Number(status.value) !== 0 : conn.running
  return {
    ...conn,
    account,
    server,
    running,
    settings: { ...conn.settings, ...fromGate },
  }
}
