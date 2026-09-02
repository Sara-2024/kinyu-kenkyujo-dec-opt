import { memberSaveLead, readToken } from './auth'

/** 接続フローで入力されたメールを、ログイン中の会員に紐づけて保存する。 */
export async function saveLead(email: string): Promise<void> {
  const token = readToken()
  if (!token) return
  try {
    await memberSaveLead(token, email)
  } catch (error) {
    console.warn('[leads]', error)
  }
}
