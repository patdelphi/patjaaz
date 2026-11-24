// M1 ComfyUI 成对工作流文件识别与 UI 画布 JSON 拦截回归测试。
import { describe, expect, it } from 'vitest'
import {
  classifyWorkflowFiles,
  formatCapabilityLabel,
  isComfyUiGraphJson,
  suggestWorkflowName,
} from '../src/lib/comfyWorkflowPack'

const VALID_API = {
  '6': { class_type: 'CLIPTextEncode', inputs: { text: 'cat' } },
  '9': { class_type: 'SaveImage', inputs: { filename_prefix: 'out' } },
}

const VALID_CONFIG = {
  schema_version: 1,
  name: 'moss_t2i',
  display_name: 'MOSS 文生图',
  capability: 't2i',
  output_kind: 'image',
  enabled: true,
  description: 'MOSS 文生图工作流',
  inputs: [
    {
      name: 'prompt',
      type: 'string',
      required: true,
      node_id: '6',
      node_input_name: 'text',
    },
  ],
}

describe('comfyWorkflowPack helpers', () => {
  it('detects ComfyUI editor graph JSON and blocks accidental upload', () => {
    const graphPayload = {
      last_node_id: 10,
      nodes: [{ id: 1, type: 'CLIPTextEncode' }],
      links: [],
    }
    expect(isComfyUiGraphJson(graphPayload)).toBe(true)

    const result = classifyWorkflowFiles([
      { name: 'workflow.json', content: JSON.stringify(graphPayload) },
    ])
    expect(result.mode).toBe('invalid')
    expect(result.errors[0]).toContain('Export (API)')
  })

  it('auto-classifies API JSON and Jaaz config JSON regardless of file order', () => {
    const result = classifyWorkflowFiles([
      { name: 'moss.jaaz.json', content: JSON.stringify(VALID_CONFIG) },
      { name: 'moss.api.json', content: JSON.stringify(VALID_API) },
    ])
    expect(result.mode).toBe('pair')
    expect(result.errors).toEqual([])
    expect(result.suggestedName).toBe('moss_t2i')
    expect(result.apiJson).toEqual(VALID_API)
    expect(result.configJson).toEqual(VALID_CONFIG)
  })

  it('handles single API JSON as draft mode and formats capabilities', () => {
    const single = classifyWorkflowFiles([
      { name: 'My Fancy Workflow.api.json', content: JSON.stringify(VALID_API) },
    ])
    expect(single.mode).toBe('single_api')
    expect(single.suggestedName).toBe('My_Fancy_Workflow')
    expect(suggestWorkflowName('edit-moss.jaaz.json')).toBe('edit_moss')
    expect(formatCapabilityLabel('i2i')).toContain('i2i')
  })
})
