import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL?.trim()
const key = import.meta.env.VITE_SUPABASE_ANON_KEY?.trim()

function isConfigured(u: string | undefined, k: string | undefined): u is string {
  return !!u && !!k && u.startsWith('https://') && !u.includes('xxxxxxxx') && k.startsWith('eyJ')
}

/** 環境変数が未設定のときは null（画面は localStorage のみで動く） */
export const supabase: SupabaseClient | null = isConfigured(url, key)
  ? createClient(url, key)
  : null
