/**
 * Single source of truth for the stored access token.
 *
 * The API client reads it on every request (see `api.ts`) so the
 * `Authorization` header never depends on React lifecycle timing, and
 * `AuthContext` reads/writes it on login/logout. Keeping the key in one place
 * stops the writer and reader from drifting apart.
 */
export const TOKEN_KEY = 'contentmind_token'

type TokenStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function storage(): TokenStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    // Access can throw in sandboxed/blocked-storage environments.
    return null
  }
}

export function getStoredToken(): string | null {
  return storage()?.getItem(TOKEN_KEY) ?? null
}

export function setStoredToken(token: string | null): void {
  const store = storage()
  if (!store) return
  if (token) store.setItem(TOKEN_KEY, token)
  else store.removeItem(TOKEN_KEY)
}
