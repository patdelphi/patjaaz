import {
  queueCanvasSave,
  waitForPendingCanvasSaves,
} from "../src/lib/canvasSaveQueue.ts"

describe("canvas save queue", () => {
  it("serializes saves for the same canvas", async () => {
    const calls = []
    let releaseFirst
    const firstGate = new Promise((resolve) => {
      releaseFirst = resolve
    })

    const firstSave = queueCanvasSave("canvas-a", async () => {
      calls.push("first-start")
      await firstGate
      calls.push("first-end")
    })
    const secondSave = queueCanvasSave("canvas-a", async () => {
      calls.push("second")
    })

    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(calls).toEqual(["first-start"])

    releaseFirst()
    await Promise.all([firstSave, secondSave])
    expect(calls).toEqual(["first-start", "first-end", "second"])
  })

  it("waits for pending saves before allowing a canvas reload", async () => {
    let releaseSave
    const saveGate = new Promise((resolve) => {
      releaseSave = resolve
    })

    const save = queueCanvasSave("canvas-b", () => saveGate)
    let reloadReady = false
    const reload = waitForPendingCanvasSaves("canvas-b").then(() => {
      reloadReady = true
    })

    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(reloadReady).toBe(false)

    releaseSave()
    await Promise.all([save, reload])
    expect(reloadReady).toBe(true)
  })
})


describe("failed canvas save queue", () => {
  it("rejects a canvas reload when the pending save fails", async () => {
    let rejectSave
    const saveGate = new Promise((_, reject) => {
      rejectSave = reject
    })
    const save = queueCanvasSave("canvas-failed", () => saveGate)
    const reload = waitForPendingCanvasSaves("canvas-failed")

    rejectSave(new Error("disk full"))

    await expect(reload).rejects.toThrow("disk full")
    await expect(save).rejects.toThrow("disk full")
  })
})
