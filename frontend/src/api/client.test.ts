/**
 * The CSRF echo, and the two things about it that are easy to break.
 *
 * The backend refuses a cookie-authenticated mutation that does not carry the
 * header, so a client that stops sending it fails every save with a 403 — and
 * the failure is nowhere near this file. These tests are the near-side guard.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { csrfToken, get, post, postForm } from './client'

function setCookie(value: string | null) {
  // jsdom's document.cookie is append-only; expiring is the way to clear one.
  document.cookie = 'irtboss_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
  if (value !== null) document.cookie = `irtboss_csrf=${value}; path=/`
}

function stubFetch() {
  const fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function initOf(fetchMock: ReturnType<typeof stubFetch>): RequestInit {
  const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit] | undefined
  expect(call).toBeDefined()
  return call![1]
}

function headersOf(fetchMock: ReturnType<typeof stubFetch>): Headers {
  return new Headers(initOf(fetchMock).headers)
}

afterEach(() => {
  setCookie(null)
  vi.unstubAllGlobals()
})

describe('csrfToken', () => {
  it('reads the cookie the backend leaves readable', () => {
    setCookie('a-token-value')
    expect(csrfToken()).toBe('a-token-value')
  })

  it('is null when there is no session', () => {
    setCookie(null)
    expect(csrfToken()).toBeNull()
  })

  it('decodes a percent-encoded value', () => {
    setCookie(encodeURIComponent('to+ken/with=chars'))
    expect(csrfToken()).toBe('to+ken/with=chars')
  })

  it('is not confused by another cookie whose name ends the same way', () => {
    document.cookie = 'not_irtboss_csrf=decoy; path=/'
    setCookie('the-real-one')
    expect(csrfToken()).toBe('the-real-one')
    document.cookie = 'not_irtboss_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
  })
})

describe('request', () => {
  it('echoes the token on a POST', async () => {
    setCookie('token-123')
    const fetchMock = stubFetch()

    await post('/projects', { name: 'x' })

    expect(headersOf(fetchMock).get('X-CSRF-Token')).toBe('token-123')
  })

  it('sends no header on a GET', async () => {
    setCookie('token-123')
    const fetchMock = stubFetch()

    await get('/projects')

    expect(headersOf(fetchMock).has('X-CSRF-Token')).toBe(false)
  })

  it('leaves multipart uploads without a Content-Type', async () => {
    // The browser has to set the multipart boundary, so this header must stay
    // absent even though the CSRF one is now added alongside it.
    setCookie('token-123')
    const fetchMock = stubFetch()

    await postForm('/datasets', new FormData())

    const headers = headersOf(fetchMock)
    expect(headers.get('X-CSRF-Token')).toBe('token-123')
    expect(headers.has('Content-Type')).toBe(false)
  })

  it('still sends credentials', async () => {
    setCookie('token-123')
    const fetchMock = stubFetch()

    await post('/projects', { name: 'x' })

    expect(initOf(fetchMock).credentials).toBe('include')
  })
})
