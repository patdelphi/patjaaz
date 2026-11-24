/** 程序说明：封装 Excalidraw 撤销/重做按钮触发与可用状态读取。 */
export type HistoryAction = 'undo' | 'redo'

export function readExcalidrawHistoryState(
  rootDocument: Document | undefined = typeof document !== 'undefined' ? document : undefined
): { canUndo: boolean; canRedo: boolean } {
  if (!rootDocument) {
    return { canUndo: true, canRedo: true }
  }
  const undoBtn = rootDocument.querySelector('[data-testid="button-undo"]') as HTMLButtonElement | null
  const redoBtn = rootDocument.querySelector('[data-testid="button-redo"]') as HTMLButtonElement | null
  return {
    canUndo: undoBtn ? !undoBtn.disabled : true,
    canRedo: redoBtn ? !redoBtn.disabled : true,
  }
}

/** 优先点击 Excalidraw 内置历史按钮，若按钮未挂载则向画布容器派发 Ctrl+Z / Ctrl+Shift+Z。 */
export function triggerExcalidrawHistory(
  action: HistoryAction,
  rootDocument: Document | undefined = typeof document !== 'undefined' ? document : undefined
): boolean {
  if (!rootDocument) return false

  const selector =
    action === 'undo' ? '[data-testid="button-undo"]' : '[data-testid="button-redo"]'
  const button = rootDocument.querySelector(selector) as HTMLButtonElement | null
  if (button && !button.disabled) {
    button.click()
    return true
  }

  const target =
    (rootDocument.querySelector('.excalidraw') as HTMLElement | null) ??
    rootDocument.activeElement
  if (target && typeof KeyboardEvent !== 'undefined') {
    const event = new KeyboardEvent('keydown', {
      key: 'z',
      code: 'KeyZ',
      ctrlKey: true,
      shiftKey: action === 'redo',
      bubbles: true,
      cancelable: true,
    })
    target.dispatchEvent(event)
    return true
  }

  return false
}
