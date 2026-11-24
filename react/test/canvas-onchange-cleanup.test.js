// 回归测试：验证 Excalidraw onChange 订阅不会重复注册且清理时会注销监听。
import { describe, expect, it, vi } from 'vitest'
import { subscribeExcalidrawChange } from '../src/hooks/use-excalidraw-change'

describe('subscribeExcalidrawChange', () => {
  it('registers once and invokes unsubscribe on cleanup while forwarding latest handler', () => {
    const unsubscribe = vi.fn()
    let registeredCallback = null
    const mockApi = {
      onChange: vi.fn((cb) => {
        registeredCallback = cb
        return unsubscribe
      }),
    }

    const firstHandler = vi.fn()
    const secondHandler = vi.fn()
    const handlerRef = { current: firstHandler }

    const cleanup = subscribeExcalidrawChange(mockApi, handlerRef)
    expect(mockApi.onChange).toHaveBeenCalledTimes(1)
    expect(typeof cleanup).toBe('function')

    // 模拟最新回调引用切换且无需重绑 onChange
    handlerRef.current = secondHandler
    registeredCallback([], { zoom: { value: 1 } }, {})
    expect(firstHandler).not.toHaveBeenCalled()
    expect(secondHandler).toHaveBeenCalledTimes(1)

    cleanup?.()
    expect(unsubscribe).toHaveBeenCalledTimes(1)
  })
})
