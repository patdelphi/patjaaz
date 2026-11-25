/** 程序说明：提供画布媒体元素归一化（后台 video 转 Excalidraw embeddable）、场景版本轻量指纹、封面提取及视频/分镜画框整组加入对话逻辑。 */
import { CanvasChatImage, normalizeCanvasImageForChat } from '@/lib/canvasChatImage'

type GenericElement = {
  id: string
  type?: string
  x?: number
  y?: number
  width?: number
  height?: number
  version?: number
  versionNonce?: number
  updated?: number
  isDeleted?: boolean
  fileId?: string | null
  link?: string | null
  name?: string | null
  text?: string
  frameId?: string | null
  containerId?: string | null
  customData?: Record<string, unknown>
  [key: string]: unknown
}

type GenericFileMap = Record<
  string,
  | {
      id?: string
      dataURL?: string
      mimeType?: string
    }
  | undefined
>

const VIDEO_EXT_RE = /\.(mp4|webm|mov)(\?|$)/i
const AUDIO_EXT_RE = /\.(mp3|wav|flac|m4a|aac)(\?|$)/i

export function isAudioUrl(url?: string | null): boolean {
  if (!url || typeof url !== 'string') return false
  return AUDIO_EXT_RE.test(url)
}

export function isVideoUrl(url?: string | null): boolean {
  if (!url || typeof url !== 'string') return false
  if (isAudioUrl(url)) return false
  return VIDEO_EXT_RE.test(url) || /\.ogg(\?|$)/i.test(url) || url.startsWith('blob:') || url.includes('video')
}

export function extractApiFilename(url?: string | null): string | null {
  if (!url || typeof url !== 'string') return null
  try {
    const parsed = new URL(url, 'http://jaaz.local')
    const marker = '/api/file/'
    const idx = parsed.pathname.lastIndexOf(marker)
    if (idx >= 0) {
      const name = parsed.pathname.slice(idx + marker.length)
      if (name) return decodeURIComponent(name)
    }
  } catch {
    // 忽略异常 URL
  }
  return null
}

/** 将后端落盘的 type='video' 元素转换为 Excalidraw 可渲染的 embeddable 元素，保留原坐标与尺寸。 */
export function normalizeSingleVideoElement<T extends GenericElement>(
  element: T,
  files?: GenericFileMap
): T {
  if (!element || element.type !== 'video') return element
  const fileId = typeof element.fileId === 'string' ? element.fileId : element.id
  const fileEntry = fileId && files ? files[fileId] : undefined
  const link =
    (typeof element.link === 'string' && element.link) ||
    fileEntry?.dataURL ||
    null
  if (!link) return element

  const width = Number(element.width) > 0 ? Number(element.width) : 640
  const height = Number(element.height) > 0 ? Number(element.height) : 640

  return {
    ...element,
    type: 'embeddable',
    width,
    height,
    link,
    backgroundColor: '#09090b',
    fillStyle: 'solid',
    locked: false,
    groupIds: Array.isArray(element.groupIds) ? element.groupIds : [],
    boundElements: Array.isArray(element.boundElements) ? element.boundElements : [],
    updated: Number(element.updated) || Date.now(),
    customData: {
      ...(element.customData || {}),
      jaazMediaType: 'video',
      fileId,
    },
  } as T
}

/** 将后端落盘的 type='audio' 元素转换为 Excalidraw 可渲染的 embeddable 音频卡片元素。 */
export function normalizeSingleAudioElement<T extends GenericElement>(
  element: T,
  files?: GenericFileMap
): T {
  if (!element || element.type !== 'audio') return element
  const fileId = typeof element.fileId === 'string' ? element.fileId : element.id
  const fileEntry = fileId && files ? files[fileId] : undefined
  const link =
    (typeof element.link === 'string' && element.link) ||
    fileEntry?.dataURL ||
    null
  if (!link) return element

  const width = Number(element.width) > 0 ? Number(element.width) : 360
  const height = Number(element.height) > 0 ? Number(element.height) : 108

  return {
    ...element,
    type: 'embeddable',
    width,
    height,
    link,
    backgroundColor: '#18181b',
    fillStyle: 'solid',
    locked: false,
    groupIds: Array.isArray(element.groupIds) ? element.groupIds : [],
    boundElements: Array.isArray(element.boundElements) ? element.boundElements : [],
    updated: Number(element.updated) || Date.now(),
    customData: {
      ...(element.customData || {}),
      jaazMediaType: 'audio',
      fileId,
    },
  } as T
}

