/** 程序说明：计算画布前后两次快照间的元素级增量 op 集（C1），仅在局部变更时走 /ops 接口以节省大画布序列化体积。 */
import type { CanvasElementOp } from '@/api/canvas'

export type ElementVersionDigest = Map<string, string>

type GenericSceneElement = {
  id: string
  version?: number
  versionNonce?: number
  isDeleted?: boolean
  [key: string]: unknown
}

export function buildElementDigestMap(
  elements: ReadonlyArray<GenericSceneElement>
): ElementVersionDigest {
  const map: ElementVersionDigest = new Map()
  for (const el of elements) {
    if (!el || !el.id) continue
    map.set(
      el.id,
      `${el.version ?? 0}:${el.versionNonce ?? 0}:${el.isDeleted ? 1 : 0}`
    )
  }
  return map
}

export function diffCanvasElementsToOps(
  prevDigest: ElementVersionDigest,
  nextElements: ReadonlyArray<GenericSceneElement>
): {
  ops: CanvasElementOp[]
  nextDigest: ElementVersionDigest
  shouldUseIncremental: boolean
} {
  const nextDigest = buildElementDigestMap(nextElements)
  if (prevDigest.size === 0 || nextElements.length === 0) {
    return { ops: [], nextDigest, shouldUseIncremental: false }
  }

  const ops: CanvasElementOp[] = []
  for (const el of nextElements) {
    if (!el || !el.id) continue
    const sig = nextDigest.get(el.id)
    const oldSig = prevDigest.get(el.id)
    if (oldSig === sig) continue
    if (el.isDeleted && oldSig) {
      ops.push({ op: 'delete', id: el.id })
    } else if (!el.isDeleted) {
      ops.push({ op: 'upsert', element: el as Record<string, unknown> })
    }
  }

  for (const oldId of prevDigest.keys()) {
    if (!nextDigest.has(oldId)) {
      ops.push({ op: 'delete', id: oldId })
    }
  }

  // 当变更元素不超过总元素的 60% 且至少有 1 项变更时走轻量增量 op 同步
  const shouldUseIncremental =
    ops.length > 0 && ops.length <= Math.max(4, Math.ceil(nextElements.length * 0.6))

  return { ops, nextDigest, shouldUseIncremental }
}
