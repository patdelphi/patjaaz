/** 程序说明：将画布图片文件记录转换为聊天可上传的附件引用。 */
import { dataURLToFile } from '@/lib/utils'

export type CanvasChatImage = {
  fileId: string
  base64?: string
  sourceUrl?: string
  width: number
  height: number
}

type CanvasImageLike = {
  fileId?: string | null
  width: number
  height: number
}

type CanvasImageFileLike = {
  id?: string
  dataURL?: string
}

export function normalizeCanvasImageForChat(
  image: CanvasImageLike,
  file?: CanvasImageFileLike
): CanvasChatImage | null {
  if (
    !image.fileId ||
    !file?.dataURL ||
    !Number.isFinite(image.width) ||
    !Number.isFinite(image.height) ||
    image.width <= 0 ||
    image.height <= 0
  ) {
    return null
  }

  const fileId = file.id || image.fileId
  const attachment = { fileId, width: image.width, height: image.height }

  if (file.dataURL.startsWith('data:')) {
    return { ...attachment, base64: file.dataURL }
  }

  try {
    const url = new URL(file.dataURL, 'http://jaaz.local')
    const fileMarker = '/api/file/'
    const markerIndex = url.pathname.lastIndexOf(fileMarker)
    if (markerIndex >= 0) {
      const fileName = url.pathname.slice(markerIndex + fileMarker.length)
      if (fileName) {
        return { ...attachment, fileId: decodeURIComponent(fileName) }
      }
    }
  } catch {
    // 非标准 URL 仍交给聊天附件流程尝试读取，并在失败时提示用户。
  }

  return { ...attachment, sourceUrl: file.dataURL }
}

/** 将 URL 或内嵌数据的画布图片读成上传接口可接收的 File。 */
export async function canvasChatImageToFile(
  image: CanvasChatImage
): Promise<File | null> {
  if (image.base64) {
    return dataURLToFile(image.base64, image.fileId)
  }

  if (!image.sourceUrl) return null

  const response = await fetch(image.sourceUrl)
  if (!response.ok) {
    let message = response.statusText || `HTTP ${response.status}`
    try {
      const payload = await response.json()
      if (typeof payload?.detail === 'string') message = payload.detail
      else if (typeof payload?.message === 'string') message = payload.message
    } catch {
      // 错误响应不是 JSON 时保留 HTTP 状态信息。
    }
    throw new Error(message)
  }

  const blob = await response.blob()
  const url = new URL(image.sourceUrl, 'http://jaaz.local')
  const encodedName = url.pathname.split('/').pop() || 'canvas-image'
  const fileName = decodeURIComponent(encodedName)
  const fileType = blob.type || 'image/png'
  return new File([blob], fileName, { type: fileType })
}
