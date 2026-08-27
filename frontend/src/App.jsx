import { Routes, Route, Navigate } from 'react-router-dom'
import NavBar from './components/NavBar'
import Jobs from './pages/Jobs'
import Reports from './pages/Reports'
import Templates from './pages/Templates'
import APIs from './pages/APIs'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main className="max-w-4xl mx-auto px-6 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/jobs" replace />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/apis" element={<APIs />} />
        </Routes>
      </main>
    </div>
  )
}
