import assert from 'node:assert/strict'
import { test } from 'node:test'

import { startInstagramConnect } from '../src/utils/connect.ts'
import type { InstagramAuthorizeResponse } from '../src/utils/connect.ts'

/** Minimal Axios-shaped failure as the real client would throw it. */
function axiosError(status: number, detail: string): Error {
  const error = new Error(detail) as Error & {
    isAxiosError: boolean
    response: { status: number; data: { detail: string } }
  }
  error.isAxiosError = true
  error.response = { status, data: { detail } }
  return error
}

function networkError(): Error {
  const error = new Error('Network Error') as Error & { isAxiosError: boolean; code: string }
  error.isAxiosError = true
  error.code = 'ERR_NETWORK'
  return error
}

/** Records what the Connect button handler does, with no DOM or router. */
function harness(requestAuthorize: () => Promise<{ data: InstagramAuthorizeResponse }>) {
  const assigned: string[] = []
  const navigated: string[] = []
  const errors: string[] = []
  let sessionExpired = 0

  const deps = {
    requestAuthorize,
    navigate: (path: string) => navigated.push(path),
    assign: (url: string) => assigned.push(url),
    onSessionExpired: () => {
      sessionExpired += 1
    },
    onError: (message: string) => errors.push(message),
  }

  return { deps, assigned, navigated, errors, expired: () => sessionExpired }
}

test('valid token: opens the Meta authorize URL and does not redirect locally', async () => {
  const url = 'https://www.instagram.com/oauth/authorize?client_id=123&response_type=code'
  const h = harness(async () => ({ data: { authorize_url: url } }))

  await startInstagramConnect(h.deps)

  assert.deepEqual(h.assigned, [url])
  assert.deepEqual(h.navigated, [])
  assert.deepEqual(h.errors, [])
  assert.equal(h.expired(), 0)
})

test('missing/invalid token (401): clears the session and goes to /login', async () => {
  const h = harness(async () => {
    throw axiosError(401, 'Not authenticated')
  })

  await startInstagramConnect(h.deps)

  assert.equal(h.expired(), 1)
  assert.deepEqual(h.navigated, ['/login'])
  assert.deepEqual(h.assigned, [])
  assert.deepEqual(h.errors, [])
})

test('not-configured (503): surfaces an error instead of logging the user out', async () => {
  const h = harness(async () => {
    throw axiosError(503, 'Instagram integration not configured.')
  })

  await startInstagramConnect(h.deps)

  assert.deepEqual(h.errors, ['Instagram integration not configured.'])
  assert.deepEqual(h.navigated, [])
  assert.deepEqual(h.assigned, [])
  assert.equal(h.expired(), 0)
})

test('a response without an authorize_url is an error and never navigates', async () => {
  const h = harness(async () => ({ data: {} }))

  await startInstagramConnect(h.deps)

  assert.equal(h.errors.length, 1)
  assert.match(h.errors[0], /authorization URL/i)
  assert.deepEqual(h.assigned, [])
  assert.deepEqual(h.navigated, [])
})

test('a network failure is surfaced without clearing the session', async () => {
  const h = harness(async () => {
    throw networkError()
  })

  await startInstagramConnect(h.deps)

  assert.equal(h.errors.length, 1)
  assert.equal(h.expired(), 0)
  assert.deepEqual(h.navigated, [])
})
