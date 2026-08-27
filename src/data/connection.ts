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

export function newConnection(email: string): Connection {
  return {
    email,
    account: '70418552',
    server: 'XMTrading-Real 3',
    connectedAt: new Date().toISOString(),
    running: true,
    settings: defaultSettings(),
  }
}
