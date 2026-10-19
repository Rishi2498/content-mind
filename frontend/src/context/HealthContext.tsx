import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { api, apiErrorMessage } from '../api'
import type { HealthResponse } from '../types'

interface AppState {
  health: HealthResponse | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

const HealthContext = createContext<AppState>({
  health: null,
  loading: true,
  error: null,
  refresh: async () => {},
})

/**
 * Health is polled app-wide because the memory backend state is load-bearing:
 * every recommendation, gap, and plan is qualified by whether Hindsight is
 * actually serving it.
 */
export function HealthProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<HealthResponse>('/health')
      setHealth(data)
      setError(null)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 30_000)
    return () => clearInterval(timer)
  }, [refresh])

  return (
    <HealthContext.Provider value={{ health, loading, error, refresh }}>
      {children}
    </HealthContext.Provider>
  )
}

export function useHealth(): AppState {
  return useContext(HealthContext)
}
