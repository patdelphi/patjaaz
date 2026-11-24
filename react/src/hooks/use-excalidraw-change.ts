/** 程序说明：安全订阅 Excalidraw onChange 回调并在组件卸载时注销监听，消除渲染期间的监听泄漏。 */
import type { ExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import type {
  AppState,
  BinaryFiles,
  ExcalidrawImperativeAPI,
} from '@excalidraw/excalidraw/types'
import { useEffect, useRef } from 'react'

export type ExcalidrawChangeHandler = (
  elements: readonly ExcalidrawElement[],
  appState: AppState,
  files: BinaryFiles
) => void

export type SubscribableExcalidrawAPI = {
  onChange: (callback: ExcalidrawChangeHandler) => () => void
}

/** 建立单次 onChange 订阅并返回对应的注销函数。 */
export function subscribeExcalidrawChange(
  api: SubscribableExcalidrawAPI | null | undefined,
  handlerRef: { current: ExcalidrawChangeHandler }
): (() => void) | undefined {
  if (!api || typeof api.onChange !== 'function') {
    return undefined
  }
  const unsubscribe = api.onChange((elements, appState, files) => {
    handlerRef.current(elements, appState, files)
  })
  return () => {
    if (typeof unsubscribe === 'function') {
      unsubscribe()
    }
  }
}

/** React Hook：在 useEffect 内按 excalidrawAPI 实例绑定一次 onChange 并在清理时注销。 */
export function useExcalidrawChange(
  excalidrawAPI: ExcalidrawImperativeAPI | null | undefined,
  handler: ExcalidrawChangeHandler
): void {
  const handlerRef = useRef<ExcalidrawChangeHandler>(handler)
  handlerRef.current = handler

  useEffect(() => {
    return subscribeExcalidrawChange(excalidrawAPI, handlerRef)
  }, [excalidrawAPI])
}
