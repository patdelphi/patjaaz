/** 程序说明：提供文本模型协议枚举、默认服务地址映射、协议推断与模型能力标签归一化函数。 */

export type LLMProtocol = 'openai' | 'anthropic' | 'google' | 'openai-compatible'

export type ModelCapabilities = {
  vision?: boolean
  tools?: boolean
  thinking?: boolean
  context_length?: number
}

export type ProtocolOption = {
  value: LLMProtocol
  label: string
  defaultUrl: string
}

export const PROTOCOL_OPTIONS: ProtocolOption[] = [
  {
    value: 'openai',
    label: 'OpenAI 官方协议',
    defaultUrl: 'https://api.openai.com/v1/',
  },
  {
    value: 'anthropic',
    label: 'Anthropic (Claude 原生)',
    defaultUrl: 'https://api.anthropic.com',
  },
  {
    value: 'google',
    label: 'Google (Gemini REST 原生)',
    defaultUrl: 'https://generativelanguage.googleapis.com',
  },
  {
    value: 'openai-compatible',
    label: 'OpenAI 兼容接口 (Compatible)',
    defaultUrl: '',
  },
]

export const DEFAULT_PROTOCOL_URLS: Record<LLMProtocol, string> = {
  openai: 'https://api.openai.com/v1/',
  anthropic: 'https://api.anthropic.com',
  google: 'https://generativelanguage.googleapis.com',
  'openai-compatible': '',
}

const VALID_PROTOCOLS = new Set<LLMProtocol>([
  'openai',
  'anthropic',
  'google',
  'openai-compatible',
])

/** 根据显式配置、Provider 标识或 URL 自动推断文本模型协议。 */
export function inferProviderProtocol(
  providerKey: string,
  config?: { protocol?: string; url?: string } | null
): LLMProtocol {
  const explicit = String(config?.protocol || '').trim().toLowerCase() as LLMProtocol
  if (VALID_PROTOCOLS.has(explicit)) {
    return explicit
  }
  const key = String(providerKey || '').trim().toLowerCase()
  const url = String(config?.url || '').trim().toLowerCase()

  if (key.includes('anthropic') || key.includes('claude') || url.includes('api.anthropic.com')) {
    return 'anthropic'
  }
  if (key.includes('google') || key.includes('gemini') || url.includes('generativelanguage.googleapis.com')) {
    return 'google'
  }
  if (key === 'openai' || url.includes('api.openai.com')) {
    return 'openai'
  }
  return 'openai-compatible'
}

/** 归一化模型能力标签对象。 */
export function normalizeModelCapabilities(
  caps?: ModelCapabilities | null
): ModelCapabilities {
  return {
    vision: Boolean(caps?.vision),
    tools: caps?.tools === undefined ? true : Boolean(caps.tools),
    thinking: Boolean(caps?.thinking),
    ...(typeof caps?.context_length === 'number' && caps.context_length > 0
      ? { context_length: caps.context_length }
      : {}),
  }
}
