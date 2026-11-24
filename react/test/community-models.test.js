// 社区版 Jaaz 云端模型过滤逻辑回归测试。
import { describe, expect, it } from 'vitest'
import { filterJaazCloudModels } from '../src/lib/communityModels'

describe('filterJaazCloudModels', () => {
  it('filters Jaaz cloud models and keeps local or custom providers', () => {
    const models = [
      { provider: 'jaaz', name: 'cloud-model' },
      { provider: 'openai', name: 'custom-model' },
      { provider: 'ollama', name: 'local-model' },
    ]

    expect(filterJaazCloudModels(models)).toEqual([
      { provider: 'openai', name: 'custom-model' },
      { provider: 'ollama', name: 'local-model' },
    ])
    expect(models).toHaveLength(3)
  })

  it('returns an empty list when the provider list is missing', () => {
    expect(filterJaazCloudModels(undefined)).toEqual([])
  })
})
