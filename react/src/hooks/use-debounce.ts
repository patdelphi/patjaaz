/* 程序说明：提供可刷新、可取消且卸载时会提交最后一次参数的防抖回调。 */
import { useCallback, useEffect, useRef } from 'react'

export type DebouncedCallback<T extends (...args: any[]) => any> = ((
  ...args: Parameters<T>
) => void) & {
  flush: () => void
  cancel: () => void
}

export default function useDebounce<T extends (...args: any[]) => any>(
  callback: T,
  delay: number
): DebouncedCallback<T> {
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const argsRef = useRef<Parameters<T> | null>(null)
  const callbackRef = useRef(callback)
  callbackRef.current = callback

  const cancel = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
    argsRef.current = null
  }, [])

  const flush = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
    const args = argsRef.current
    argsRef.current = null
    if (args) {
      callbackRef.current(...args)
    }
  }, [])

  const debounced = useCallback(
    (...args: Parameters<T>) => {
      argsRef.current = args
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
      timeoutRef.current = setTimeout(flush, delay)
    },
    [delay, flush]
  )

  useEffect(() => () => flush(), [flush])

  return Object.assign(debounced, { flush, cancel })
}
