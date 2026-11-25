/** 程序说明：计算画布下一个自动递增序号标注编号（E5），并生成成组的圆形角标与居中数字元素骨架。 */

export type CalloutCandidate = {
  id?: string
  isDeleted?: boolean
  customData?: Record<string, unknown>
}

export const CALLOUT_BADGE_DIAMETER = 36

/** 扫描当前未删除元素，返回下一个可用的递增序号（从 1 开始）。 */
export function getNextCalloutNumber(
  elements: ReadonlyArray<CalloutCandidate>
): number {
  let maxNum = 0
  for (const el of elements) {
    if (!el || el.isDeleted) continue
    const cd = el.customData
    if (cd && cd.jaazType === 'callout-badge') {
      const n = Number(cd.calloutNumber)
      if (Number.isFinite(n) && n > maxNum) {
        maxNum = Math.floor(n)
      }
    }
  }
  return maxNum + 1
}

/** 生成共享 groupId 的红底圆形 + 居中白字序号元素输入，供 convertToExcalidrawElements 转换。 */
export function createCalloutBadgeSkeletons(
  calloutNumber: number,
  centerX: number,
  centerY: number
) {
  const num = Math.max(1, Math.floor(calloutNumber))
  const label = String(num)
  const diameter = CALLOUT_BADGE_DIAMETER
  const groupId = `callout_grp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`
  const x = Math.round(centerX - diameter / 2)
  const y = Math.round(centerY - diameter / 2)
  const fontSize = label.length >= 2 ? 16 : 18
  const approxTextWidth = label.length * (fontSize * 0.6)
  const approxTextHeight = fontSize * 1.25

  return [
    {
      type: 'ellipse' as const,
      x,
      y,
      width: diameter,
      height: diameter,
      strokeColor: '#ffffff',
      backgroundColor: '#ef4444',
      fillStyle: 'solid' as const,
      strokeWidth: 2,
      roughness: 0,
      groupIds: [groupId],
      customData: {
        jaazType: 'callout-badge',
        calloutNumber: num,
      },
    },
    {
      type: 'text' as const,
      x: Math.round(centerX - approxTextWidth / 2),
      y: Math.round(centerY - approxTextHeight / 2),
      text: label,
      fontSize,
      strokeColor: '#ffffff',
      textAlign: 'center' as const,
      verticalAlign: 'middle' as const,
      groupIds: [groupId],
      customData: {
        jaazType: 'callout-badge-label',
        calloutNumber: num,
      },
    },
  ]
}
