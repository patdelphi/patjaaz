import { findNewPersistableImageIds } from "../src/lib/canvasImagePersistence.ts"

describe("canvas image persistence detection", () => {
  it("detects only new active images whose file data is present", () => {
    const elements = [
      { id: "new-image", type: "image", fileId: "file-new", isDeleted: false },
      { id: "known-image", type: "image", fileId: "file-known", isDeleted: false },
      { id: "deleted-image", type: "image", fileId: "file-deleted", isDeleted: true },
      { id: "missing-file", type: "image", fileId: "file-missing", isDeleted: false },
    ]
    const files = {
      "file-new": { id: "file-new", dataURL: "data:image/png;base64,new" },
      "file-known": { id: "file-known", dataURL: "data:image/png;base64,known" },
      "file-deleted": { id: "file-deleted", dataURL: "data:image/png;base64,deleted" },
    }

    expect(findNewPersistableImageIds(elements, files, new Set(["known-image"]))).toEqual([
      "new-image",
    ])
  })

  it("does not mark an image as persistable before its file data arrives", () => {
    const elements = [
      { id: "pending-image", type: "image", fileId: "file-pending", isDeleted: false },
    ]

    expect(findNewPersistableImageIds(elements, {}, new Set())).toEqual([])
  })
})
