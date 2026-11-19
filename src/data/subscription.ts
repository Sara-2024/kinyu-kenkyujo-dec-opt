// Yumekku【サブスク版】の申請と承認（管理サイト）。
//
// お客様は特別ゲート（dreamland/yumekku-sub/）で申請し、運営がここで「承認／停止」を切り替える。
// 承認しているあいだだけ、DB が利用許可（24〜25 時間で切れる署名つき）を出し、中継がパスポートへ渡す。
// 停止すると、パスポートがつながっていれば 1 分ほどで、つながっていなくても最長 25 時間で新規エントリーが止まる。
import { supabase } from '../lib/supabase'
import { DREAMLAND_PLAN_NAMES } from './dreamland'

/** 会員のプラン（ロビーの 3 つ ＋ サブスク） */
export type MemberPlan = 'first' | 'crystal' | 'premium' | 'subscription'
export const MEMBER_PLANS: readonly MemberPlan[] = ['first', 'crystal', 'premium', 'subscription']
export const PLAN_NAMES: Record<MemberPlan, string> = { ...DREAMLAND_PLAN_NAMES, subscription: 'Yumekku【サブスク版】' }

export type SubscriptionStatus = 'pending' | 'active' | 'stopped'
export const SUBSCRIPTION_STATUS_NAMES: Record<SubscriptionStatus, string> = {
  pending: '審査中',
  active: '承認中（利用できる）',
  stopped: '停止中',
}

export interface SubscriptionRow {
  member_id: string
  account: number | null
  name: string
  member_status: string
  status: SubscriptionStatus
  applied_at: string
  approved_at: string | null
  stopped_at: string | null
  note: string
  /** 申請を送ってきた回数 */
  submissions: number
}

async function rpc<T>(name: string, args: Record<string, unknown>): Promise<T> {
  if (!supabase) throw new Error('NOT_CONFIGURED')
  const { data, error } = await supabase.rpc(name, args)
  if (error) throw error
  return data as T
}

export function subscriptionErrorMessage(error: unknown): string {
  const raw =
    error && typeof error === 'object' && 'message' in error ? String((error as { message: string }).message) : String(error ?? '')
  if (raw.includes('NOT_CONFIGURED')) return '研究所への接続設定がまだ完了していません。'
  if (raw.includes('FORBIDDEN')) return 'この操作を行う権限がありません。'
  if (raw.includes('NOT_FOUND')) return '対象の申請が見つかりません。'
  if (raw.includes('SESSION_EXPIRED')) return 'ログインの有効期限が切れました。もう一度ログインしてください。'
  if (/could not find the function|does not exist|PGRST202/i.test(raw)) {
    return 'データベースにまだサブスク版の設定が入っていません（supabase/migrations/20261118_subscription.sql を流してください）。'
  }
  return '処理に失敗しました。時間をおいてもう一度お試しください。'
}

export function subscriptionList(token: string): Promise<SubscriptionRow[]> {
  return rpc<SubscriptionRow[]>('admin_list_subscriptions', { p_token: token }).then((rows) => rows ?? [])
}

export function subscriptionSet(token: string, memberId: string, status: SubscriptionStatus, note?: string): Promise<unknown> {
  return rpc('admin_set_subscription', { p_token: token, p_member_id: memberId, p_status: status, p_note: note ?? null })
}

/** その口座は Yumekku【サブスク版】か（会員のプラン、無ければパスポートが名乗った EA の名前で見る） */
export function isSubscriptionAccount(plan: unknown, status: unknown): boolean {
  if (plan === 'subscription') return true
  const s = (status ?? null) as { ea_expected?: unknown; ea_name?: unknown; subscription?: unknown } | null
  const ea = String(s?.ea_expected ?? s?.ea_name ?? '')
  return ea.includes('サブスク版') || (typeof s?.subscription === 'string' && s.subscription !== '')
}

/** 管理者画面の「通常プラン／サブスク版」の切り替え */
export type PlanView = 'all' | 'normal' | 'subscription'
