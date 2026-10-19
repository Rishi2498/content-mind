import axios from 'axios'

/**
 * Pure helpers for turning Axios failures into something the UI can show.
 * They live outside `api.ts` so they can be imported (and unit tested) without
 * pulling in the app's Axios instance, which reads `import.meta.env`.
 */

/** HTTP status of an API error, if the failure came from a response. */
export function apiErrorStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined
}

/**
 * Turn a FastAPI error into a message worth showing a user. 422 validation
 * errors arrive as a list of field problems, which we flatten.
 */
export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { detail?: string | unknown[] } | undefined
    if (Array.isArray(data?.detail)) {
      return data.detail
        .map((d) => {
          const item = d as { loc?: string[]; msg?: string }
          const field = item.loc?.filter((p) => p !== 'body').join('.') ?? ''
          return field ? `${field}: ${item.msg}` : (item.msg ?? 'invalid value')
        })
        .join('; ')
    }
    if (typeof data?.detail === 'string') return data.detail
    if (error.code === 'ECONNABORTED') return 'The request timed out.'
    if (!error.response) {
      return 'Cannot reach the ContentMind API. Is the backend running on port 8010?'
    }
    return `Request failed with status ${error.response.status}`
  }
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
