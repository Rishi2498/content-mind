import axios from 'axios'

import { getStoredToken } from './utils/tokenStore.ts'

export { apiErrorMessage, apiErrorStatus } from './utils/apiError.ts'

// `import.meta.env` only exists under Vite. Optional chaining keeps this module
// importable by the dependency-free Node test runner as well.
const viteEnv = (import.meta as unknown as { env?: Record<string, string | undefined> }).env

/**
 * In dev, Vite proxies /api to the FastAPI server (see vite.config.ts), so the
 * base URL stays relative and CORS never enters the picture. `VITE_API_BASE_URL`
 * can override it, but nothing does today, so requests always hit this app's
 * own /api — never a stale localhost or tunnel host.
 */
export const api = axios.create({
  baseURL: viteEnv?.VITE_API_BASE_URL ?? '/api',
  timeout: 30_000,
})

/**
 * Attach the stored JWT to every request. Doing this in an interceptor (rather
 * than by mutating `api.defaults.headers` from a React effect) makes the
 * `Authorization: Bearer <token>` header deterministic for all callers,
 * including the protected `GET /instagram/authorize` the Connect button uses.
 */
api.interceptors.request.use((config) => {
  const token = getStoredToken()
  if (token && config.headers) {
    if (typeof config.headers.set === 'function') config.headers.set('Authorization', `Bearer ${token}`)
    else (config.headers as Record<string, string>).Authorization = `Bearer ${token}`
  }
  return config
})
