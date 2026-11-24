// 回归测试：验证参数化块箭头的闭合多边形顶点生成、元素属性及缩放重算逻辑。
import { describe, expect, it } from 'vitest'
import {
  createBlockArrowElement,
  generateBlockArrowPoints,
  isBlockArrowElement,
  recomputeResizedBlockArrows,
} from '../src/lib/blockArrow'

describe('blockArrow geometry and resize recalculation', () => {
  it('generates closed polygon loops within bounds for straight, double, and curved variants', () => {
    for (const variant of ['straight', 'double', 'curved']) {
      const pts = generateBlockArrowPoints(240, 100, { variant })
      expect(pts.length).toBeGreaterThanOrEqual(8)
      // 首尾坐标必须精确重合，保证 Excalidraw 判定为闭合实色多边形
      expect(pts[0]).toEqual(pts[pts.length - 1])
      for (const [x, y] of pts) {
        expect(Number.isFinite(x)).toBe(true)
        expect(Number.isFinite(y)).toBe(true)
        expect(x).toBeGreaterThanOrEqual(0)
        expect(x).toBeLessThanOrEqual(240.01)
        expect(y).toBeGreaterThanOrEqual(0)
        expect(y).toBeLessThanOrEqual(100.01)
      }
    }
  })

  it('creates valid block-arrow line elements with roundness null and roughness 0', () => {
    const el = createBlockArrowElement({ x: 100, y: 200, variant: 'double', seed: 42, now: 1000 })
    expect(el.type).toBe('line')
    expect(el.roundness).toBeNull()
    expect(el.roughness).toBe(0)
    expect(el.fillStyle).toBe('solid')
    expect(isBlockArrowElement(el)).toBe(true)
    expect(el.customData.variant).toBe('double')
  })

  it('recomputes vertices only when element dimensions changed beyond 1px', () => {
    const original = createBlockArrowElement({
      x: 10,
      y: 20,
      width: 240,
      height: 96,
      variant: 'straight',
      seed: 9,
      now: 1000,
    })

    // 尺寸未变时不触发场景重写
    expect(recomputeResizedBlockArrows([original], 1001)).toBeNull()

    // 非等比拉伸至 420x140 后应按参数重算点阵并同步 lastWidth / lastHeight
    const resized = { ...original, width: 420, height: 140 }
    const nextList = recomputeResizedBlockArrows([resized], 2000)
    expect(nextList).not.toBeNull()
    const updated = nextList[0]
    expect(updated.version).toBe(original.version + 1)
    expect(updated.customData.lastWidth).toBe(420)
    expect(updated.customData.lastHeight).toBe(140)
    expect(updated.points[0]).toEqual(updated.points[updated.points.length - 1])
    expect(Math.max(...updated.points.map(([px]) => px))).toBeCloseTo(420, 1)

    // 更新后再次检查不再重复触发
    expect(recomputeResizedBlockArrows(nextList, 2001)).toBeNull()
  })
})
