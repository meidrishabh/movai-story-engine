import { env } from '../../config/env'

/** An error response from the API. `message` is the server's `detail` when it sent one. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (body.detail !== undefined) return JSON.stringify(body.detail)
  } catch {
    // The body was not JSON; fall back to the status text.
  }
  return response.statusText || `Request failed (${response.status})`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData
  const headers = new Headers(init.headers)
  if (init.body !== undefined && !isForm) headers.set('content-type', 'application/json')

  let response: Response
  try {
    response = await fetch(`${env.apiUrl}/api/v1${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${env.apiUrl}. Is it running?`)
  }
  if (!response.ok) throw new ApiError(response.status, await readDetail(response))
  return (response.status === 204 ? undefined : await response.json()) as T
}

const json = (body: unknown) => (body === undefined ? undefined : JSON.stringify(body))

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: json(body) }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body: json(body) }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body: json(body) }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
}

/** Items come back as `{ count, items }` from list endpoints. */
export interface Listed<T> {
  count: number
  items: T[]
}
