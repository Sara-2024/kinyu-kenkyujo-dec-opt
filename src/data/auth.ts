import { supabase } from '../lib/supabase'

export type MemberRole = 'user' | 'admin'
export type MemberStatus = 'active' | 'suspended'

export interface Member {
  id: string
  /** お名前（会員登録で聞く） */
  name: string
  /** 登録した MT5 の口座番号。会員 ＝ 口座番号 */
  account: number | null
  /** 契約プラン（ロビーの合言葉で決まる）。古い会員は null */
  plan?: 'first' | 'crystal' | null
  /** 旧: メール。いまは使わない（空のまま） */
  email?: string | null
  role: MemberRole
  status: MemberStatus
  can_trade: boolean
  last_login_at?: string | null
  created_at?: string
  /** 連携でつながっている口座（登録した口座と違うこともある） */
  connected_account?: number | string | null
  server?: string | null
  running?: boolean | null
  connected_at?: string | null
  /** お使いのパソコン。初期設定で選んだ／始めたときに記録される */
  platform?: 'windows' | 'mac' | null
}

export interface AuthSession {
  token: string
  member: Member
}

const TOKEN_KEY = 'trelab-session-token'

/** 画面に出す呼び名。「お名前（口座番号）」。古い会員はメール */
export function memberLabel(m: Pick<Member, 'name' | 'account' | 'email'> | null | undefined): string {
  if (!m) return ''
  if (m.name) return m.account ? `${m.name}（${m.account}）` : m.name
  return m.email ?? (m.account ? String(m.account) : '')
}

export function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function writeToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // 保存できなくても操作は止めない
  }
}

export function authErrorMessage(error: unknown): string {
  const raw =
    error && typeof error === 'object' && 'message' in error
      ? String((error as { message: string }).message)
      : String(error ?? '')
  if (raw.includes('NOT_CONFIGURED') || raw.includes('supabase')) {
    return '研究所への接続設定がまだ完了していません。運営に連絡してください。'
  }
  if (raw.includes('BAD_ACCOUNT')) return '口座番号は数字で入力してください。'
  if (raw.includes('BAD_NAME')) return 'お名前を入力してください。'
  if (raw.includes('ACCOUNT_TAKEN')) return 'この口座番号はすでに登録されています。'
  if (raw.includes('WEAK_PASSWORD')) return 'パスワードは8文字以上にしてください。'
  if (raw.includes('BAD_ENTRY')) return '入場パスワードが違います。'
  if (raw.includes('BAD_CREDENTIALS')) return '口座番号またはパスワードが違います。'
  if (raw.includes('SUSPENDED')) return 'このアカウントは停止されています。運営に連絡してください。'
  if (raw.includes('SESSION_EXPIRED')) return 'ログインの有効期限が切れました。もう一度ログインしてください。'
  if (raw.includes('FORBIDDEN')) return 'この操作を行う権限がありません。'
  if (raw.includes('LAST_ADMIN')) return '最後の管理者は、自分の権限を外せません。'
  if (raw.includes('SELF_DELETE')) return '自分自身のアカウントは削除できません。'
  if (raw.includes('NOT_FOUND')) return '対象のアカウントが見つかりません。'
  return '処理に失敗しました。時間をおいてもう一度お試しください。'
}

function client() {
  if (!supabase) {
    const err = new Error('NOT_CONFIGURED')
    throw err
  }
  return supabase
}

async function rpc<T>(name: string, args: Record<string, unknown>): Promise<T> {
  const { data, error } = await client().rpc(name, args)
  if (error) throw error
  return data as T
}

export async function authRegister(account: number, name: string, password: string, entry: string): Promise<AuthSession> {
  return rpc<AuthSession>('auth_register', {
    p_account: account,
    p_name: name,
    p_password: password,
    p_entry: entry,
  })
}

/**
 * 入場パスワードだけ先に確かめる。
 * データベースにまだこの関数が無いときは null（分からない）を返し、
 * 本登録のときの確認に任せる。
 */
