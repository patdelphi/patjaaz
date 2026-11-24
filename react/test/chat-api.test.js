// 聊天提交 API 的接收确认和 HTTP 错误处理回归测试。
import { afterEach, describe, expect, it, vi } from 'vitest'
import { sendMessages } from '../src/api/chat'

const payload = {
  sessionId: 'session-test',
  canvasId: 'canvas-test',
  newMessages: [{ role: 'user', content: 'hello' }],
  textModel: { model: 'mock', provider: 'mock' },
  toolList: [],
  systemPrompt: null,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('sendMessages', () => {
  it('returns the accepted task response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: 'accepted', session_id: 'session-test' }), {
          status: 202,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    )

    await expect(sendMessages(payload)).resolves.toEqual({
      status: 'accepted',
      session_id: 'session-test',
    })
  })

  it('throws a readable server error for a failed submission', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'invalid session' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    )

    await expect(sendMessages(payload)).rejects.toThrow('invalid session')
  })
})
