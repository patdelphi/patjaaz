/* 程序说明：校验画布 embeddable 元素的链接，仅允许本站 /api/file/ 资源。 */

const FORBIDDEN_PROTOCOL_PREFIXES = [
  'javascript:',
  'data:',
  'file:',
  'vbscript:',
]

function safeDecodeURIComponent(value: string): string | null {
  try {
    return decodeURIComponent(value)
  } catch {
    return null
  }
}

/** 判断画布 embeddable URL 是否属于同源 /api/file/ 资源，阻断外部网页或脚本嵌入。 */
export function isAllowedEmbeddableUrl(
  url: unknown,
  currentOrigin?: string
): boolean {
  if (typeof url !== 'string') return false

  const trimmed = url.trim()
  if (!trimmed) return false
  // 禁止空白字符、控制字符、反斜杠、协议相对路径及上级穿越。
  if (/[\u0000-\u0020\u007f\\]/.test(trimmed)) return false
  if (trimmed.startsWith('//') || trimmed.includes('..')) return false

  const lower = trimmed.toLowerCase()
  if (
    FORBIDDEN_PROTOCOL_PREFIXES.some((prefix) => lower.startsWith(prefix)) ||
    lower.includes('%2e%2e') ||
    lower.includes('%5c')
  ) {
    return false
  }

  const fallbackOrigin =
    typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin
      : 'http://jaaz.local'
  const resolvedBase = (currentOrigin || fallbackOrigin).trim()

  let baseUrl: URL
  let parsed: URL
  try {
    baseUrl = new URL(resolvedBase)
    parsed = new URL(trimmed, baseUrl)
  } catch {
    return false
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false
  if (parsed.origin !== baseUrl.origin) return false
  if (!parsed.pathname.startsWith('/api/file/')) return false

  const rest = parsed.pathname.slice('/api/file/'.length)
  if (!rest || rest.includes('/') || rest === '.') return false

  const decoded = safeDecodeURIComponent(rest)
  if (!decoded || decoded.includes('/') || decoded.includes('\\') || decoded.includes('..')) {
    return false
  }

  return true
}
