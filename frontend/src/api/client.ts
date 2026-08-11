/**
 * HTTP client.
 *
 * The session is an HttpOnly cookie set by `POST /auth/login` and `/register`
 * (`backend/app/api/routers/auth.py::_set_session_cookie`), so script cannot
 * read it and there is no token to attach by hand. Every request therefore sets
 * `credentials: 'include'`. The backend's CORS middleware runs with
 * `allow_credentials=True` and an explicit origin allowlist, so this works
 * cross-origin too — but the dev server proxies `/api` to keep the browser on
 * one origin, which avoids the SameSite=Lax cookie being dropped.
 *
 * There is no `axios` here and no interceptor stack: the only cross-cutting
 * concerns are credentials and error shaping, both of which fit in this file.
 */

const BASE = '/api/v1'

/**
 * A failed request, with the backend's own message preserved.
 *
 * The upload and analysis routes author their `detail` strings for users
 * (`ingest.InvalidUpload`, the unsupported-model 422, the 409 on results for an
 * incomplete run). Replacing them with a generic string would throw away the
 * only part of the error that tells someone what to change.
 */
export class ApiError extends Error {
  readonly status: number
  /** FastAPI's `detail`, normalised. Pydantic validation errors arrive as arrays. */
  readonly detail: string
  readonly fieldErrors: { field: string; message: string }[]

  constructor(status: number, detail: string, fieldErrors: { field: string; message: string }[] = []) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.fieldErrors = fieldErrors
  }

  get isUnauthenticated(): boolean {
    return this.status === 401
  }
}

interface PydanticError {
  loc?: unknown[]
  msg?: string
}

function normaliseDetail(body: unknown, status: number): {
  detail: string
  fieldErrors: { field: string; message: string }[]
} {
  if (body != null && typeof body === 'object' && 'detail' in body) {
    const raw = (body as { detail: unknown }).detail
    if (typeof raw === 'string') return { detail: raw, fieldErrors: [] }
    if (Array.isArray(raw)) {
      const fieldErrors = raw.map((entry) => {
        const e = entry as PydanticError
        const loc = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body') : []
        return {
          field: loc.map(String).join('.') || 'request',
          message: typeof e.msg === 'string' ? e.msg : 'is invalid',
        }
      })
      return {
        detail: fieldErrors.map((f) => `${f.field}: ${f.message}`).join('; '),
        fieldErrors,
      }
    }
  }
  return { detail: `Request failed with status ${status}`, fieldErrors: [] }
}

async function handle<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  const text = await response.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = null
    }
  }
  if (!response.ok) {
    const { detail, fieldErrors } = normaliseDetail(body, response.status)
    throw new ApiError(response.status, detail, fieldErrors)
  }
  return body as T
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { credentials: 'include', ...init })
  } catch {
    // A network-level failure is not a 500 and must not be reported as one.
    throw new ApiError(0, 'Could not reach the API. It may be down, or this browser may be offline.')
  }
  return handle<T>(response)
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET' })
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' })
}

/** Multipart. No Content-Type header — the browser must set the boundary. */
export function postForm<T>(path: string, form: FormData): Promise<T> {
  return request<T>(path, { method: 'POST', body: form })
}
