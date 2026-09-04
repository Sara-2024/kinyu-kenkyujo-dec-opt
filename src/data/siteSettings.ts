// サイト全体の設定（研究員の名前など）。Supabase の app_settings.site_settings に置き、
// 管理者画面から変えられる。取れないときは端末に残した前回の値 → 既定値の順で使う。
import { supabase } from '../lib/supabase'

export interface SiteSettings {
  /** 研究員の表示名。キーは characters.ts の id */
  names?: Record<string, string>
}

const CACHE_KEY = 'trelab-site-settings'

export function readCachedSettings(): SiteSettings {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    return raw ? (JSON.parse(raw) as SiteSettings) : {}
  } catch {
    return {}
  }
}

export function writeCachedSettings(settings: SiteSettings): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(settings))
  } catch {
    // 保存できなくても表示は続ける
  }
}

export async function loadSiteSettings(): Promise<SiteSettings | null> {
  if (!supabase) return null
  const { data, error } = await supabase.rpc('site_settings_get')
  if (error) throw error
  return (data ?? {}) as SiteSettings
}

export async function adminSaveSiteSettings(token: string, settings: SiteSettings): Promise<SiteSettings> {
  if (!supabase) throw new Error('NOT_CONFIGURED')
  const { data, error } = await supabase.rpc('admin_set_site_settings', { p_token: token, p_settings: settings })
  if (error) throw error
  return (data ?? settings) as SiteSettings
}
