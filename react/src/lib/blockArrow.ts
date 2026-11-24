/** 程序说明：实现参数化闭合多边形块箭头（直箭头、双向箭头、弯箭头）的几何顶点生成与缩放重算。 */
import type {
  ExcalidrawElement,
  ExcalidrawLinearElement,
} from '@excalidraw/excalidraw/element/types'

export type BlockArrowVariant = 'straight' | 'double' | 'curved'

export type BlockArrowParams = {
  variant: BlockArrowVariant
  shaftRatio: number
  headLengthPx: number
  headWidthRatio: number
  curvature: number
}

export type BlockArrowCustomData = BlockArrowParams & {
  kind: 'block-arrow'
  lastWidth: number
  lastHeight: number
}

export const DEFAULT_BLOCK_ARROW_PARAMS: BlockArrowParams = {
  variant: 'straight',
  shaftRatio: 0.42,
  headLengthPx: 56,
  headWidthRatio: 1.0,
  curvature: 0.38,
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function roundCoord(n: number): number {
  return Math.round(n * 100) / 100
}

/** 判断元素是否为 Jaaz 自定义块箭头（闭合 line 多边形）。 */
export function isBlockArrowElement(
  element: Pick<ExcalidrawElement, 'type' | 'customData'> | null | undefined
): element is ExcalidrawLinearElement {
  return Boolean(
    element &&
      element.type === 'line' &&
      element.customData &&
      element.customData.kind === 'block-arrow'
  )
}

/** 从元素 customData 中安全读取块箭头参数，缺省字段回退默认值。 */
export function readBlockArrowParams(
  customData: Record<string, unknown> | null | undefined
): BlockArrowParams {
  const variant =
    customData?.variant === 'double' || customData?.variant === 'curved'
      ? customData.variant
      : 'straight'
  return {
    variant,
    shaftRatio:
      typeof customData?.shaftRatio === 'number' && Number.isFinite(customData.shaftRatio)
        ? clamp(customData.shaftRatio, 0.15, 0.85)
        : DEFAULT_BLOCK_ARROW_PARAMS.shaftRatio,
    headLengthPx:
      typeof customData?.headLengthPx === 'number' && Number.isFinite(customData.headLengthPx)
        ? clamp(customData.headLengthPx, 16, 200)
        : DEFAULT_BLOCK_ARROW_PARAMS.headLengthPx,
    headWidthRatio:
      typeof customData?.headWidthRatio === 'number' && Number.isFinite(customData.headWidthRatio)
        ? clamp(customData.headWidthRatio, 0.5, 1.0)
        : DEFAULT_BLOCK_ARROW_PARAMS.headWidthRatio,
    curvature:
      typeof customData?.curvature === 'number' && Number.isFinite(customData.curvature)
        ? clamp(customData.curvature, -0.85, 0.85)
        : DEFAULT_BLOCK_ARROW_PARAMS.curvature,
  }
}

function normalizePointsToBox(
  pts: [number, number][],
  width: number,
  height: number
): [number, number][] {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity

  for (const [x, y] of pts) {
    if (x < minX) minX = x
    if (y < minY) minY = y
    if (x > maxX) maxX = x
    if (y > maxY) maxY = y
  }

  const spanX = Math.max(1e-3, maxX - minX)
  const spanY = Math.max(1e-3, maxY - minY)
  return pts.map(([x, y]) => [
    roundCoord(((x - minX) / spanX) * width),
    roundCoord(((y - minY) / spanY) * height),
  ])
}

/** 按目标宽高与块箭头参数生成闭合多边形顶点（首尾坐标一致）。 */
export function generateBlockArrowPoints(
  rawWidth: number,
  rawHeight: number,
  partialParams?: Partial<BlockArrowParams>
): [number, number][] {
  const w = Math.max(24, Number.isFinite(rawWidth) ? rawWidth : 240)
  const h = Math.max(16, Number.isFinite(rawHeight) ? rawHeight : 88)
  const params = { ...DEFAULT_BLOCK_ARROW_PARAMS, ...partialParams }
  const shaftRatio = clamp(params.shaftRatio, 0.15, 0.85)
  const headWidthRatio = clamp(params.headWidthRatio, 0.5, 1.0)

  if (params.variant === 'double') {
    const headLen = clamp(params.headLengthPx, 16, w * 0.42)
    const headSpan = Math.max(8, h * headWidthRatio)
    const hyTop = (h - headSpan) / 2
    const hyBot = (h + headSpan) / 2
    const shaftH = Math.min(headSpan * 0.9, h * shaftRatio)
    const sy1 = (h - shaftH) / 2
    const sy2 = (h + shaftH) / 2
    const xL = headLen
    const xR = w - headLen
    const cy = h / 2

    const ring: [number, number][] = [
      [0, cy],
      [xL, hyTop],
      [xL, sy1],
      [xR, sy1],
      [xR, hyTop],
      [w, cy],
      [xR, hyBot],
      [xR, sy2],
      [xL, sy2],
      [xL, hyBot],
    ]
    const closed = normalizePointsToBox([...ring, ring[0]], w, h)
    closed[closed.length - 1] = [...closed[0]]
    return closed
  }

  if (params.variant === 'curved') {
    const segments = 24
    const headLen = clamp(params.headLengthPx, 16, w * 0.48)
    const curvature = clamp(params.curvature, -0.85, 0.85)
    const shaftH = Math.max(4, h * shaftRatio * 0.72)
    const halfShaft = shaftH / 2
    const halfHead = Math.max(halfShaft * 1.35, (h * headWidthRatio) * 0.45)

    // 构造二次贝塞尔中轴，控制点随 curvature 上下拱起
    const p0: [number, number] = [0, h * (curvature >= 0 ? 0.78 : 0.22)]
    const p2: [number, number] = [w - headLen, h * 0.48]
    const p1: [number, number] = [
      (p0[0] + p2[0]) * 0.48,
      p0[1] - curvature * h * 1.15,
    ]

    const upperEdge: [number, number][] = []
    const lowerEdge: [number, number][] = []

    let endTangentX = 1
    let endTangentY = 0

    for (let i = 0; i <= segments; i++) {
      const t = i / segments
      const mt = 1 - t
      const x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
      const y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]

      const dx = 2 * mt * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
      const dy = 2 * mt * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
      const len = Math.max(1e-4, Math.hypot(dx, dy))
      const tx = dx / len
      const ty = dy / len
      const nx = -ty
      const ny = tx

      if (i === segments) {
        endTangentX = tx
        endTangentY = ty
      }

      upperEdge.push([x - nx * halfShaft, y - ny * halfShaft])
      lowerEdge.push([x + nx * halfShaft, y + ny * halfShaft])
    }

    const endNx = -endTangentY
    const endNy = endTangentX
    const headBaseTop: [number, number] = [p2[0] - endNx * halfHead, p2[1] - endNy * halfHead]
    const headTip: [number, number] = [p2[0] + endTangentX * headLen, p2[1] + endTangentY * headLen]
    const headBaseBot: [number, number] = [p2[0] + endNx * halfHead, p2[1] + endNy * halfHead]

    const ring: [number, number][] = [
      ...upperEdge,
      headBaseTop,
      headTip,
      headBaseBot,
      ...lowerEdge.reverse(),
    ]
    const closed = normalizePointsToBox([...ring, ring[0]], w, h)
    closed[closed.length - 1] = [...closed[0]]
    return closed
  }

  // 默认：直向块箭头（straight）
  const headLen = clamp(params.headLengthPx, 16, w * 0.65)
  const headSpan = Math.max(8, h * headWidthRatio)
  const hyTop = (h - headSpan) / 2
  const hyBot = (h + headSpan) / 2
  const shaftH = Math.min(headSpan * 0.9, h * shaftRatio)
  const sy1 = (h - shaftH) / 2
  const sy2 = (h + shaftH) / 2
  const neckX = w - headLen

  const ring: [number, number][] = [
    [0, sy1],
    [neckX, sy1],
    [neckX, hyTop],
    [w, h / 2],
    [neckX, hyBot],
    [neckX, sy2],
    [0, sy2],
  ]
  const closed = normalizePointsToBox([...ring, ring[0]], w, h)
  closed[closed.length - 1] = [...closed[0]]
  return closed
}

