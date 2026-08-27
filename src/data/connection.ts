// 接続の状態をブラウザに覚えさせる。
// 一度つないだら、次からは設定のやり直しではなく管理画面に入る。
import { defaultSettings } from './eaSettings'

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
    account,
    server,
    connectedAt: new Date().toISOString(),
    running: extra?.running ?? true,
    settings: { ...defaultSettings(), ...(extra?.settings ?? {}) },
  }
}
