import { apiErrorMessage, apiErrorStatus } from './apiError.ts'

/** Shape of `GET /instagram/authorize` (only the field we consume). */
export interface InstagramAuthorizeResponse {
  authorize_url?: string
}

/**
 * Everything the Connect Instagram button needs, injected so the flow can be
 * unit tested without a DOM, a router or a live network.
 */
export interface ConnectInstagramDeps {
  /** Fetch the authorize URL through the JWT-carrying API client. */
  requestAuthorize: () => Promise<{ data: InstagramAuthorizeResponse }>
  /** Navigate within the SPA (react-router). */
  navigate: (path: string) => void
  /** Hand the whole browser tab over to Meta. */
  assign: (url: string) => void
  /** Clear the (now unusable) session before sending the user to log in. */
  onSessionExpired: () => void
  onError: (message: string) => void
}

/**
 * Fetch the Instagram authorization URL with the caller's JWT and send the
 * browser to Meta. This is the exact logic the Connect button runs, so it is
 * covered by tests.
 *
 * A 401 means the stored token is missing or no longer valid. We clear it
 * before redirecting to /login: otherwise `Login` sees a still-present token
 * and immediately bounces the user back to the dashboard (no real re-login).
 */
export async function startInstagramConnect(deps: ConnectInstagramDeps): Promise<void> {
  try {
    const resp = await deps.requestAuthorize()
    const url = resp.data?.authorize_url
    if (!url) {
      deps.onError('The server did not return an Instagram authorization URL.')
      return
    }
    deps.assign(url)
  } catch (error) {
    if (apiErrorStatus(error) === 401) {
      deps.onSessionExpired()
      deps.navigate('/login')
      return
    }
    deps.onError(apiErrorMessage(error))
  }
}
