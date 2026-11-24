// 画布图片进入聊天附件的路径归一化回归测试。
import { describe, expect, it } from 'vitest'
import {
  extractSelectedCanvasTexts,
  normalizeCanvasImageForChat,
} from '../src/lib/canvasChatImage'

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

  it('extracts standalone and container-bound script texts in reading order without duplicates', () => {
    const elements = [
      { id: 'rect-1', type: 'rectangle', x: 50, y: 100 },
      { id: 'txt-2', type: 'text', x: 50, y: 260, text: '  脚本2：道具特写  ' },
      { id: 'txt-1', type: 'text', x: 60, y: 120, containerId: 'rect-1', text: '脚本1：主角设定' },
      { id: 'txt-del', type: 'text', x: 50, y: 10, isDeleted: true, text: '已删除脚本' },
    ]
    expect(
      extractSelectedCanvasTexts(elements, {
        'rect-1': true,
        'txt-1': true,
        'txt-2': true,
        'txt-del': true,
      })
    ).toEqual(['脚本1：主角设定', '脚本2：道具特写'])
  })
})
