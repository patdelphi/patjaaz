/** 程序说明：封装统一 API 请求包装与全局 fetch 拦截器，收到受保护接口 401 时触发重新认证事件。 */
import { eventBus } from './event'

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

const INTERCEPTOR_FLAG = '__jaazAuthFetchInstalled'
const NATIVE_FETCH_KEY = '__jaazNativeFetch'

type InterceptorHost = typeof globalThis & {
  [INTERCEPTOR_FLAG]?: boolean
  [NATIVE_FETCH_KEY]?: FetchLike
}

function extractRequestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.toString()
  if (typeof Request !== 'undefined' && input instanceof Request) return input.url
  return String((input as { url?: string })?.url ?? '')
}

/** 判断响应是否为同源受保护 API 返回的 401（排除 /api/auth/* 登录与状态接口）。 */
export function shouldEmitUnauthorized(
  url: string,
  status: number,
  origin: string = typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
): boolean {
  if (status !== 401 || !url) return false
  try {
    const parsed = new URL(url, origin)
    if (parsed.origin !== origin) return false
    const path = parsed.pathname
    if (!(path === '/api' || path.startsWith('/api/'))) return false
    if (path === '/api/auth' || path.startsWith('/api/auth/')) return false
    return true
  } catch {
    return false
  }
}

/** 统一请求包装：遇到受保护 API 返回 401 时广播 Auth::Unauthorized 切换至登录闸门。 */
export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
  fetchImpl?: FetchLike
): Promise<Response> {
  const host = globalThis as InterceptorHost
  const executor =
    fetchImpl ??
    host[NATIVE_FETCH_KEY] ??
    (typeof globalThis.fetch === 'function' ? globalThis.fetch.bind(globalThis) : null)
  if (!executor) {
    throw new Error('Fetch API is unavailable')
  }

  const response = await executor(input, init)
  const url = extractRequestUrl(input)
  if (shouldEmitUnauthorized(url, response.status)) {
    eventBus.emit('Auth::Unauthorized', { url, status: response.status })
  }
  return response
}

/** 在全局对象上幂等安装 401 拦截器，覆盖应用内所有直接调用 fetch 的代码路径。 */
export function installApiAuthInterceptor(target: typeof globalThis = globalThis): void {
  const host = target as InterceptorHost
  if (!host || typeof host.fetch !== 'function' || host[INTERCEPTOR_FLAG]) {
    return
  }
  const original = host.fetch.bind(host)
  host[NATIVE_FETCH_KEY] = original
  host[INTERCEPTOR_FLAG] = true
  host.fetch = ((input: RequestInfo | URL, init?: RequestInit) =>
    apiFetch(input, init, original)) as typeof fetch
}