/** 归一化画布初始数据中的全部后台视频与音频元素，修复重新打开画布时媒体不显示问题。 */
export function normalizeCanvasElementsForScene<T extends GenericElement>(
  elements?: ReadonlyArray<T> | null,
  files?: GenericFileMap
): T[] {
  if (!Array.isArray(elements)) return []
  let changed = false
  const next = elements.map((elem) => {
    if (elem?.type === 'video') {
      const converted = normalizeSingleVideoElement(elem, files)
      if (converted !== elem) changed = true
      return converted
    }
    if (elem?.type === 'audio') {
      const converted = normalizeSingleAudioElement(elem, files)
      if (converted !== elem) changed = true
      return converted
    }
    return elem
  })
  return changed ? next : [...elements]
}

/** 计算画布元素版本指纹；纯平移或缩放视野时元素 version 不变，用于跳过每帧重复遍历与无效落库。 */
export function computeSceneVersionKey(
  elements: ReadonlyArray<{
    id: string
    version?: number
    versionNonce?: number
    isDeleted?: boolean
  }>
): string {
  let hash = 2166136261
  for (let i = 0; i < elements.length; i++) {
    const el = elements[i]
    const v = (el.version ?? 0) ^ ((el.versionNonce ?? 0) << 1) ^ (el.isDeleted ? 1 : 0)
    hash ^= v
    hash = Math.imul(hash, 16777619)
  }
  return `${elements.length}:${hash >>> 0}`
}

/** 提取画布封面 URL：优先取最新图片，纯视频画布回退到最新视频链接。 */
export function pickCanvasThumbnailUrl(
  elements: ReadonlyArray<GenericElement>,
  files: GenericFileMap
): string {
  const active = elements.filter((el) => el && !el.isDeleted)
  const latestImage = active
    .filter((el) => el.type === 'image')
    .sort((a, b) => (Number(b.updated) || 0) - (Number(a.updated) || 0))[0]
  if (latestImage) {
    const fid = typeof latestImage.fileId === 'string' ? latestImage.fileId : ''
    const url = fid ? files[fid]?.dataURL : ''
    if (url) return url
  }

  const latestVideo = active
    .filter(
      (el) =>
        el.type === 'video' || (el.type === 'embeddable' && isVideoUrl(el.link))
    )
    .sort((a, b) => (Number(b.updated) || 0) - (Number(a.updated) || 0))[0]
  if (latestVideo) {
    if (typeof latestVideo.link === 'string' && latestVideo.link) {
      return latestVideo.link
    }
    const fid = typeof latestVideo.fileId === 'string' ? latestVideo.fileId : latestVideo.id
    return (fid && files[fid]?.dataURL) || ''
  }
  return ''
}

function isInsideFrame(elem: GenericElement, frame: GenericElement): boolean {
  if (elem.id === frame.id) return false
  if (elem.frameId && elem.frameId === frame.id) return true
  const fx = Number(frame.x) || 0
  const fy = Number(frame.y) || 0
  const fw = Number(frame.width) || 0
  const fh = Number(frame.height) || 0
  if (fw <= 0 || fh <= 0) return false
  const ex = Number(elem.x) || 0
  const ey = Number(elem.y) || 0
  const ew = Math.max(0, Number(elem.width) || 0)
  const eh = Math.max(0, Number(elem.height) || 0)
  const cx = ex + ew / 2
  const cy = ey + eh / 2
  return cx >= fx && cx <= fx + fw && cy >= fy && cy <= fy + fh
}

