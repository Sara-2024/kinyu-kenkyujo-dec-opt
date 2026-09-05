import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  authLogin,
  authLogout,
  authMe,
  authRegister,
  memberClearConnection,
  memberGetConnection,
  memberPutConnection,
  readToken,
  writeToken,
  type Member,
} from '../data/auth'
import {
  applyRemoteConnection,
  clearConnection,
  loadConnection,
  setConnectionOwner,
  setConnectionPersist,
  type Connection,
} from '../data/connection'

interface AuthState {
  ready: boolean
  member: Member | null
  token: string | null
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, entry: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

function applySession(token: string | null, member: Member | null) {
  writeToken(token)
  setConnectionOwner(member?.id ?? null)
}

async function hydrateConnection(token: string) {
  const remote = await memberGetConnection(token)
  if (remote && typeof remote === 'object') {
    applyRemoteConnection(remote)
    return
  }
  const local = loadConnection()
  if (local) {
    void memberPutConnection(token, {
      email: local.email,
      account: local.account,
      server: local.server,
      connectedAt: local.connectedAt,
      running: local.running,
      settings: local.settings,
    })
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false)
  const [member, setMember] = useState<Member | null>(null)
  const [token, setToken] = useState<string | null>(null)

  const adopt = useCallback(async (nextToken: string, nextMember: Member) => {
    applySession(nextToken, nextMember)
    setToken(nextToken)
    setMember(nextMember)
    setConnectionPersist((conn: Connection | null) => {
      if (!conn) {
        void memberClearConnection(nextToken)
        return
      }
      void memberPutConnection(nextToken, {
        email: conn.email,
        account: conn.account,
        server: conn.server,
        connectedAt: conn.connectedAt,
        running: conn.running,
        settings: conn.settings,
      })
    })
    await hydrateConnection(nextToken)
  }, [])

  const refresh = useCallback(async () => {
    // 開発中に Supabase を用意せず見た目だけ確認したいとき（npm run dev かつ .env.local に
    // VITE_PREVIEW_MEMBER=1）。本番ビルドには入らない
    if (import.meta.env.DEV && import.meta.env.VITE_PREVIEW_MEMBER === '1') {
      const preview = { id: '00000000-0000-4000-8000-000000000000', email: 'preview@example.com', role: 'admin', status: 'active', can_trade: true } as Member
      setMember(preview)
      // 連携の保存先（localStorage）は会員IDごと。プレビューでも同じ動きにする
      setConnectionOwner(preview.id)
      setToken(null)
      setReady(true)
      return
    }
    const stored = readToken()
    if (!stored) {
      applySession(null, null)
      setConnectionPersist(null)
      setToken(null)
      setMember(null)
      setReady(true)
      return
    }
    try {
      const me = await authMe(stored)
      await adopt(stored, me)
    } catch {
      applySession(null, null)
      setConnectionPersist(null)
      setToken(null)
      setMember(null)
    } finally {
      setReady(true)
    }
  }, [adopt])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await authLogin(email, password)
      await adopt(session.token, session.member)
    },
    [adopt],
  )

  const register = useCallback(
    async (email: string, password: string, entry: string) => {
      const session = await authRegister(email, password, entry)
      await adopt(session.token, session.member)
    },
    [adopt],
  )

  const logout = useCallback(async () => {
    if (token) await authLogout(token)
    setConnectionPersist(null)
    clearConnection()
    applySession(null, null)
    setToken(null)
    setMember(null)
  }, [token])

  const value = useMemo(
    () => ({ ready, member, token, login, register, logout, refresh }),
    [ready, member, token, login, register, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
