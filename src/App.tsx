import { Route, Routes } from 'react-router-dom'
import { Chat } from './pages/Chat'
import { Lab } from './pages/Lab'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Lab />} />
      <Route path="/chat/:id" element={<Chat />} />
      <Route path="*" element={<Lab />} />
    </Routes>
  )
}
