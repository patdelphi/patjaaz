/** 程序说明：提供统一的 Excalidraw 场景元素变更工具，自动递增 version、versionNonce 和 updated。 */
import type { CaptureUpdateAction } from '@excalidraw/excalidraw'
import type { ExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import type { AppState, ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types'

export const CAPTURE_UPDATE_IMMEDIATELY =
  'IMMEDIATELY' as (typeof CaptureUpdateAction)['IMMEDIATELY']

export type MutableSceneAPI = Pick<
  ExcalidrawImperativeAPI,
  'getSceneElements' | 'updateScene'
>

/** 返回递增版本号与更新时间戳后的元素副本。 */
export function bumpElementVersion<T extends ExcalidrawElement>(
  element: T,
  now: number = Date.now()
): T {
  return {
    ...element,
    version: (typeof element.version === 'number' ? element.version : 0) + 1,
    versionNonce: Math.floor(Math.random() * 2147483647),
    updated: now,
  }
}

/** 遍历场景元素并原子提交修改（仅当元素有改动或传入 appState 时调用 updateScene）。 */
export function mutateSceneElements<K extends keyof AppState = never>(
  api: MutableSceneAPI | null | undefined,
  updater: (
    element: ExcalidrawElement,
    index: number,
    elements: readonly ExcalidrawElement[]
  ) => ExcalidrawElement,
  options?: {
    appState?: Pick<AppState, K>
    captureUpdate?: (typeof CaptureUpdateAction)[keyof typeof CaptureUpdateAction]
    now?: number
  }
): boolean {
  if (!api) return false

  const currentElements = api.getSceneElements()
  const now = options?.now ?? Date.now()
  let changed = false

  const nextElements = currentElements.map((element, index, list) => {
    const updated = updater(element, index, list)
    if (updated !== element) {
      changed = true
      return bumpElementVersion(updated, now)
    }
    return element
  })

  if (!changed && !options?.appState) {
    return false
  }

  api.updateScene({
    ...(changed ? { elements: nextElements } : {}),
    ...(options?.appState ? { appState: options.appState } : {}),
    captureUpdate: options?.captureUpdate ?? CAPTURE_UPDATE_IMMEDIATELY,
  })
  return true
}
