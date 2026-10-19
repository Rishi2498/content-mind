import assert from 'node:assert/strict'
import { test } from 'node:test'

import { parseOAuthCallback } from '../src/utils/oauth.ts'

test('a connected callback exposes the local connection id', () => {
  const result = parseOAuthCallback(new URLSearchParams('connected=42'))

  assert.equal(result.status, 'connected')
  assert.equal(result.connectionId, '42')
})

test('a provider denial is reported as cancelled, not an error', () => {
  const result = parseOAuthCallback(
    new URLSearchParams('error=User+denied+the+request&error_code=access_denied'),
  )

  assert.equal(result.status, 'cancelled')
  assert.match(result.message, /cancel/i)
})

test('a token exchange failure is surfaced as an error message', () => {
  const result = parseOAuthCallback(
    new URLSearchParams('error=Failed+to+exchange+token&error_code=token_exchange_failed'),
  )

  assert.equal(result.status, 'error')
  assert.match(result.message, /Failed to exchange token/)
})

test('no callback parameters yields none', () => {
  const result = parseOAuthCallback(new URLSearchParams(''))

  assert.equal(result.status, 'none')
})
