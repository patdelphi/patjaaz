// 回归测试：验证 Excalidraw 粗箭头缩放公式、防裁剪 padding、虚线缩放、锚点补丁及版本校验。
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  applyExcalidrawPatches,
  computeArrowheadAngle,
  computeArrowheadScale,
  computeCanvasPadding,
  computeDashArrayDashed,
  computeDashArrayDotted,
  markers,
  patchArrowDev,
  patchArrowProd,
} from '../scripts/patch-excalidraw.mjs'

describe('Excalidraw thick arrow patch', () => {
  it('computes arrowhead scale, open-arrow angle, canvas padding, and dash arrays', () => {
    expect(computeArrowheadScale(2)).toBe(1)
    expect(computeArrowheadScale(4)).toBe(1)
    expect(computeArrowheadScale(16)).toBeCloseTo(2.8)

    expect(computeArrowheadAngle('arrow', 22, 4)).toBe(22)
    expect(computeArrowheadAngle('arrow', 22, 16)).toBeCloseTo(29.2)
    expect(computeArrowheadAngle('arrow', 22, 64)).toBe(30)
    expect(computeArrowheadAngle('triangle', 22, 16)).toBe(22)

    expect(computeCanvasPadding({ type: 'arrow', strokeWidth: 16 })).toBe(96)
    expect(computeCanvasPadding({ type: 'arrow', strokeWidth: 2 })).toBe(20)
    expect(computeCanvasPadding({ type: 'line', strokeWidth: 12 })).toBe(36)
    expect(computeCanvasPadding({ type: 'rectangle', strokeWidth: 16 })).toBe(44)
    expect(computeCanvasPadding({ type: 'text', fontSize: 32 })).toBe(16)

    expect(computeDashArrayDashed(2)).toEqual([8, 10])
    expect(computeDashArrayDashed(16)).toEqual([40, 32])
    expect(computeDashArrayDotted(2)).toEqual([1.5, 8])
    expect(computeDashArrayDotted(16)).toEqual([9.6, 28.8])
  })

  it('patches dev and prod arrow helpers idempotently', () => {
    const devSource = [
      'const size = getArrowheadSize(arrowhead);',
      'const angle = getArrowheadAngle(arrowhead);',
      'var getCanvasPadding = (element) => {',
      '  switch (element.type) {',
      '    case "freedraw":',
      '      return element.strokeWidth * 12;',
      '    case "text":',
      '      return element.fontSize / 2;',
      '    default:',
      '      return 20;',
      '  }',
      '};',
      'var getDashArrayDashed = (strokeWidth) => [8, 8 + strokeWidth];',
      'var getDashArrayDotted = (strokeWidth) => [1.5, 6 + strokeWidth];',
    ].join('\n')

    const patchedDev = patchArrowDev(devSource)
    expect(patchedDev).toContain(markers.arrowSizeDev)
    expect(patchedDev).toContain('case "arrow":\n      return Math.max(20, element.strokeWidth * 6);')
    expect(patchArrowDev(patchedDev)).toBe(patchedDev)

    const prodSource = [
      'w=km(r),I=0;',
      'let N=Zm(r);if(r==="crowfoot_many"',
      'ri=e=>{switch(e.type){case"freedraw":return e.strokeWidth*12;case"text":return e.fontSize/2;default:return 20}}',
      'var Cm=e=>[8,8+e],k1=e=>[1.5,6+e];',
    ].join('')

    const patchedProd = patchArrowProd(prodSource)
    expect(patchedProd).toContain(markers.arrowSizeProd)
    expect(patchedProd).toContain('case"arrow":return Math.max(20,e.strokeWidth*6)')
    expect(patchArrowProd(patchedProd)).toBe(patchedProd)
  })

  it('fails fast on Excalidraw version mismatch or missing renderer anchor', () => {
    const dir = mkdtempSync(join(tmpdir(), 'jaaz-patch-test-'))
    try {
      mkdirSync(join(dir, 'dist/dev'), { recursive: true })
      mkdirSync(join(dir, 'dist/prod'), { recursive: true })
      writeFileSync(join(dir, 'package.json'), JSON.stringify({ version: '0.17.0' }))
      expect(() => applyExcalidrawPatches(dir)).toThrow(/0\.18\.1/)

      writeFileSync(join(dir, 'package.json'), JSON.stringify({ version: '0.18.1' }))
      writeFileSync(join(dir, 'dist/dev/chunk.js'), 'unmatched content')
      expect(() => applyExcalidrawPatches(dir)).toThrow(/Unable to locate Excalidraw/)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})
