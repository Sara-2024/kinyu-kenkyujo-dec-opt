import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Chat } from './pages/Chat'
import { Lab } from './pages/Lab'
import { Login } from './pages/Login'
import { Admin } from './pages/Admin'
import { useAuth } from './hooks/AuthContext'

function RequireAuth({ children }: { children: ReactNode }) {
  const { ready, member } = useAuth()
  if (!ready) return <BootScreen />
  if (!member) return <Navigate to="/login" replace />
  return children
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { ready, member } = useAuth()
  if (!ready) return <BootScreen />
  if (!member) return <Navigate to="/login" replace />
  if (member.role !== 'admin') return <Navigate to="/" replace />
  return children
}

function BootScreen() {
  return <div className="h-screen w-full" style={{ background: '#070b14' }} />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/admin"
        element={
          <RequireAdmin>
            <Admin />
          </RequireAdmin>
        }
      />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Lab />
          </RequireAuth>
        }
      />
      <Route
        path="/chat/:id"
        element={
          <RequireAuth>
            <Chat />
          </RequireAuth>
        }
      />
      <Route
        path="*"
        element={
          <RequireAuth>
            <Lab />
          </RequireAuth>
        }
      />
    </Routes>
  )
}
