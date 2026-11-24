// 画布 embeddable 链接白名单校验的回归测试。
import { describe, expect, it } from 'vitest'
import { isAllowedEmbeddableUrl } from '../src/lib/embeddableUrl'

describe('isAllowedEmbeddableUrl', () => {
  const origin = 'http://localhost:5174'

  it('allows relative and same-origin /api/file/ URLs', () => {
    expect(isAllowedEmbeddableUrl('/api/file/vid_123.mp4', origin)).toBe(true)
    expect(
      isAllowedEmbeddableUrl('http://localhost:5174/api/file/im_abc.png', origin)
    ).toBe(true)
    expect(
      isAllowedEmbeddableUrl('https://tunnel.example.com/api/file/v1.mp4', 'https://tunnel.example.com')
    ).toBe(true)
  })

  it('blocks external origins, protocol-relative URLs, dangerous schemes, and traversal', () => {
    const blocked = [
      '',
      '   ',
      'https://evil.com/phishing',
      'https://evil.com/api/file/vid.mp4',
      '//evil.com/api/file/vid.mp4',
      'javascript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'file:///C:/Windows/win.ini',
      '/api/file/../secret.txt',
      '/api/file/%2e%2e/secret.txt',
      '/api/file/sub/nested.mp4',
      '/api/file/',
      '/api/settings',
      'http://localhost:5174/api/file/a\\b.mp4',
    ]

    for (const url of blocked) {
      expect(isAllowedEmbeddableUrl(url, origin), url).toBe(false)
    }
  })
})
