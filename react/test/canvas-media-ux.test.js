// 画布视频归一化、平移帧率版本指纹、视频封面回退、聊天定位匹配及视频/Frame 分镜框整组加入对话单元测试。
import { describe, expect, it } from 'vitest'
import {
  collectSelectedCanvasContextForChat,
  computeSceneVersionKey,
  findCanvasElementByMediaUrl,
  normalizeCanvasElementsForScene,
  pickCanvasThumbnailUrl,
} from '../src/lib/canvasMediaNormalize'

describe('canvas media normalization & UX helpers', () => {
  it('converts backend type=video elements into Excalidraw embeddable elements on load', () => {
    const rawElements = [
      { id: 'txt-1', type: 'text', x: 10, y: 20, width: 100, height: 30, text: '脚本' },
      {
        id: 'im_eJxJbn8p',
        type: 'video',
        fileId: 'im_eJxJbn8p',
        x: 755,
        y: 1124,
        width: 640,
        height: 640,
        link: null,
      },
    ]
    const files = {
      im_eJxJbn8p: {
        id: 'im_eJxJbn8p',
        dataURL: '/api/file/fa3_mfiYnr.mp4',
        mimeType: 'video/mp4',
      },
    }
    const normalized = normalizeCanvasElementsForScene(rawElements, files)
    expect(normalized[0]).toBe(rawElements[0])
    expect(normalized[1]).toMatchObject({
      id: 'im_eJxJbn8p',
      type: 'embeddable',
      link: '/api/file/fa3_mfiYnr.mp4',
      x: 755,
      y: 1124,
      width: 640,
      height: 640,
      customData: {
        jaazMediaType: 'video',
        fileId: 'im_eJxJbn8p',
      },
    })
  })

  it('keeps scene version key stable across viewport pans and changes on element edits', () => {
    const sceneA = [
      { id: 'a', version: 1, versionNonce: 101, isDeleted: false },
      { id: 'b', version: 3, versionNonce: 202, isDeleted: false },
    ]
    const scenePanned = [
      { id: 'a', version: 1, versionNonce: 101, isDeleted: false },
      { id: 'b', version: 3, versionNonce: 202, isDeleted: false },
    ]
    const sceneEdited = [
      { id: 'a', version: 2, versionNonce: 303, isDeleted: false },
      { id: 'b', version: 3, versionNonce: 202, isDeleted: false },
    ]
    expect(computeSceneVersionKey(sceneA)).toBe(computeSceneVersionKey(scenePanned))
    expect(computeSceneVersionKey(sceneA)).not.toBe(computeSceneVersionKey(sceneEdited))
  })

  it('falls back to video URL for thumbnail when canvas contains only videos', () => {
    const elements = [
      {
        id: 'vid-1',
        type: 'embeddable',
        link: '/api/file/demo_clip.mp4',
        updated: 100,
        isDeleted: false,
      },
    ]
    expect(pickCanvasThumbnailUrl(elements, {})).toBe('/api/file/demo_clip.mp4')
  })

  it('collects frame title, bound/free scripts, images, and videos when a Frame is selected', () => {
    const elements = [
      { id: 'frame-1', type: 'frame', name: '第一幕：青瓷茶馆', x: 0, y: 0, width: 600, height: 600 },
      { id: 'rect-1', type: 'rectangle', frameId: 'frame-1', x: 20, y: 40, width: 300, height: 120 },
      { id: 'txt-bound', type: 'text', containerId: 'rect-1', x: 30, y: 60, text: '主角汉服设定' },
      { id: 'img-in-frame', type: 'image', fileId: 'f-img', x: 100, y: 200, width: 256, height: 256 },
      { id: 'vid-in-frame', type: 'embeddable', link: '/api/file/scene1.mp4', x: 100, y: 480, width: 160, height: 90 },
      { id: 'outside-txt', type: 'text', x: 900, y: 50, text: '框外无关笔记' },
    ]
    const files = {
      'f-img': { id: 'f-img', dataURL: '/api/file/char_v1.png' },
    }

    const res = collectSelectedCanvasContextForChat(elements, files, { 'frame-1': true })
    expect(res.images.map((i) => i.fileId)).toEqual(['char_v1.png'])
    expect(res.texts).toEqual([
      '【分镜画框：第一幕：青瓷茶馆】',
      '主角汉服设定',
      '[画布视频引用: file_id="scene1.mp4"]',
    ])
  })

  it('matches both image files and embeddable video links for chat-to-canvas positioning', () => {
    const elements = [
      { id: 'img-el', type: 'image', fileId: 'fid-1' },
      { id: 'vid-el', type: 'embeddable', link: '/api/file/fa3_mfiYnr.mp4' },
    ]
    const files = {
      'fid-1': { id: 'fid-1', dataURL: '/api/file/PKVpr-ZmWF.png' },
    }
    expect(
      findCanvasElementByMediaUrl(elements, files, 'http://127.0.0.1:57988/api/file/PKVpr-ZmWF.png')?.id
    ).toBe('img-el')
    expect(
      findCanvasElementByMediaUrl(elements, files, '/api/file/fa3_mfiYnr.mp4')?.id
    ).toBe('vid-el')
  })
})
