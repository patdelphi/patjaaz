// 知识库远程请求封装，保留已有令牌的兼容访问。
export async function authenticatedFetch(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = localStorage.getItem('jaaz_access_token')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  }

  if (token) {
    headers['Authorization'] = 'Bearer ' + token
  }

  return fetch(url, {
    ...options,
    headers,
  })
}
