/* 程序说明：筛选已经具备文件数据、需要立即写入画布的新增图片。 */
type CanvasImageLike = {
  id: string
  type: string
  fileId?: string | null
  isDeleted?: boolean
}

type CanvasBinaryFileLike = {
  dataURL?: string
}

export function getPersistableImageIds(
  elements: readonly CanvasImageLike[],
  files: Record<string, CanvasBinaryFileLike | undefined>
): string[] {
  return elements.flatMap((element) => {
    if (
      element.type !== 'image' ||
      element.isDeleted ||
      !element.fileId ||
      !files[element.fileId]?.dataURL
    ) {
      return []
    }
    return [element.id]
  })
}

export function findNewPersistableImageIds(
  elements: readonly CanvasImageLike[],
  files: Record<string, CanvasBinaryFileLike | undefined>,
  knownImageIds: ReadonlySet<string>
): string[] {
  return getPersistableImageIds(elements, files).filter(
    (imageId) => !knownImageIds.has(imageId)
  )
}
