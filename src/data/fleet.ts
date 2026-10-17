// 一斉制御（自社デモ口座の登録簿）。既存の会員・連携とは別枠。
//
// 口座は「ログイン中の会員」が登録する。その会員IDが、口座の PC で動く
// ドリームランド・パスポート の部屋になるので、一斉停止は会員IDの部屋へ流せばよい。
// パスワードは預かるだけで、停止には使わない。
import { supabase } from '../lib/supabase'

export interface FleetAccount {
  id: string
  member_id: string
  email: string
  account: number
  server: string
  included: boolean
  note: string
  created_at: string
  updated_at: string
  /** その会員が初期設定で選んだパソコン（記録があれば） */
  platform?: 'windows' | 'mac' | null
}

/**
 * その口座で動いているシステム（EA）の短い呼び名。管理者画面・一斉制御の「システム」列に出す。
 * ブリッジが名乗った「載せるべき EA」（ea_expected。1 つ目は YumekkuEA-1年版、ロイヤルの 2 つ目は
 * YumekkuEA1年版｜安定低月利ver）を優先し、無ければ実際に載っている EA 名（ea_name）。
 * 先頭の「YumekkuEA」は省いて「1年版」「1年版｜安定低月利ver」のように出す。
 */
export function systemLabel(status: unknown): string {
  const s = (status ?? null) as { ea_expected?: unknown; ea_name?: unknown } | null
  const raw = s?.ea_expected ?? s?.ea_name
  if (typeof raw !== 'string' || !raw) return '—'
  return raw.replace(/^YumekkuEA[-_ ]?/i, '') || raw
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

export function fleetErrorMessage(error: unknown): string {
  const raw =
    error && typeof error === 'object' && 'message' in error ? String((error as { message: string }).message) : String(error ?? '')
  if (raw.includes('NOT_CONFIGURED')) return '研究所への接続設定がまだ完了していません。'
  if (raw.includes('BAD_ACCOUNT')) return '口座番号は数字で入力してください。'
  if (raw.includes('BAD_SERVER')) return 'サーバー名を入力してください（MT5 のログイン画面に出ている名前）。'
  if (raw.includes('BAD_PASSWORD')) return 'パスワードを入力してください。'
  if (raw.includes('TAKEN')) return 'この口座は別の方が登録済みです。'
  if (raw.includes('FORBIDDEN')) return 'この操作を行う権限がありません。'
  if (raw.includes('NOT_FOUND')) return '対象の口座が見つかりません。'
  if (raw.includes('SESSION_EXPIRED')) return 'ログインの有効期限が切れました。もう一度ログインしてください。'
  if (/fleet_optout|fleet_my_optout|fleet_optouts/.test(raw) && /could not find the function|does not exist|PGRST202/i.test(raw)) {
    return 'データベースに「一斉停止を受け付けない」設定がまだ入っていません（supabase/migrations/20261003_fleet_optout.sql を流してください）。'
  }
  if (/fleet_register_for/.test(raw) && /could not find the function|does not exist|PGRST202/i.test(raw)) {
    return 'データベースに「つながっている口座を登録する」設定がまだ入っていません（supabase/migrations/20261003_fleet_register_for.sql を流してください）。'
  }
  if (/could not find the function|does not exist|PGRST202/i.test(raw)) {
    return 'データベースにまだ一斉制御の設定が入っていません（supabase/migrations/20261002_add_fleet.sql を流してください）。'
  }
  return '処理に失敗しました。時間をおいてもう一度お試しください。'
}

export function fleetRegister(token: string, account: number, server: string, password: string): Promise<FleetAccount> {
  return rpc<FleetAccount>('fleet_register', { p_token: token, p_account: account, p_server: server, p_password: password })
}

/** 管理者が、つながっている部屋（会員）を登録簿に加える。パスワードは預からない。 */
export function fleetRegisterFor(token: string, memberId: string, account: number, server: string): Promise<FleetAccount> {
  return rpc<FleetAccount>('fleet_register_for', { p_token: token, p_member_id: memberId, p_account: account, p_server: server, p_password: '' })
}

/** 本人が「運営による一斉停止」を受け付けるかどうか（連携した時点では受け付ける） */
export async function fleetMyOptout(token: string): Promise<boolean> {
  const data = await rpc<{ optout?: boolean }>('fleet_my_optout', { p_token: token })
  return Boolean(data?.optout)
}

export function fleetOptoutSet(token: string, optout: boolean): Promise<void> {
  return rpc<void>('fleet_optout_set', { p_token: token, p_optout: optout })
}

/** 管理者: 受け付けないと決めた会員の ID 一覧 */
export async function fleetOptouts(token: string): Promise<string[]> {
  const data = await rpc<string[] | null>('fleet_optouts', { p_token: token })
  return Array.isArray(data) ? data.map(String) : []
}

export function fleetMyAccounts(token: string): Promise<FleetAccount[]> {
  return rpc<FleetAccount[]>('fleet_my_accounts', { p_token: token })
}

export function fleetList(token: string): Promise<FleetAccount[]> {
  return rpc<FleetAccount[]>('fleet_list', { p_token: token })
}

export function fleetSetIncluded(token: string, id: string, included: boolean): Promise<void> {
  return rpc('fleet_set_included', { p_token: token, p_id: id, p_included: included })
}

export function fleetSetNote(token: string, id: string, note: string): Promise<void> {
  return rpc('fleet_set_note', { p_token: token, p_id: id, p_note: note })
}

export function fleetDelete(token: string, id: string): Promise<void> {
  return rpc('fleet_delete', { p_token: token, p_id: id })
}

export function fleetReveal(token: string, id: string): Promise<{ account: number; server: string; password: string }> {
  return rpc('fleet_reveal', { p_token: token, p_id: id })
}
