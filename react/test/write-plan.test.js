// write_plan 参数结构校验回归测试。
import { describe, expect, it } from 'vitest'
import { parseWritePlanSteps } from '../src/lib/writePlan'

describe('write plan argument parser', () => {
  it('returns valid steps from serialized tool arguments', () => {
    expect(
      parseWritePlanSteps(
        JSON.stringify({ steps: [{ title: 'Inspect', description: 'Check logs' }] })
      )
    ).toEqual([{ title: 'Inspect', description: 'Check logs' }])
  })

  it('returns an empty list when steps is not an array', () => {
    expect(parseWritePlanSteps(JSON.stringify({ steps: 'not-an-array' }))).toEqual([])
    expect(parseWritePlanSteps(JSON.stringify({ steps: { title: 'Inspect' } }))).toEqual([])
  })

  it('ignores malformed entries and malformed JSON', () => {
    expect(
      parseWritePlanSteps(
        JSON.stringify({ steps: [null, { title: 42 }, { title: 'Valid' }] })
      )
    ).toEqual([{ title: 'Valid', description: '' }])
    expect(parseWritePlanSteps('{invalid')).toEqual([])
  })
})