// 接続の状態をブラウザに覚えさせる。
// 一度つないだら、次からは設定のやり直しではなく管理画面に入る。
import { defaultSettings, settingsFromGate } from './eaSettings'

const LEGACY_KEY = 'trelab-connection'

let ownerId: string | null = null
let persist: ((conn: Connection | null) => void) | null = null

function storageKey(): string {
  return ownerId ? `${LEGACY_KEY}:${ownerId}` : `${LEGACY_KEY}:none`
}

/** ログイン中の会員に紐づける。他の人の保存データは読まない。 */
export function setConnectionOwner(memberId: string | null): void {
  ownerId = memberId
}

export function setConnectionPersist(fn: ((conn: Connection | null) => void) | null): void {
  persist = fn
}

function parseConnection(raw: string): Connection | null {
  const parsed = JSON.parse(raw) as Connection
  if (parsed.account === '70418552') return null
  parsed.settings = { ...defaultSettings(), ...(parsed.settings ?? {}) }
  return parsed
}

export interface Connection {
  email: string
  account: string
  server: string
  connectedAt: string
  running: boolean
  settings: Record<string, number>
}

export function loadConnection(): Connection | null {
  if (!ownerId) return null
  try {
    const raw = localStorage.getItem(storageKey())
    if (!raw) return null
    return parseConnection(raw)
  } catch {
    return null
  }
}

export function applyRemoteConnection(raw: unknown): Connection | null {
  if (!raw || typeof raw !== 'object') return null
  try {
    const parsed = parseConnection(JSON.stringify(raw))
    if (!parsed) return null
    saveConnection(parsed, { skipRemote: true })
    return parsed
  } catch {
    return null
  }
}

export function saveConnection(conn: Connection, opts?: { skipRemote?: boolean }): void {
  try {
    localStorage.setItem(storageKey(), JSON.stringify(conn))
  } catch {
    // 保存できなくても操作は続けられるようにする
  }
  if (!opts?.skipRemote) persist?.(conn)
}

export function clearConnection(): void {
  try {
    localStorage.removeItem(storageKey())
  } catch {
    // 同上
  }
  persist?.(null)
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
