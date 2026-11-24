// 画布图片进入聊天附件的路径归一化回归测试。
import { describe, expect, it } from 'vitest'
import { normalizeCanvasImageForChat } from '../src/lib/canvasChatImage'

const image = { fileId: 'element-file-id', width: 120, height: 80 }

describe('canvas image chat attachments', () => {
  it('passes inline Excalidraw data URLs through for upload', () => {
    expect(
      normalizeCanvasImageForChat(image, {
        id: 'element-file-id',
        dataURL: 'data:image/png;base64,aGVsbG8=',
      })
    ).toEqual({
      fileId: 'element-file-id',
      base64: 'data:image/png;base64,aGVsbG8=',
      width: 120,
      height: 80,
    })
  })

  it('extracts a Jaaz file id from relative and absolute API URLs', () => {
    expect(
      normalizeCanvasImageForChat(image, {
        id: 'element-file-id',
        dataURL: '/api/file/manual%20image.png?cache=1',
      })?.fileId
    ).toBe('manual image.png')
    expect(
      normalizeCanvasImageForChat(image, {
        id: 'element-file-id',
        dataURL: 'https://jaaz.example/api/file/image.png?cache=1',
      })?.fileId
    ).toBe('image.png')
  })

  it('preserves other URLs for explicit fetch and upload', () => {
    expect(
      normalizeCanvasImageForChat(image, {
        id: 'element-file-id',
        dataURL: 'https://images.example/photo.png',
      })
    ).toEqual({
      fileId: 'element-file-id',
      sourceUrl: 'https://images.example/photo.png',
      width: 120,
      height: 80,
    })
  })

  it('ignores image elements without available file data', () => {
    expect(normalizeCanvasImageForChat(image, undefined)).toBeNull()
    expect(
      normalizeCanvasImageForChat({ ...image, fileId: null }, {
        dataURL: 'data:image/png;base64,aGVsbG8=',
      })
    ).toBeNull()
  })
})