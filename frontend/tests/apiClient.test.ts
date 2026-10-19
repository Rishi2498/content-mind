import assert from 'node:assert/strict'
import { afterEach, beforeEach, test } from 'node:test'

import type { InternalAxiosRequestConfig } from 'axios'

import { api } from '../src/api.ts'
import { TOKEN_KEY } from '../src/utils/tokenStore.ts'

/** In-memory stand-in for window.localStorage under Node. */
class MemoryStorage {
  private data = new Map<string, string>()
  getItem(key: string): string | null {
    return this.data.has(key) ? (this.data.get(key) as string) : null
  }
  setItem(key: string, value: string): void {
    this.data.set(key, String(value))
  }
  removeItem(key: string): void {
    this.data.delete(key)
  }
}

const originalAdapter = api.defaults.adapter
let captured: InternalAxiosRequestConfig | undefined

beforeEach(() => {
  ;(globalThis as { localStorage?: unknown }).localStorage = new MemoryStorage()
  captured = undefined
  // Capture the fully merged config instead of making a real request.
  api.defaults.adapter = async (config) => {
    captured = config
    return { data: null, status: 200, statusText: 'OK', headers: {}, config }
  }
})

afterEach(() => {
  api.defaults.adapter = originalAdapter
  delete (globalThis as { localStorage?: unknown }).localStorage
})

function authHeader(): string | undefined {
  const headers = captured?.headers as unknown as
    | { Authorization?: string; authorization?: string; get?: (name: string) => string | undefined }
    | undefined
  if (!headers) return undefined
  if (typeof headers.get === 'function') return headers.get('Authorization')
  return headers.Authorization ?? headers.authorization
}

test('the API client targets this app origin (/api), never a stale host', () => {
  assert.equal(api.defaults.baseURL, '/api')
})

test('a stored token is sent as Authorization: Bearer <token>', async () => {
  ;(globalThis.localStorage as MemoryStorage).setItem(TOKEN_KEY, 'test-jwt')
  await api.get('/instagram/authorize')

  assert.equal(captured?.url, '/instagram/authorize')
  assert.equal(authHeader(), 'Bearer test-jwt')
})

test('without a stored token no Authorization header is sent', async () => {
  await api.get('/instagram/authorize')

  assert.equal(captured?.url, '/instagram/authorize')
  assert.equal(authHeader(), undefined)
})
