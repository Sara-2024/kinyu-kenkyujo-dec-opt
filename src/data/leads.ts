import { supabase } from '../lib/supabase'

/** 接続フローで入力されたメールを Supabase に記録する。失敗しても UI は止めない。 */
export async function saveLead(email: string): Promise<void> {
  if (!supabase) return
  try {
    const { error } = await supabase.from('leads').insert({
      email,
      source: 'algo-connect',
    })
    if (error) console.warn('[leads]', error.message)
  } catch {
    // ネットワーク障害など。商談デモは localStorage 側で続行する。
  }
}
