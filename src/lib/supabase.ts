import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_ANON_KEY

/** 環境変数が未設定のときは null（画面は localStorage のみで動く） */
export const supabase: SupabaseClient | null =
  url && key ? createClient(url, key) : null
