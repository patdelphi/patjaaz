/** 程序说明：验证自动递增序号标注编号计算（跳过已删除元素）与成组圆圈文字生成逻辑。 */
import { describe, expect, it } from 'vitest'
import {
  CALLOUT_BADGE_DIAMETER,
  createCalloutBadgeSkeletons,
  getNextCalloutNumber,
} from '../src/lib/calloutBadge'

describe('numbered callout badges (E5)', () => {
  it('computes next callout number ignoring deleted elements', () => {
    expect(getNextCalloutNumber([])).toBe(1)
    const scene = [
      { id: '1', isDeleted: false, customData: { jaazType: 'callout-badge', calloutNumber: 1 } },
      { id: '2', isDeleted: false, customData: { jaazType: 'callout-badge', calloutNumber: 3 } },
      { id: '3', isDeleted: true, customData: { jaazType: 'callout-badge', calloutNumber: 9 } },
    ]
    expect(getNextCalloutNumber(scene)).toBe(4)
  })

  it('creates grouped circle and text skeletons centered at target coordinates', () => {
    const [circle, label] = createCalloutBadgeSkeletons(2, 500, 300)
    expect(circle.type).toBe('ellipse')
    expect(circle.width).toBe(CALLOUT_BADGE_DIAMETER)
    expect(circle.x).toBe(500 - CALLOUT_BADGE_DIAMETER / 2)
    expect(label.type).toBe('text')
    expect(label.text).toBe('2')
    expect(circle.groupIds).toEqual(label.groupIds)
    expect(circle.groupIds).toHaveLength(1)
  })
})
