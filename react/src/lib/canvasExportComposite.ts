/** 程序说明：在整张画布或选区导出为 PNG/SVG 前，捕获内嵌视频当前帧/首帧生成临时图片元素，避免视频区域导出为空白框。 */
import { isVideoUrl } from '@/lib/canvasMediaNormalize'
import type { OrderedExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import type { BinaryFileData, BinaryFiles } from '@excalidraw/excalidraw/types'

function drawVideoFrameToDataUrl(
  video: HTMLVideoElement,
  targetWidth: number,
  targetHeight: number
): string | null {
  try {
    const w = Math.max(1, Math.round(video.videoWidth || targetWidth || 640))
    const h = Math.max(1, Math.round(video.videoHeight || targetHeight || 360))
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.fillStyle = '#09090b'
    ctx.fillRect(0, 0, w, h)
    ctx.drawImage(video, 0, 0, w, h)
    return canvas.toDataURL('image/png')
  } catch {
    return null
  }
}

/** 优先复用页面已挂载的 <video> 帧，未就绪时临时离屏加载首帧并导出 PNG DataURL。 */
export async function captureVideoPosterDataUrl(
  videoSrc: string,
  width: number,
  height: number,
  timeoutMs = 4000
): Promise<string | null> {
  if (typeof document === 'undefined' || !videoSrc) return null

  const mountedVideos = Array.from(document.querySelectorAll('video'))
  for (const existing of mountedVideos) {
    if (
      (existing.currentSrc.endsWith(videoSrc) || existing.getAttribute('src') === videoSrc) &&
      existing.readyState >= 2 &&
      existing.videoWidth > 0
    ) {
      const fastUrl = drawVideoFrameToDataUrl(existing, width, height)
      if (fastUrl) return fastUrl
    }
  }

  return new Promise<string | null>((resolve) => {
    const tempVideo = document.createElement('video')
    let settled = false
    const finish = (val: string | null) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      tempVideo.removeAttribute('src')
      tempVideo.load()
      resolve(val)
    }

    const timer = setTimeout(() => finish(null), timeoutMs)
    tempVideo.crossOrigin = 'anonymous'
    tempVideo.muted = true
    tempVideo.playsInline = true
    tempVideo.preload = 'auto'

    tempVideo.onloadeddata = () => {
      if (tempVideo.duration > 0.15) {
        tempVideo.currentTime = 0.1
      } else {
        finish(drawVideoFrameToDataUrl(tempVideo, width, height))
      }
    }
    tempVideo.onseeked = () => {
      finish(drawVideoFrameToDataUrl(tempVideo, width, height))
    }
    tempVideo.onerror = () => finish(null)
    tempVideo.src = videoSrc
  })
}

/**
 * 构建用于 PNG/SVG 导出的临时场景副本：将可截帧的视频 embeddable 元素替换为同坐标临时图片，不改动原画布状态。
 */
export async function buildExportableSceneWithVideoPosters(
  elements: ReadonlyArray<OrderedExcalidrawElement>,
  files: BinaryFiles,
  posterCapturer: (
    src: string,
    width: number,
    height: number
  ) => Promise<string | null> = captureVideoPosterDataUrl
): Promise<{
  elements: OrderedExcalidrawElement[]
  files: BinaryFiles
}> {
  const nextFiles: BinaryFiles = { ...files }
  const nextElements: OrderedExcalidrawElement[] = []

  for (const el of elements) {
    if (el.isDeleted) continue
    const link = 'link' in el && typeof el.link === 'string' ? el.link : ''
    const isVideoEmbed =
      el.type === 'embeddable' &&
      (isVideoUrl(link) ||
        (el.customData as Record<string, unknown> | undefined)?.jaazMediaType === 'video')

    if (isVideoEmbed && link) {
      const posterDataUrl = await posterCapturer(link, el.width, el.height)
      if (posterDataUrl) {
        const syntheticFileId = `video_poster_${el.id}`
        const fileData: BinaryFileData = {
          id: syntheticFileId as BinaryFileData['id'],
          dataURL: posterDataUrl as BinaryFileData['dataURL'],
          mimeType: 'image/png',
          created: Date.now(),
        }
        nextFiles[syntheticFileId] = fileData
        const syntheticImage = {
          ...el,
          type: 'image',
          fileId: syntheticFileId,
          status: 'saved',
          scale: [1, 1],
          crop: null,
        } as unknown as OrderedExcalidrawElement
        nextElements.push(syntheticImage)
        continue
      }
    }

    nextElements.push(el)
  }

  return { elements: nextElements, files: nextFiles }
}
