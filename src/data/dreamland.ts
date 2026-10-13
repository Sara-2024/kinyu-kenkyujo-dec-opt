// ドリームランド渡航手続き（dreamland/index.html）で預かった MT5 口座の申込。
//
// お客様はロビーのサービスカウンターで口座番号・サーバー・パスワード・プランを記入し、
// サイトの /api/dreamland を通して Supabase に入る。管理者はここから一覧を見て、
// EA の納品（設置）のときにパスワードを取り出す。
import { supabase } from '../lib/supabase'

export type DreamlandPlan = 'first' | 'crystal'

export const DREAMLAND_PLAN_NAMES: Record<DreamlandPlan, string> = {
  first: 'ファーストクラス',
  crystal: 'ロイヤルファーストクラス',
}

export interface DreamlandApplication {
  id: string
  application_no: string
  account: number
  server: string
  plan: DreamlandPlan
  name: string
  email: string
  platform: 'windows' | 'mac' | null
  consent_at: string
  /** 同じ口座を送ってきた回数。何度も登録する人の判断材料 */
  submissions: number
  note: string
  created_at: string
  updated_at: string
  /** 口座番号が同じ会員（本体サイトに登録済みなら） */
  member_id?: string | null
  member_name?: string | null
}

function client() {
  if (!supabase) throw new Error('NOT_CONFIGURED')
  return supabase
}

async function rpc<T>(name: string, args: Record<string, unknown>): Promise<T> {
  const { data, error } = await client().rpc(name, args)
  if (error) throw error
  return data as T
}

export function dreamlandErrorMessage(error: unknown): string {
  const raw =
    error && typeof error === 'object' && 'message' in error ? String((error as { message: string }).message) : String(error ?? '')
  if (raw.includes('NOT_CONFIGURED')) return '研究所への接続設定がまだ完了していません。'
  if (raw.includes('FORBIDDEN')) return 'この操作を行う権限がありません。'
  if (raw.includes('NOT_FOUND')) return '対象の申込が見つかりません。'
  if (raw.includes('SESSION_EXPIRED')) return 'ログインの有効期限が切れました。もう一度ログインしてください。'
  if (/could not find the function|does not exist|PGRST202/i.test(raw)) {
    return 'データベースにまだドリームランドの申込の設定が入っていません（supabase/migrations/20261012_dreamland_applications.sql を流してください）。'
  }
  return '処理に失敗しました。時間をおいてもう一度お試しください。'
}

export function dreamlandList(token: string): Promise<DreamlandApplication[]> {
  return rpc<DreamlandApplication[]>('dreamland_list', { p_token: token })
}

export function dreamlandReveal(token: string, id: string): Promise<{ account: number; server: string; password: string }> {
  return rpc('dreamland_reveal', { p_token: token, p_id: id })
}

export function dreamlandSetNote(token: string, id: string, note: string): Promise<void> {
  return rpc<void>('dreamland_set_note', { p_token: token, p_id: id, p_note: note })
}

export function dreamlandDelete(token: string, id: string): Promise<void> {
  return rpc<void>('dreamland_delete', { p_token: token, p_id: id })
}
