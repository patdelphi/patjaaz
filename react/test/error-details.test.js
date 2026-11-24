// ErrorBoundary 对 unknown 错误值的格式化回归测试。
import { describe, expect, it } from 'vitest'
import { getErrorDetails } from '../src/lib/errorDetails'

describe('getErrorDetails', () => {
  it('preserves name, message, and stack from Error instances', () => {
    const error = new TypeError('invalid input')
    const details = getErrorDetails(error)

    expect(details.name).toBe('TypeError')
    expect(details.message).toBe('invalid input')
    expect(details.stack).toContain('invalid input')
  })

  it('reads safe error fields from plain objects', () => {
    expect(
      getErrorDetails({
        name: 'ApiError',
        message: 'request failed',
        stack: 'api stack',
      })
    ).toEqual({
      name: 'ApiError',
      message: 'request failed',
      stack: 'api stack',
    })
  })

  it('formats thrown strings and null values without property access errors', () => {
    expect(getErrorDetails('request failed')).toEqual({
      name: 'Unknown Error',
      message: 'request failed',
      stack: '',
    })
    expect(getErrorDetails(null)).toEqual({
      name: 'Unknown Error',
      message: 'null',
      stack: '',
    })
  })
})
