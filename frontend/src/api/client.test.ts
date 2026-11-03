import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request } from './client'

function respond(status: number, body: unknown) {
  return vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

afterEach(() => vi.unstubAllGlobals())

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  const err = await promise.then(
    () => { throw new Error('expected the request to fail') },
    (e: unknown) => e,
  )
  expect(err).toBeInstanceOf(ApiError)
  return err as ApiError
}

describe('request error handling', () => {
  it('surfaces the backend 429 message and request id (standard error shape)', async () => {
    vi.stubGlobal('fetch', respond(429, { detail: 'Too many requests (10 per 1 minute). Try again in up to 60 seconds.', error_category: 'rate_limited', request_id: 'req-1' }))
    const err = await failure(request('/auth/me'))
    expect(err.status).toBe(429)
    expect(err.message).toContain('Too many requests')
    expect(err.requestId).toBe('req-1')
  })

  it('joins validation errors without echoing submitted values', async () => {
    vi.stubGlobal('fetch', respond(422, { detail: [{ loc: ['body', 'password'], msg: 'Field required', type: 'missing' }], request_id: 'req-2' }))
    const err = await failure(request('/auth/login', { method: 'POST', body: '{}' }))
    expect(err.message).toBe('body.password: Field required')
  })

  it('falls back to a generic message when the body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502 })))
    const err = await failure(request('/events'))
    expect(err.status).toBe(502)
    expect(err.message).toBe('Request failed with status 502')
  })

  it('sends JSON bodies with a JSON content type to the relative API base', async () => {
    const fetchMock = respond(200, { ok: true })
    vi.stubGlobal('fetch', fetchMock)
    await request('/sources', { method: 'POST', body: JSON.stringify({ name: 'x' }) })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/sources')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })
})

describe('cookie-mode session handling', () => {
  it('never stores tokens in localStorage and keeps the access token in memory', async () => {
    const { setAccessToken, getAccessToken, clearTokens } = await import('./client')
    const spy = vi.spyOn(Storage.prototype, 'setItem')
    setAccessToken('in-memory-token')
    expect(getAccessToken()).toBe('in-memory-token')
    expect(spy).not.toHaveBeenCalled()
    clearTokens()
    expect(getAccessToken()).toBeNull()
  })

  it('refreshes with the session header and same-origin credentials, once for concurrent 401s', async () => {
    const { setAccessToken, getAccessToken } = await import('./client')
    setAccessToken('expired')
    let refreshCalls = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/auth/refresh') {
        refreshCalls += 1
        expect(new Headers(init?.headers).get('X-Session-Mode')).toBe('cookie')
        expect(init?.credentials).toBe('same-origin')
        return new Response(JSON.stringify({ access_token: 'fresh', refresh_token: null }), { status: 200 })
      }
      const auth = new Headers(init?.headers).get('Authorization')
      return auth === 'Bearer fresh'
        ? new Response(JSON.stringify({ ok: true }), { status: 200 })
        : new Response(JSON.stringify({ detail: 'expired' }), { status: 401 })
    }))
    const results = await Promise.all([request('/events'), request('/sensors'), request('/assets')])
    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }])
    expect(refreshCalls).toBe(1)
    expect(getAccessToken()).toBe('fresh')
  })

  it('does not try to refresh when an /auth/ call itself returns 401 (wrong password)', async () => {
    const fetchMock = respond(401, { detail: 'Invalid credentials' })
    vi.stubGlobal('fetch', fetchMock)
    const err = await failure(request('/auth/login', { method: 'POST', body: '{}' }))
    expect(err.status).toBe(401)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('transient refresh failures', () => {
  it('a rate-limited refresh keeps the session; only 401 ends it', async () => {
    const { setAccessToken, getAccessToken, tryRefresh, SESSION_EXPIRED_EVENT } = await import('./client')
    const expired = vi.fn()
    window.addEventListener(SESSION_EXPIRED_EVENT, expired)
    setAccessToken('still-valid')
    vi.stubGlobal('fetch', respond(429, { detail: 'Too many requests' }))
    expect(await tryRefresh()).toBe(false)
    expect(getAccessToken()).toBe('still-valid')
    expect(expired).not.toHaveBeenCalled()

    vi.stubGlobal('fetch', respond(401, { detail: 'Session has been revoked' }))
    expect(await tryRefresh()).toBe(false)
    expect(getAccessToken()).toBeNull()
    expect(expired).toHaveBeenCalledTimes(1)
    window.removeEventListener(SESSION_EXPIRED_EVENT, expired)
  })
})
