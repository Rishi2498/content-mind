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
    <>
      <SectionHeader title="Sign in" subtitle="Access your ContentMind workspace." />
      <Card className="mx-auto max-w-md">
        <form onSubmit={submit} className="flex flex-col gap-4">
          {error && <ErrorNote message={error} />}
          <label className="block">
            <span className="label">Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="field"
              placeholder="you@company.com"
            />
          </label>
          <label className="block">
            <span className="label">Password</span>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="field"
              placeholder="••••••••"
            />
          </label>
          <button type="submit" disabled={submitting} className="btn btn-primary mt-2">
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="mt-4 text-center text-sm text-ink-400">
          No account yet?{' '}
          <Link to="/signup" className="text-brand-400 hover:underline">
            Create one
          </Link>
        </p>
      </Card>
    </>
  )
}
