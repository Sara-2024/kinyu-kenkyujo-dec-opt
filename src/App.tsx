import { useEffect, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Lab } from './pages/Lab'
import { Login } from './pages/Login'
import { Admin } from './pages/Admin'
import { AdminGate } from './pages/AdminGate'
import { Fleet } from './pages/Fleet'
import { FleetJoin } from './pages/FleetJoin'
import { useAuth } from './hooks/AuthContext'

/**
 * このビルドが「管理サイト」か。
 * 同じコードを 2 つの Vercel プロジェクトで動かす。
 *   ・本体（kinyu-kenkyujo-dec-opt）… お客様向け。トップはロビーへ飛ばし、/control に稼働／停止の画面
 *   ・管理サイト（dreamland-admin、VITE_SITE_MODE=admin）… 運営向け。合言葉 1 つで /admin と /fleet に入る
 */
export const ADMIN_SITE = import.meta.env.VITE_SITE_MODE === 'admin'

/** お客様向けの顔はロビー（dreamland/）。本体サイトのトップはそこへ飛ばす */
export const LOBBY_URL = (import.meta.env.VITE_LOBBY_URL as string | undefined)?.trim() || 'https://dreamland-lobby.vercel.app/'

function RequireAuth({ children }: { children: ReactNode }) {
  const { ready, member } = useAuth()
  if (!ready) return <BootScreen />
  if (!member) return <Navigate to={ADMIN_SITE ? '/' : '/login'} replace />
  return children
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { ready, member } = useAuth()
  if (!ready) return <BootScreen />
  if (!member) return <Navigate to={ADMIN_SITE ? '/' : '/login'} replace />
  if (member.role !== 'admin') return <Navigate to={ADMIN_SITE ? '/' : '/control'} replace />
  return children
}

function BootScreen() {
  return <div className="h-screen w-full" style={{ background: ADMIN_SITE ? '#dbe5f2' : '#070b14' }} />
}

/** ロビーへ移動する（本体サイトのトップ） */
function ToLobby() {
  useEffect(() => {
    window.location.replace(LOBBY_URL)
  }, [])
  return <div className="h-screen w-full" style={{ background: '#dbe5f2' }} />
}

export default function App() {
  if (ADMIN_SITE) {
    return (
      <Routes>
        <Route path="/" element={<AdminGate />} />
        <Route
          path="/admin"
          element={
            <RequireAdmin>
              <Admin />
            </RequireAdmin>
          }
        />
        <Route
          path="/fleet"
          element={
            <RequireAdmin>
              <Fleet />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    )
  }

  return (
    <Routes>
      {/* お客様向けの顔はロビー。ここは仕組み（窓口・ダウンロード・稼働／停止・管理）だけを残す */}
      <Route path="/" element={<ToLobby />} />
      <Route path="/login" element={<Login />} />
      <Route
        path="/admin"
        element={
          <RequireAdmin>
            <Admin />
          </RequireAdmin>
        }
      />
      {/* 一斉制御（自社デモ口座）。既存の画面とは別枠 */}
      <Route
        path="/fleet"
        element={
          <RequireAdmin>
            <Fleet />
          </RequireAdmin>
        }
      />
      <Route
        path="/fleet/join"
        element={
          <RequireAuth>
            <FleetJoin />
          </RequireAuth>
        }
      />
      {/* 稼働／停止・ロット変更の管理画面（旧・研究所の管制室） */}
      <Route
        path="/control"
        element={
          <RequireAuth>
            <Lab />
          </RequireAuth>
        }
      />
      <Route path="*" element={<ToLobby />} />
    </Routes>
  )
}