/** 创建可直接插入 Excalidraw 场景的参数化块箭头元素。 */
export function createBlockArrowElement(options: {
  x: number
  y: number
  width?: number
  height?: number
  variant?: BlockArrowVariant
  strokeColor?: string
  backgroundColor?: string
  strokeWidth?: number
  seed?: number
  id?: string
  now?: number
}): ExcalidrawLinearElement {
  const width = options.width ?? 240
  const height = options.height ?? 96
  const params: BlockArrowParams = {
    ...DEFAULT_BLOCK_ARROW_PARAMS,
    variant: options.variant ?? 'straight',
  }
  const points = generateBlockArrowPoints(width, height, params)
  const now = options.now ?? Date.now()
  const seed = options.seed ?? Math.floor(Math.random() * 2147483647)

  const customData: BlockArrowCustomData = {
    kind: 'block-arrow',
    ...params,
    lastWidth: width,
    lastHeight: height,
  }

  return {
    id: options.id ?? `ba_${seed.toString(36)}_${now.toString(36)}`,
    type: 'line',
    x: options.x,
    y: options.y,
    width,
    height,
    angle: 0 as ExcalidrawLinearElement['angle'],
    strokeColor: options.strokeColor ?? '#1e3a8a',
    backgroundColor: options.backgroundColor ?? '#3b82f6',
    fillStyle: 'solid',
    strokeWidth: options.strokeWidth ?? 2,
    strokeStyle: 'solid',
    // roundness 必须为 null 且 roughness 为 0，确保闭合多边形保持尖锐棱角与实色填充
    roundness: null,
    roughness: 0,
    opacity: 100,
    groupIds: [],
    frameId: null,
    index: null as ExcalidrawLinearElement['index'],
    seed,
    version: 1,
    versionNonce: seed,
    isDeleted: false,
    boundElements: null,
    updated: now,
    link: null,
    locked: false,
    points: points as unknown as ExcalidrawLinearElement['points'],
    lastCommittedPoint: null,
    startBinding: null,
    endBinding: null,
    startArrowhead: null,
    endArrowhead: null,
    customData,
  }
}

