/** 程序说明：压缩并上传聊天图片，同时校验服务端返回数据。 */
import { compressImageFile } from '@/utils/imageUtils'

export async function uploadImage(
  file: File
): Promise<{ file_id: string; width: number; height: number; url: string }> {
  // Compress image before upload
  const compressedFile = await compressImageFile(file)

  const formData = new FormData()
  formData.append('file', compressedFile)
  const response = await fetch('/api/upload_image', {
    method: 'POST',
    body: formData,
  })
  const payload = await response.json().catch(() => null)

  if (!response.ok) {
    const detail =
      typeof payload?.detail === 'string'
        ? payload.detail
        : typeof payload?.message === 'string'
          ? payload.message
          : response.statusText || `HTTP ${response.status}`
    throw new Error(detail)
  }

  if (
    !payload ||
    typeof payload.file_id !== 'string' ||
    !payload.file_id.trim() ||
    !Number.isFinite(payload.width) ||
    payload.width <= 0 ||
    !Number.isFinite(payload.height) ||
    payload.height <= 0 ||
    typeof payload.url !== 'string'
  ) {
    throw new Error('invalid image upload response')
  }

  return payload
}
