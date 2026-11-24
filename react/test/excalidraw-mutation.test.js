// 回归测试：验证 mutateSceneElements 自动递增版本号、nonce、时间戳并传递 IMMEDIATELY。
import { describe, expect, it, vi } from 'vitest'
import { bumpElementVersion, mutateSceneElements } from '../src/lib/excalidrawMutation'

describe('excalidrawMutation', () => {
  it('increments version, updates versionNonce and timestamp when modifying elements', () => {
    const el1 = { id: 't1', type: 'text', version: 3, versionNonce: 10, updated: 100, backgroundColor: 'transparent' }
    const el2 = { id: 'r1', type: 'rectangle', version: 5, versionNonce: 20, updated: 100 }
    const updateScene = vi.fn()
    const api = {
      getSceneElements: () => [el1, el2],
      updateScene,
    }

    const changed = mutateSceneElements(
      api,
      (el) => (el.id === 't1' ? { ...el, backgroundColor: '#FFF2CC' } : el),
      { now: 9999 }
    )

    expect(changed).toBe(true)
    expect(updateScene).toHaveBeenCalledTimes(1)
    const arg = updateScene.mock.calls[0][0]
    expect(arg.captureUpdate).toBe('IMMEDIATELY')
    expect(arg.elements[0].backgroundColor).toBe('#FFF2CC')
    expect(arg.elements[0].version).toBe(4)
    expect(arg.elements[0].updated).toBe(9999)
    expect(typeof arg.elements[0].versionNonce).toBe('number')
    expect(arg.elements[1]).toBe(el2)
  })

  it('skips updateScene when no element reference changed and no appState was provided', () => {
    const el = bumpElementVersion({ id: 'a', type: 'arrow', version: 1, versionNonce: 1, updated: 1 }, 500)
    const updateScene = vi.fn()
    const changed = mutateSceneElements({ getSceneElements: () => [el], updateScene }, (item) => item)

    expect(changed).toBe(false)
    expect(updateScene).not.toHaveBeenCalled()
  })
})
