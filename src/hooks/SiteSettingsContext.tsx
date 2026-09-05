// 研究員の名前など、サイト全体の設定を配る。
// 起動時に Supabase から読み、読めるまでは端末に残した前回の値で描く。
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { CHARACTERS, type Character } from '../data/characters'
import {
  adminSaveSiteSettings,
  loadSiteSettings,
  readCachedSettings,
  writeCachedSettings,
  type SiteSettings,
} from '../data/siteSettings'

interface SiteSettingsState {
  settings: SiteSettings
  /** 名前を設定で差し替えた研究員一覧 */
  characters: Record<string, Character>
  /** 管理者が保存する。Supabase に書けなければ端末にだけ残す */
  save: (token: string | null, next: SiteSettings) => Promise<'remote' | 'local'>
  /** 台詞の {{id}} をいまの名前にする */
  t: (text: string) => string
}

const Ctx = createContext<SiteSettingsState | null>(null)

/** 台詞の {{id}} を、いまの名前に置き換える */
function fill(text: string, nameOf: (id: string) => string): string {
  return text.replace(/\{\{(\w+)\}\}/g, (_, id: string) => nameOf(id))
}

export function applyNames(names: Record<string, string> | undefined): Record<string, Character> {
  const nameOf = (id: string) => names?.[id]?.trim() || CHARACTERS[id]?.name || id
  const out: Record<string, Character> = {}
  for (const [id, c] of Object.entries(CHARACTERS)) {
    const answers: Record<string, string> = {}
    for (const [q, a] of Object.entries(c.answers)) answers[q] = fill(a, nameOf)
    out[id] = {
      ...c,
      name: nameOf(id),
      greeting: fill(c.greeting, nameOf),
      fallback: fill(c.fallback, nameOf),
      answers,
      returningRunning: c.returningRunning && fill(c.returningRunning, nameOf),
      returningStopped: c.returningStopped && fill(c.returningStopped, nameOf),
      reconnecting: c.reconnecting && fill(c.reconnecting, nameOf),
      ai: c.ai && { ...c.ai, noBridge: c.ai.noBridge && fill(c.ai.noBridge, nameOf) },
    }
  }
  return out
}

export function SiteSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<SiteSettings>(readCachedSettings)

  useEffect(() => {
    let alive = true
    loadSiteSettings()
      .then((remote) => {
        if (!alive || !remote) return
        setSettings(remote)
        writeCachedSettings(remote)
      })
      .catch(() => {
        // 関数がまだ無い／通信できない → 端末の値のまま
      })
    return () => {
      alive = false
    }
  }, [])

  const save = useCallback(async (token: string | null, next: SiteSettings) => {
    setSettings(next)
    writeCachedSettings(next)
    if (!token) return 'local' as const
    try {
      const saved = await adminSaveSiteSettings(token, next)
      setSettings(saved)
      writeCachedSettings(saved)
      return 'remote' as const
    } catch {
      return 'local' as const
    }
  }, [])

  const value = useMemo(() => {
    const names = settings.names
    const nameOf = (id: string) => names?.[id]?.trim() || CHARACTERS[id]?.name || id
    return { settings, characters: applyNames(names), save, t: (text: string) => fill(text, nameOf) }
  }, [settings, save])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSiteSettings(): SiteSettingsState {
  const v = useContext(Ctx)
  if (!v) throw new Error('SiteSettingsProvider がありません')
  return v
}
