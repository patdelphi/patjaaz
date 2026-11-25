/** 程序说明：覆盖阶段 P3 前端增量 op 差异提取（C1）与分镜多页 PDF 二进制封装（X1）单元测试。 */
import { describe, expect, it } from 'vitest'
import {
  buildElementDigestMap,
  diffCanvasElementsToOps,
} from '../src/lib/canvasIncrementalSync'
import {
  buildPdfFromJpegPages,
  collectElementsForFrame,
} from '../src/lib/canvasFrameExport'

describe('Stage P3 incremental sync and frame PDF export', () => {
  it('computes minimal upsert and delete ops when a small subset of elements changes', () => {
    const base = Array.from({ length: 10 }, (_, idx) => ({
      id: `el_${idx}`,
      version: 1,
      versionNonce: 100 + idx,
      isDeleted: false,
      x: idx * 50,
    }))
    const prev = buildElementDigestMap(base)

    const next = base.map((item) =>
      item.id === 'el_2'
        ? { ...item, version: 2, versionNonce: 999, x: 500 }
        : item.id === 'el_4'
          ? { ...item, version: 2, isDeleted: true }
          : item
    )
    const res = diffCanvasElementsToOps(prev, next)
    expect(res.shouldUseIncremental).toBe(true)
    expect(res.ops).toHaveLength(2)
    expect(res.ops).toEqual([
      { op: 'upsert', element: expect.objectContaining({ id: 'el_2', x: 500 }) },
      { op: 'delete', id: 'el_4' },
    ])
  })

  it('builds a valid PDF 1.4 binary document from JPEG frame pages and collects frame children', () => {
    const fakeJpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0xff, 0xd9])
    const pdfBytes = buildPdfFromJpegPages([
      { jpegBytes: fakeJpeg, widthPx: 1200, heightPx: 800 },
      { jpegBytes: fakeJpeg, widthPx: 1200, heightPx: 800 },
    ])
    const asciiHead = new TextDecoder('latin1').decode(pdfBytes.slice(0, 16))
    const asciiTail = new TextDecoder('latin1').decode(pdfBytes.slice(-32))
    expect(asciiHead.startsWith('%PDF-1.4')).toBe(true)
    expect(asciiTail.includes('%%EOF')).toBe(true)

    const frame = { id: 'f1', type: 'frame', x: 100, y: 100, width: 400, height: 400 }
    const insideByCoord = { id: 'img1', type: 'image', x: 150, y: 150, width: 100, height: 100 }
    const outside = { id: 'img2', type: 'image', x: 900, y: 900, width: 100, height: 100 }
    const grouped = collectElementsForFrame(frame, [frame, insideByCoord, outside])
    expect(grouped.map((g) => g.id)).toEqual(['f1', 'img1'])
  })
})
