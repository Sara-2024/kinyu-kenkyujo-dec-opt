// 研究員の AI（/api/chat）に聞く。担当ぶんのデータ（aiContext.ts）だけを添えて送り、
// 返ってきた answer と redirect をそのまま画面に渡す。ここで答えを作らない。
import { AI_TEXT } from './characters'
import { readToken } from './auth'

export type AiRole = 'rin' | 'jin' | 'algo' | 'mio'

export interface AiReply {
  answer: string
  /** 担当外だったとき、案内先の研究員の id */
  redirect: AiRole | null
}

export type AiFailure = 'unavailable' | 'unauthorized' | 'busy' | 'failed'

export const AI_FAILURE_TEXT: Record<AiFailure, string> = {
  unavailable: AI_TEXT.unavailable,
  unauthorized: AI_TEXT.unauthorized,
  busy: AI_TEXT.busy,
  failed: AI_TEXT.failed,
}

export async function askAi(input: {
  role: AiRole
  question: string
  context: unknown
  names: Record<string, string>
}): Promise<{ ok: true; reply: AiReply } | { ok: false; why: AiFailure }> {
  const token = readToken()
  let res: Response
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(token ? { authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(input),
    })
  } catch {
    return { ok: false, why: 'failed' }
  }
  if (res.status === 503) return { ok: false, why: 'unavailable' }
  if (res.status === 401) return { ok: false, why: 'unauthorized' }
  if (res.status === 429) return { ok: false, why: 'busy' }
  if (!res.ok) return { ok: false, why: 'failed' }
  const data = (await res.json().catch(() => null)) as Partial<AiReply> | null
  if (!data || typeof data.answer !== 'string') return { ok: false, why: 'failed' }
  return { ok: true, reply: { answer: data.answer, redirect: data.redirect ?? null } }
}

/**
 * 別の研究員に引き継ぐ質問。案内ボタンを押したあと、引き継がれた側の会話が開いたときに
 * 一度だけ取り出して、そのまま聞く。
 */
let pending: { to: string; from: string; question: string } | null = null

export function setPendingQuestion(p: { to: string; from: string; question: string } | null): void {
  pending = p
}

export function takePendingQuestion(forId: string): { from: string; question: string } | null {
  if (!pending || pending.to !== forId) return null
  const out = { from: pending.from, question: pending.question }
  pending = null
  return out
}
