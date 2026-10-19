import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { apiErrorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { Card, ErrorNote, SectionHeader } from '../components/ui'

export function Signup() {
  const { token, signup } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (token) return <Navigate to="/" replace />

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await signup(email, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <SectionHeader
        title="Create your account"
        subtitle="Each workspace gets its own isolated memory."
      />
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
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="field"
              placeholder="At least 8 characters"
            />
          </label>
          <label className="block">
            <span className="label">Confirm password</span>
            <input
              type="password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="field"
              placeholder="Repeat your password"
            />
          </label>
          <button type="submit" disabled={submitting} className="btn btn-primary mt-2">
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>
        <p className="mt-4 text-center text-sm text-ink-400">
          Already have an account?{' '}
          <Link to="/login" className="text-brand-400 hover:underline">
            Sign in
          </Link>
        </p>
      </Card>
    </>
  )
}