/** 汇总当前选中元素（支持图片、独立/图形内文字、视频及整组 Frame 分镜画框）供一键加入对话。 */
export function collectSelectedCanvasContextForChat(
  elements: ReadonlyArray<GenericElement>,
  files: GenericFileMap,
  selectedIds: Readonly<Record<string, boolean | undefined>>
): {
  images: CanvasChatImage[]
  texts: string[]
} {
  const active = elements.filter((el) => el && !el.isDeleted)
  const selectedFrames = active.filter(
    (el) => el.type === 'frame' && Boolean(selectedIds[el.id])
  )

  // 将直接选中元素与选中 Frame 内部包含的子元素合并为有效目标集合
  const effectiveIds = new Set<string>()
  for (const el of active) {
    if (selectedIds[el.id]) {
      effectiveIds.add(el.id)
      continue
    }
    if (selectedFrames.some((frame) => isInsideFrame(el, frame))) {
      effectiveIds.add(el.id)
    }
  }

  const sorted = [...active].sort(
    (a, b) => (Number(a.y) || 0) - (Number(b.y) || 0) || (Number(a.x) || 0) - (Number(b.x) || 0)
  )

  const images: CanvasChatImage[] = []
  const seenImageKeys = new Set<string>()
  const texts: string[] = []
  const seenTextNodeIds = new Set<string>()

  for (const frame of selectedFrames) {
    const title = String(frame.name || '').trim()
    if (title) {
      texts.push(`【分镜画框：${title}】`)
    }
  }

  for (const el of sorted) {
    if (el.type === 'image' && effectiveIds.has(el.id)) {
      const fid = typeof el.fileId === 'string' ? el.fileId : undefined
      const fileEntry = fid ? files[fid] : undefined
      const attachment = normalizeCanvasImageForChat(
        {
          fileId: fid,
          width: Number(el.width) || 0,
          height: Number(el.height) || 0,
        },
        fileEntry
      )
      if (attachment && !seenImageKeys.has(attachment.fileId)) {
        seenImageKeys.add(attachment.fileId)
        images.push(attachment)
      }
      continue
    }

    if (
      el.type === 'text' &&
      (effectiveIds.has(el.id) ||
        (typeof el.containerId === 'string' && effectiveIds.has(el.containerId)))
    ) {
      if (seenTextNodeIds.has(el.id)) continue
      seenTextNodeIds.add(el.id)
      const raw = String(el.text || '').trim()
      if (raw) texts.push(raw)
      continue
    }

    if (
      (el.type === 'audio' ||
        (el.type === 'embeddable' &&
          (isAudioUrl(el.link) || el.customData?.jaazMediaType === 'audio'))) &&
      effectiveIds.has(el.id)
    ) {
      const fid = typeof el.fileId === 'string' ? el.fileId : el.id
      const url =
        (typeof el.link === 'string' && el.link) ||
        (fid ? files[fid]?.dataURL : undefined)
      const apiFileName = extractApiFilename(url)
      if (apiFileName) {
        texts.push(`[画布音频引用: file_id="${apiFileName}"]`)
      }
      continue
    }

    if (
      (el.type === 'video' || (el.type === 'embeddable' && isVideoUrl(el.link))) &&
      effectiveIds.has(el.id)
    ) {
      const fid = typeof el.fileId === 'string' ? el.fileId : el.id
      const url =
        (typeof el.link === 'string' && el.link) ||
        (fid ? files[fid]?.dataURL : undefined)
      const apiFileName = extractApiFilename(url)
      if (apiFileName) {
        texts.push(`[画布视频引用: file_id="${apiFileName}"]`)
      }
    }
  }

  return { images, texts }
}

/** 根据消息中的媒体 URL 在画布场景中查找对应的图片或视频元素（兼容 files 映射与 embeddable.link）。 */
export function findCanvasElementByMediaUrl<T extends GenericElement>(
  elements: ReadonlyArray<T>,
  files: GenericFileMap | undefined,
  mediaUrl?: string | null
): T | null {
  if (!mediaUrl) return null
  const targetName = extractApiFilename(mediaUrl)

  for (const el of elements) {
    if (!el || el.isDeleted) continue
    if (typeof el.link === 'string' && el.link) {
      if (
        mediaUrl.includes(el.link) ||
        el.link.includes(mediaUrl) ||
        (targetName && extractApiFilename(el.link) === targetName)
      ) {
        return el
      }
    }
    const fid = typeof el.fileId === 'string' ? el.fileId : el.id
    const fileUrl = fid && files ? files[fid]?.dataURL : undefined
    if (fileUrl) {
      if (
        mediaUrl.includes(fileUrl) ||
        fileUrl.includes(mediaUrl) ||
        (targetName && extractApiFilename(fileUrl) === targetName)
      ) {
        return el
      }
    }
  }
  return null
}

