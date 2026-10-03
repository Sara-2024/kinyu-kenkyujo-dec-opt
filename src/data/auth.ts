import { supabase } from '../lib/supabase'

export type MemberRole = 'user' | 'admin'
export type MemberStatus = 'active' | 'suspended'

export interface Member {
  id: string
  email: string
  role: MemberRole
  status: MemberStatus
  can_trade: boolean
  last_login_at?: string | null
  created_at?: string
  account?: string | null
  server?: string | null
  running?: boolean | null
  connected_at?: string | null
}

export interface AuthSession {
  token: string
  member: Member
}

const TOKEN_KEY = 'trelab-session-token'

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
  if (raw.includes('INVALID_EMAIL')) return 'メールアドレスの形を確認してください。'
  if (raw.includes('WEAK_PASSWORD')) return 'パスワードは8文字以上にしてください。'
  if (raw.includes('BAD_ENTRY')) return '入場パスワードが違います。'
  if (raw.includes('EMAIL_TAKEN')) return 'このメールアドレスはすでに登録されています。'
  if (raw.includes('BAD_CREDENTIALS')) return 'メールアドレスまたはパスワードが違います。'
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

export async function authRegister(email: string, password: string, entry: string): Promise<AuthSession> {
  return rpc<AuthSession>('auth_register', {
    p_email: email,
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

export async function authLogin(email: string, password: string): Promise<AuthSession> {
  return rpc<AuthSession>('auth_login', { p_email: email, p_password: password })
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
 * ログイン中のときだけ作れる。会員IDそのものを接続ツールへ渡さないために使う。
 * 数分で切れ、一度使ったら無効。
 */
export async function issueConnectToken(token: string): Promise<string | null> {
  const data = await rpc<{ token?: string }>('connect_token_issue', { p_token: token })
  return typeof data?.token === 'string' ? data.token : null
}
