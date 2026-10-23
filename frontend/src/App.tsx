import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from './components/Layout'
import { AuthProvider, useAuth } from './context/AuthContext'
import { HealthProvider } from './context/HealthContext'
import { ThemeProvider } from './context/ThemeContext'
import { AddContent } from './pages/AddContent'
import { Analytics } from './pages/Analytics'
import { Chat } from './pages/Chat'
import { ContentLibrary } from './pages/ContentLibrary'
import { ContentPlanner } from './pages/ContentPlanner'
import { Dashboard } from './pages/Dashboard'
import { Demo } from './pages/Demo'
import { Instagram } from './pages/Instagram'
import { Learned } from './pages/Learned'
import { Login } from './pages/Login'
import { MediaLibrary } from './pages/MediaLibrary'
import { Performance } from './pages/Performance'
import PrivacyPolicy from './pages/PrivacyPolicy'
import TermsOfService from './pages/TermsOfService'
import { Reviewer } from './pages/Reviewer'
import { Signup } from './pages/Signup'
import { Strategy } from './pages/Strategy'

function RequireAuth({ children }: { children: ReactNode }) {
  const { token, loading } = useAuth()
  if (loading) return null
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <AuthProvider>
      <HealthProvider>
        <ThemeProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/privacy-policy" element={<PrivacyPolicy />} />
            <Route path="/terms-of-service" element={<TermsOfService />} />
            <Route
              path="*"
              element={
                <RequireAuth>
                  <Layout>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/content" element={<ContentLibrary />} />
                      <Route path="/content/new" element={<AddContent />} />
                      <Route path="/media" element={<MediaLibrary />} />
                      <Route path="/reviewer" element={<Reviewer />} />
                      <Route path="/performance" element={<Performance />} />
                      <Route path="/instagram" element={<Instagram />} />
                      <Route path="/strategy" element={<Strategy />} />
                      <Route path="/planner" element={<ContentPlanner />} />
                      <Route path="/analytics" element={<Analytics />} />
                      <Route path="/learned" element={<Learned />} />
                      <Route path="/chat" element={<Chat />} />
                      <Route path="/demo" element={<Demo />} />
                      <Route path="*" element={<Dashboard />} />
                    </Routes>
                  </Layout>
                </RequireAuth>
              }
            />
          </Routes>
        </ThemeProvider>
      </HealthProvider>
    </AuthProvider>
  )
}
