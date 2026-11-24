// 程序说明：验证画布 URL 图片转聊天上传文件，以及上传 API 错误处理。
import { afterEach, describe, expect, it, vi } from 'vitest'
import { canvasChatImageToFile } from '../src/lib/canvasChatImage'
import { uploadImage } from '../src/api/upload'

vi.mock('@/utils/imageUtils', () => ({
  compressImageFile: vi.fn(async (file) => file),
}))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('canvasChatImageToFile', () => {
  it('turns inline canvas image data into an uploadable file', async () => {
    const file = await canvasChatImageToFile({
      fileId: 'canvas-image.png',
      base64: 'data:image/png;base64,AQID',
      width: 20,
      height: 10,
    })

    expect(file).toBeInstanceOf(File)
    expect(file?.name).toBe('canvas-image.png')
    expect(file?.type).toBe('image/png')
  })

  it('keeps an existing server file reference without re-uploading it', async () => {
    await expect(
      canvasChatImageToFile({
        fileId: 'uploaded.png',
        width: 20,
        height: 10,
      })
    ).resolves.toBeNull()
  })

  it('fetches URL-backed canvas images into uploadable files', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Uint8Array([1, 2, 3]), {
        status: 200,
        headers: { 'Content-Type': 'image/png' },
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    const file = await canvasChatImageToFile({
      fileId: 'excalidraw-internal-id',
      sourceUrl: '/api/file/original.png',
      width: 20,
      height: 10,
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/file/original.png')
    expect(file).toBeInstanceOf(File)
    expect(file?.name).toBe('original.png')
    expect(file?.type).toBe('image/png')
  })

  it('reports a failed source image fetch', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'image missing' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    )

    await expect(
      canvasChatImageToFile({
        fileId: 'excalidraw-internal-id',
        sourceUrl: '/api/file/missing.png',
        width: 20,
        height: 10,
      })
    ).rejects.toThrow('image missing')
  })
})

describe('uploadImage', () => {
  it('returns a validated uploaded image response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ file_id: 'uploaded.png', width: 20, height: 10, url: '/api/file/uploaded.png' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        )
      )
    )

    await expect(uploadImage(new File(['image'], 'image.png', { type: 'image/png' }))).resolves.toEqual({
      file_id: 'uploaded.png',
      width: 20,
      height: 10,
      url: '/api/file/uploaded.png',
    })
  })

  it('throws the API detail when upload fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'file rejected' }), {
          status: 413,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    )

    await expect(
      uploadImage(new File(['image'], 'image.png', { type: 'image/png' }))
    ).rejects.toThrow('file rejected')
  })

  it('rejects a successful response without a usable file id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ width: 20, height: 10 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    )

    await expect(
      uploadImage(new File(['image'], 'image.png', { type: 'image/png' }))
    ).rejects.toThrow('invalid image upload response')
  })
})
