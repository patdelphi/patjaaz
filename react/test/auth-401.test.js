// 回归测试：验证 apiFetch 仅对同源受保护 API 返回 401 时触发 Auth::Unauthorized。
import { describe, expect, it, vi } from 'vitest'
import { apiFetch, shouldEmitUnauthorized } from '../src/lib/apiFetch'
import { eventBus } from '../src/lib/event'

describe('apiFetch 401 handling', () => {
  it('matches only same-origin protected /api/* routes on status 401', () => {
    const origin = 'http://localhost:5174'
    expect(shouldEmitUnauthorized('/api/canvas/list', 401, origin)).toBe(true)
    expect(shouldEmitUnauthorized('http://localhost:5174/api/chat', 401, origin)).toBe(true)

    expect(shouldEmitUnauthorized('/api/auth/login', 401, origin)).toBe(false)
    expect(shouldEmitUnauthorized('/api/auth/status', 401, origin)).toBe(false)
    expect(shouldEmitUnauthorized('/api/canvas/list', 404, origin)).toBe(false)
    expect(shouldEmitUnauthorized('https://evil.com/api/canvas/list', 401, origin)).toBe(false)
    expect(shouldEmitUnauthorized('/other/path', 401, origin)).toBe(false)
  })

  it('emits Auth::Unauthorized when a protected API responds with 401', async () => {
    const handler = vi.fn()
    eventBus.on('Auth::Unauthorized', handler)
    try {
      const fakeFetch = vi.fn(async () => new Response('{"detail":"Login required"}', { status: 401 }))
      await apiFetch('/api/canvas/list', undefined, fakeFetch)
      expect(handler).toHaveBeenCalledTimes(1)
      expect(handler).toHaveBeenCalledWith({ url: '/api/canvas/list', status: 401 })

      await apiFetch('/api/auth/login', undefined, fakeFetch)
      expect(handler).toHaveBeenCalledTimes(1)
    } finally {
      eventBus.off('Auth::Unauthorized', handler)
    }
  })
})
