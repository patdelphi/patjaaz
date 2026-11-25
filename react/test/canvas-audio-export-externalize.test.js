/** 程序说明：验证画布音频卡片归一化与加入对话、视频导出封面合成及内联 Base64 图片自动外置上传逻辑。 */
import { describe, expect, it, vi } from 'vitest'
import {
  collectSelectedCanvasContextForChat,
  isAudioUrl,
  isVideoUrl,
  normalizeCanvasElementsForScene,
} from '../src/lib/canvasMediaNormalize'
import {
  dataUrlToFile,
  externalizeInlineCanvasImages,
  isInlineBase64ImageUrl,
} from '../src/lib/canvasBase64Externalizer'
import { buildExportableSceneWithVideoPosters } from '../src/lib/canvasExportComposite'

describe('audio element normalization & chat reference', () => {
  it('distinguishes audio URLs from video URLs and normalizes type=audio into embeddable', () => {
    expect(isAudioUrl('/api/file/voice_01.wav')).toBe(true)
    expect(isAudioUrl('/api/file/bgm.mp3')).toBe(true)
    expect(isVideoUrl('/api/file/voice_01.wav')).toBe(false)
    expect(isVideoUrl('/api/file/clip.mp4')).toBe(true)

    const raw = [
      {
        id: 'aud-1',
        type: 'audio',
        fileId: 'aud-1',
        x: 120,
        y: 340,
        width: 360,
        height: 108,
      },
    ]
    const files = {
      'aud-1': {
        id: 'aud-1',
        dataURL: '/api/file/tts_sample.wav',
        mimeType: 'audio/wav',
      },
    }
    const normalized = normalizeCanvasElementsForScene(raw, files)
    expect(normalized[0]).toMatchObject({
      id: 'aud-1',
      type: 'embeddable',
      link: '/api/file/tts_sample.wav',
      width: 360,
      height: 108,
      customData: {
        jaazMediaType: 'audio',
        fileId: 'aud-1',
      },
    })

    const ctx = collectSelectedCanvasContextForChat(normalized, files, { 'aud-1': true })
    expect(ctx.texts).toEqual(['[画布音频引用: file_id="tts_sample.wav"]'])
  })
})

describe('video poster frame compositing for PNG/SVG export', () => {
  it('replaces video embeddables with synthetic image elements without mutating original scene', async () => {
    const originalElements = [
      { id: 'shape-1', type: 'rectangle', x: 0, y: 0, width: 200, height: 100, isDeleted: false },
      {
        id: 'vid-99',
        type: 'embeddable',
        link: '/api/file/story.mp4',
        x: 240,
        y: 0,
        width: 640,
        height: 360,
        isDeleted: false,
      },
      {
        id: 'aud-99',
        type: 'embeddable',
        link: '/api/file/narration.wav',
        x: 240,
        y: 400,
        width: 360,
        height: 108,
        isDeleted: false,
      },
    ]
    const originalFiles = {}
    const fakeCapturer = vi.fn().mockResolvedValue('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

    const result = await buildExportableSceneWithVideoPosters(
      originalElements,
      originalFiles,
      fakeCapturer
    )

    expect(fakeCapturer).toHaveBeenCalledTimes(1)
    expect(fakeCapturer).toHaveBeenCalledWith('/api/file/story.mp4', 640, 360)
    expect(originalElements[1].type).toBe('embeddable')
    expect(result.elements[1]).toMatchObject({
      id: 'vid-99',
      type: 'image',
      fileId: 'video_poster_vid-99',
      x: 240,
      y: 0,
      width: 640,
      height: 360,
    })
    expect(result.files['video_poster_vid-99']?.dataURL).toContain('data:image/png;base64,')
    expect(result.elements[2].type).toBe('embeddable')
  })
})

describe('inline base64 pasted image externalization (C2)', () => {
  const TINY_PNG =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

  it('converts data:image/* into File and swaps BinaryFiles dataURL to /api/file/<id>', async () => {
    expect(isInlineBase64ImageUrl(TINY_PNG)).toBe(true)
    expect(isInlineBase64ImageUrl('/api/file/abc.png')).toBe(false)

    const fileObj = dataUrlToFile(TINY_PNG, 'pasted_test')
    expect(fileObj.name).toBe('pasted_test.png')
    expect(fileObj.type).toBe('image/png')
    expect(fileObj.size).toBeGreaterThan(10)

    const elements = [
      { id: 'img-paste', type: 'image', fileId: 'f-inline', isDeleted: false },
      { id: 'img-remote', type: 'image', fileId: 'f-remote', isDeleted: false },
    ]
    const files = {
      'f-inline': { id: 'f-inline', dataURL: TINY_PNG, mimeType: 'image/png', created: 1 },
      'f-remote': { id: 'f-remote', dataURL: '/api/file/existing.png', mimeType: 'image/png', created: 1 },
    }
    const uploader = vi.fn().mockResolvedValue({ url: '/api/file/uploaded_x99.png' })

    const { nextFiles, updatedEntries } = await externalizeInlineCanvasImages(
      'cv-test-1',
      elements,
      files,
      uploader
    )
    expect(uploader).toHaveBeenCalledTimes(1)
    expect(updatedEntries).toHaveLength(1)
    expect(nextFiles['f-inline'].dataURL).toBe('/api/file/uploaded_x99.png')
    expect(nextFiles['f-remote'].dataURL).toBe('/api/file/existing.png')
  })
})
