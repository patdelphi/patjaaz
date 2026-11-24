/* 程序说明：按画布串行保存，并让重开请求等待未完成的写入。 */
const pendingCanvasSaves = new Map<string, Promise<void>>()

export function queueCanvasSave(
  canvasId: string,
  saveOperation: () => Promise<void> | void
): Promise<void> {
  const previousSave = pendingCanvasSaves.get(canvasId) ?? Promise.resolve()
  const saveRequest = previousSave
    .catch(() => undefined)
    .then(() => saveOperation())

  pendingCanvasSaves.set(canvasId, saveRequest)
  const clearCompletedSave = () => {
    if (pendingCanvasSaves.get(canvasId) === saveRequest) {
      pendingCanvasSaves.delete(canvasId)
    }
  }
  void saveRequest.then(clearCompletedSave, clearCompletedSave)

  return saveRequest
}

export async function waitForPendingCanvasSaves(canvasId: string): Promise<void> {
  while (true) {
    const pendingSave = pendingCanvasSaves.get(canvasId)
    if (!pendingSave) return

    await pendingSave
    if (pendingCanvasSaves.get(canvasId) === pendingSave) {
      pendingCanvasSaves.delete(canvasId)
      return
    }
  }
}
