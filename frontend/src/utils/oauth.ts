/**
 * Interpretation of the query string the backend appends when it redirects the
 * browser back from the Instagram OAuth callback:
 *
 *   success  ->  ?connected=<local connection id>
 *   failure  ->  ?error=<message>&error_code=<machine code>
 *
 * Kept as a pure function so it can be unit tested without a DOM and so the
 * page component stays focused on rendering.
 */
export interface OAuthCallbackResult {
  status: 'connected' | 'cancelled' | 'error' | 'none'
  /** Human-readable message for the UI. Never contains tokens or secrets. */
  message: string
  /** The local ContentMind connection id when status is "connected". */
  connectionId?: string
}

export function parseOAuthCallback(params: URLSearchParams): OAuthCallbackResult {
  const connected = params.get('connected')
  if (connected) {
    return {
      status: 'connected',
      message: 'Instagram account connected successfully.',
      connectionId: connected,
    }
  }

  const error = params.get('error')
  if (error) {
    const code = params.get('error_code') ?? ''
    // Meta sends error=access_denied when the user rejects the consent screen.
    const cancelled =
      code === 'access_denied' ||
      code === 'user_cancelled' ||
      /denied|cancel/i.test(error)
    return {
      status: cancelled ? 'cancelled' : 'error',
      message: cancelled ? 'Instagram connection was cancelled.' : error,
    }
  }

  return { status: 'none', message: '' }
}
