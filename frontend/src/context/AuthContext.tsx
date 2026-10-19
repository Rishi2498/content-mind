import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { api } from '../api'
import { getStoredToken, setStoredToken } from '../utils/tokenStore'

const EMAIL_KEY = 'contentmind_email'

interface AuthState {
  token: string | null
  email: string | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getStoredToken())
  const [email, setEmail] = useState<string | null>(() => localStorage.getItem(EMAIL_KEY))
  const [loading, setLoading] = useState(true)

  // The API client attaches the token itself (see api.ts), so here we only
  // need to signal that the initial auth read is complete.
  useEffect(() => {
    setLoading(false)
  }, [])

  const login = useCallback(async (addr: string, password: string) => {
    const form = new URLSearchParams()
    form.set('username', addr)
    form.set('password', password)
    const { data } = await api.post<{ access_token: string; token_type: string }>(
      '/auth/login',
      form,
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } },
    )
    setStoredToken(data.access_token)
    localStorage.setItem(EMAIL_KEY, addr)
    setToken(data.access_token)
    setEmail(addr)
  }, [])

  const signup = useCallback(async (addr: string, password: string) => {
    await api.post('/auth/signup', { email: addr, password })
    await login(addr, password)
  }, [login])

  const logout = useCallback(() => {
    setStoredToken(null)
    localStorage.removeItem(EMAIL_KEY)
    setToken(null)
    setEmail(null)
  }, [])

  const value = useMemo(
    () => ({ token, email, loading, login, signup, logout }),
    [token, email, loading, login, signup, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
