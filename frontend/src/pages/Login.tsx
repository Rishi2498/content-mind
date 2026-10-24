import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { apiErrorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Card, ErrorNote, SectionHeader } from '../components/ui'

export function Login() {
  const { token, login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (token) return <Navigate to="/" replace />

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(email, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-bg-primary to-bg-secondary p-4">
      <Card className="mx-auto max-w-md w-full p-8">
        <SectionHeader title="Sign in" subtitle="Access your ContentMind workspace." />
        <form onSubmit={submit} className="flex flex-col gap-6">
          {error && <ErrorNote message={error} />}
          <div className="space-y-3">
            <label className="block text-sm font-medium text-text-primary">
              <span className="required text-text-error">*</span> Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              className="field w-full"
              placeholder="you@company.com"
            />
          </div>
          <div className="space-y-3">
            <label className="block text-sm font-medium text-text-primary">
              <span className="required text-text-error">*</span> Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="field w-full"
              placeholder="••••••••"
            />
          </div>
          <button type="submit" disabled={submitting} className="btn btn-primary w-full">
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="mt-6 text-center text-sm text-ink-400">
          No account yet?{' '}
          <Link to="/signup" className="text-brand-400 hover:underline">
            Create one
          </Link>
        </p>
      </Card>
    </div>
  )
}
