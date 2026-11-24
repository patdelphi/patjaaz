/** 程序说明：提供 ComfyUI 成对工作流文件识别、UI 画布 JSON 检测、能力标签格式化与文件导出辅助函数。 */

export type ParsedWorkflowFileInput = {
  name: string
  content: string
}

export type ClassifiedWorkflowFiles = {
  mode: 'pair' | 'single_api' | 'invalid'
  apiJson: Record<string, any> | null
  configJson: Record<string, any> | null
  apiFileName: string
  configFileName: string
  suggestedName: string
  errors: string[]
}

/** 检测 JSON 对象是否为 ComfyUI 编辑器画布格式（nodes/links 数组）而非 API Format。 */
export function isComfyUiGraphJson(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return false
  }
  const obj = payload as Record<string, unknown>
  const hasGraph =
    Array.isArray(obj.nodes) &&
    (Array.isArray(obj.links) || 'last_node_id' in obj)
  if (!hasGraph) {
    return false
  }
  const hasApiNodes = Object.entries(obj).some(([key, val]) => {
    if (['nodes', 'links', 'groups', 'config', 'extra'].includes(key)) {
      return false
    }
    return Boolean(
      val &&
        typeof val === 'object' &&
        typeof (val as Record<string, unknown>).class_type === 'string'
    )
  })
  return !hasApiNodes
}

/** 判断 JSON 对象是否为 Jaaz 工作流配置文件。 */
export function isJaazWorkflowConfig(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return false
  }
  const obj = payload as Record<string, unknown>
  return (
    typeof obj.name === 'string' &&
    Array.isArray(obj.inputs) &&
    ('schema_version' in obj || 'capability' in obj || 'description' in obj)
  )
}

/** 判断 JSON 对象是否为 ComfyUI API Format 节点字典。 */
export function isComfyApiWorkflow(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return false
  }
  if (isComfyUiGraphJson(payload)) {
    return false
  }
  return Object.values(payload as Record<string, unknown>).some((node) =>
    Boolean(
      node &&
        typeof node === 'object' &&
        typeof (node as Record<string, unknown>).class_type === 'string'
    )
  )
}

/** 从文件名推导安全的工作流英文下划线标识。 */
export function suggestWorkflowName(filename: string): string {
  const base = filename
    .replace(/\.api\.json$/i, '')
    .replace(/\.jaaz\.json$/i, '')
    .replace(/\.json$/i, '')
    .trim()
  const sanitized = base.replace(/[^a-zA-Z0-9_]+/g, '_').replace(/^_+|_+$/g, '')
  return sanitized || 'custom_workflow'
}

/** 自动识别用户选取的 1~2 个 JSON 文件角色，并提前拦截画布 UI JSON。 */
export function classifyWorkflowFiles(
  files: ParsedWorkflowFileInput[]
): ClassifiedWorkflowFiles {
  const errors: string[] = []
  let apiJson: Record<string, any> | null = null
  let configJson: Record<string, any> | null = null
  let apiFileName = ''
  let configFileName = ''

  if (!files || files.length === 0) {
    return {
      mode: 'invalid',
      apiJson: null,
      configJson: null,
      apiFileName: '',
      configFileName: '',
      suggestedName: 'custom_workflow',
      errors: ['请先选择工作流 JSON 文件'],
    }
  }

  for (const file of files) {
    let parsed: unknown
    try {
      parsed = JSON.parse(file.content)
    } catch (err) {
      errors.push(`文件 ${file.name} 不是有效的 JSON: ${err instanceof Error ? err.message : String(err)}`)
      continue
    }

    if (isComfyUiGraphJson(parsed)) {
      errors.push(
        `文件 ${file.name} 是 ComfyUI 编辑器画布 JSON（含 nodes/links），请在 ComfyUI 中启用 Dev Mode 后选择 Export (API) 导出 API JSON`
      )
      continue
    }

    if (isJaazWorkflowConfig(parsed)) {
      if (configJson) {
        errors.push(`检测到多个 Jaaz 配置文件（${configFileName} 与 ${file.name}），请仅保留一个`)
      } else {
        configJson = parsed as Record<string, any>
        configFileName = file.name
      }
      continue
    }

    if (isComfyApiWorkflow(parsed)) {
      if (apiJson) {
        errors.push(`检测到多个 API JSON 文件（${apiFileName} 与 ${file.name}），请仅保留一个`)
      } else {
        apiJson = parsed as Record<string, any>
        apiFileName = file.name
      }
      continue
    }

    errors.push(`无法识别文件 ${file.name} 的类型，请确认其为 ComfyUI API JSON 或 jaaz.workflow.json`)
  }

  const suggestedName =
    (configJson && typeof configJson.name === 'string' && configJson.name) ||
    suggestWorkflowName(apiFileName || files[0]?.name || 'custom_workflow')

  if (errors.length > 0) {
    return {
      mode: 'invalid',
      apiJson,
      configJson,
      apiFileName,
      configFileName,
      suggestedName,
      errors,
    }
  }

  if (apiJson && configJson) {
    return {
      mode: 'pair',
      apiJson,
      configJson,
      apiFileName,
      configFileName,
      suggestedName,
      errors: [],
    }
  }

  if (apiJson && !configJson) {
    return {
      mode: 'single_api',
      apiJson,
      configJson: null,
      apiFileName,
      configFileName: '',
      suggestedName,
      errors: [],
    }
  }

  return {
    mode: 'invalid',
    apiJson,
    configJson,
    apiFileName,
    configFileName,
    suggestedName,
    errors: ['缺少 ComfyUI API JSON 文件（如 workflow.api.json）'],
  }
}

const CAPABILITY_LABELS: Record<string, string> = {
  t2i: '文生图 (t2i)',
  i2i: '图生图/编辑 (i2i)',
  inpaint: '局部重绘 (inpaint)',
  outpaint: '扩图 (outpaint)',
  rembg: '抠图去背 (rembg)',
  upscale: '超分放大 (upscale)',
  t2v: '文生视频 (t2v)',
  i2v: '图生视频 (i2v)',
  tts: '语音合成 (tts)',
  asr: '语音识别 (asr)',
  music: '音乐生成 (music)',
  custom: '自定义 (custom)',
}

/** 格式化能力代码为可读中文标签。 */
export function formatCapabilityLabel(capability?: string): string {
  if (!capability) return '未分类'
  return CAPABILITY_LABELS[capability] || capability
}

/** 在浏览器中触发 JSON 文件下载。 */
export function downloadJsonFile(filename: string, payload: unknown): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