/** 检测被用户拖拽缩放过的块箭头并重算其顶点与 lastWidth/lastHeight；若无变化返回 null。 */
export function recomputeResizedBlockArrows(
  elements: readonly ExcalidrawElement[],
  now: number = Date.now()
): ExcalidrawElement[] | null {
  let changed = false

  const nextElements = elements.map((element) => {
    if (element.isDeleted || !isBlockArrowElement(element)) {
      return element
    }

    const data = element.customData as Record<string, unknown> | undefined
    const lastW = typeof data?.lastWidth === 'number' ? data.lastWidth : element.width
    const lastH = typeof data?.lastHeight === 'number' ? data.lastHeight : element.height

    if (Math.abs(element.width - lastW) <= 1 && Math.abs(element.height - lastH) <= 1) {
      return element
    }

    changed = true
    const params = readBlockArrowParams(data)
    const nextPoints = generateBlockArrowPoints(element.width, element.height, params)
    return {
      ...element,
      roundness: null,
      roughness: 0,
      points: nextPoints as unknown as ExcalidrawLinearElement['points'],
      customData: {
        ...(element.customData ?? {}),
        kind: 'block-arrow',
        ...params,
        lastWidth: element.width,
        lastHeight: element.height,
      },
      version: (typeof element.version === 'number' ? element.version : 0) + 1,
      versionNonce: Math.floor(Math.random() * 2147483647),
      updated: now,
    } as ExcalidrawElement
  })

  return changed ? nextElements : null
}