export async function authCheckEntry(entry: string): Promise<boolean | null> {
  try {
    const data = await rpc<{ ok: boolean }>('auth_check_entry', { p_entry: entry })
    return !!data?.ok
  } catch (err) {
    const raw = err && typeof err === 'object' && 'message' in err ? String((err as { message: string }).message) : ''
    if (/could not find the function|does not exist|PGRST202/i.test(raw)) return null
    throw err
  }
}

/** 管理サイト：口座番号ではなく「管理サイトの合言葉」1つで入る（運営用の会員になる） */
export async function authOperatorLogin(password: string): Promise<AuthSession> {
  return rpc<AuthSession>('admin_login', { p_password: password })
}

export async function authLogin(account: number, password: string): Promise<AuthSession> {
  return rpc<AuthSession>('auth_login', { p_account: account, p_password: password })
}

export async function authLogout(token: string): Promise<void> {
  try {
    await rpc('auth_logout', { p_token: token })
  } catch {
    // サーバ側の削除に失敗しても、端末のトークンは消す
  }
}

export async function authMe(token: string): Promise<Member> {
  const data = await rpc<{ member: Member }>('auth_me', { p_token: token })
  return data.member
}

export async function adminListMembers(token: string): Promise<Member[]> {
  const data = await rpc<Member[]>('admin_list_members', { p_token: token })
  return data ?? []
}

export async function adminUpdateMember(
  token: string,
  memberId: string,
  patch: { role?: MemberRole; status?: MemberStatus; can_trade?: boolean },
): Promise<Member> {
  return rpc<Member>('admin_update_member', {
    p_token: token,
    p_member_id: memberId,
    p_role: patch.role ?? null,
    p_status: patch.status ?? null,
    p_can_trade: patch.can_trade ?? null,
  })
}

/** 会員を消す（セッション・連携・一斉制御の記録も一緒に消える）。自分と最後の管理者は消せない */
export async function adminDeleteMember(token: string, memberId: string): Promise<void> {
  await rpc<unknown>('admin_delete_member', { p_token: token, p_member_id: memberId })
}

/** お使いのパソコン（Windows / Mac）を記録する。運営が「誰が何を使っているか」を見るため */
export async function memberPlatformSet(token: string, platform: 'windows' | 'mac'): Promise<void> {
  await rpc<unknown>('member_platform_set', { p_token: token, p_platform: platform })
}

export async function adminSetPassword(token: string, memberId: string, password: string): Promise<void> {
  await rpc('admin_set_password', {
    p_token: token,
    p_member_id: memberId,
    p_password: password,
  })
}

export async function adminSetEntryPassword(token: string, entry: string): Promise<void> {
  await rpc('admin_set_entry_password', { p_token: token, p_entry: entry })
}

/** 管理サイトの合言葉を決める */
export async function adminSetOperatorPassword(token: string, password: string): Promise<void> {
  await rpc('admin_set_admin_password', { p_token: token, p_password: password })
}

/** プランごとの合言葉（ロビーの「パスポートの設置」で打つもの）を決める */
export async function adminSetPlanPassword(token: string, plan: 'first' | 'crystal', password: string): Promise<void> {
  await rpc('admin_set_plan_password', { p_token: token, p_plan: plan, p_password: password })
}

export async function memberGetConnection(token: string): Promise<unknown> {
  const data = await rpc<{ connection: unknown }>('member_get_connection', { p_token: token })
  return data?.connection ?? null
}

export async function memberPutConnection(token: string, payload: Record<string, unknown>): Promise<void> {
  await rpc('member_put_connection', { p_token: token, p_payload: payload })
}

export async function memberClearConnection(token: string): Promise<void> {
  await rpc('member_clear_connection', { p_token: token })
}

export async function memberSaveLead(token: string, email: string): Promise<void> {
  await rpc('member_save_lead', { p_token: token, p_email: email, p_source: 'algo-connect' })
}

/**
 * MT5と連携するための、短命の合図をもらう。
 *
 * ログイン中のときだけ作れる。会員IDそのものをパスポートへ渡さないために使う。
 * 数分で切れ、一度使ったら無効。
 */
export async function issueConnectToken(token: string): Promise<string | null> {
  const data = await rpc<{ token?: string }>('connect_token_issue', { p_token: token })
  return typeof data?.token === 'string' ? data.token : null
}
