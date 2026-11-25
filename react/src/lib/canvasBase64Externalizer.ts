/** 程序说明：将用户直接粘贴或拖入画布的 data:image/* 内联图片自动上传至 /api/upload_image，替换为轻量 /api/file/<id> 引用。 */
import { uploadImage } from '@/api/upload'
import type { BinaryFileData, BinaryFiles } from '@excalidraw/excalidraw/types'

const MIME_TO_EXT: Record<string, string> = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/jpg': 'jpg',
  'image/webp': 'webp',
  'image/gif': 'gif',
}

const inflightUploads = new Map<string, Promise<string | null>>()
const failedFileKeys = new Set<string>()

export function isInlineBase64ImageUrl(url?: string | null): boolean {
  return typeof url === 'string' && /^data:image\/[a-zA-Z0-9.+-]+;base64,/i.test(url)
}

export function dataUrlToFile(dataUrl: string, baseName: string): File {
  const commaIdx = dataUrl.indexOf(',')
  if (commaIdx < 0) {
    throw new Error('Invalid data URL')
  }
  const header = dataUrl.slice(0, commaIdx)
  const b64 = dataUrl.slice(commaIdx + 1)
  const mimeMatch = header.match(/^data:(image\/[a-zA-Z0-9.+-]+);base64$/i)
  const mimeType = (mimeMatch ? mimeMatch[1] : 'image/png').toLowerCase()
  const ext = MIME_TO_EXT[mimeType] || 'png'

  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return new File([bytes], `${baseName}.${ext}`, { type: mimeType })
}

/**
 * 扫描当前活跃画布图片元素引用的内联 base64 文件并上传外置，返回替换后的 BinaryFiles 与发生更新的列表。
 */
export async function externalizeInlineCanvasImages(
  canvasId: string,
  elements: ReadonlyArray<{ type?: string; isDeleted?: boolean; fileId?: string | null }>,
  files: BinaryFiles,
  uploader: (file: File) => Promise<{ url: string }> = uploadImage
): Promise<{ nextFiles: BinaryFiles; updatedEntries: BinaryFileData[] }> {
  const referencedFileIds = new Set<string>()
  for (const el of elements) {
    if (el && !el.isDeleted && el.type === 'image' && typeof el.fileId === 'string' && el.fileId) {
      referencedFileIds.add(el.fileId)
    }
  }

  const candidates: BinaryFileData[] = []
  for (const fid of referencedFileIds) {
    const entry = files[fid]
    const cacheKey = `${canvasId}:${fid}`
    if (entry && isInlineBase64ImageUrl(entry.dataURL) && !failedFileKeys.has(cacheKey)) {
      candidates.push(entry)
    }
  }

  if (candidates.length === 0) {
    return { nextFiles: files, updatedEntries: [] }
  }

  const nextFiles: BinaryFiles = { ...files }
  const updatedEntries: BinaryFileData[] = []

  await Promise.all(
    candidates.map(async (entry) => {
      const cacheKey = `${canvasId}:${entry.id}`
      let task = inflightUploads.get(cacheKey)
      if (!task) {
        task = (async () => {
          try {
            const fileObj = dataUrlToFile(entry.dataURL, `paste_${entry.id.slice(0, 8)}`)
            const res = await uploader(fileObj)
            return res.url || null
          } catch (err) {
            console.warn('[canvasBase64Externalizer] Failed to externalize inline image:', err)
            failedFileKeys.add(cacheKey)
            return null
          } finally {
            inflightUploads.delete(cacheKey)
          }
        })()
        inflightUploads.set(cacheKey, task)
      }

      const remoteUrl = await task
      if (remoteUrl) {
        const updated: BinaryFileData = {
          ...entry,
          dataURL: remoteUrl as BinaryFileData['dataURL'],
        }
        nextFiles[entry.id] = updated
        updatedEntries.push(updated)
      }
    })
  )

  return { nextFiles, updatedEntries }
}
