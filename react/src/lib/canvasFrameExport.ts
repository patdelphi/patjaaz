/** 程序说明：构建按 Frame 分镜框裁剪导出（PNG/JPG/WebP，支持 1x/2x 倍率）与零依赖多页 PDF 二进制封装工具（X1）。 */

export type FrameExportFormat = 'png' | 'jpeg' | 'webp'

/** 将一组 JPEG 字节页组装为符合 PDF 1.4 规范的多页二进制文档，无需引入第三方重型 PDF 库。 */
export function buildPdfFromJpegPages(
  pages: ReadonlyArray<{ jpegBytes: Uint8Array; widthPx: number; heightPx: number }>
): Uint8Array {
  if (pages.length === 0) {
    throw new Error('At least one page is required to build PDF')
  }

  const encoder = new TextEncoder()
  const chunks: Uint8Array[] = []
  const offsets: number[] = [0]
  let bytePos = 0

  const pushStr = (s: string) => {
    const b = encoder.encode(s)
    chunks.push(b)
    bytePos += b.byteLength
  }
  const pushBytes = (b: Uint8Array) => {
    chunks.push(b)
    bytePos += b.byteLength
  }

  pushStr('%PDF-1.4\n%\xFF\xFF\xFF\xFF\n')

  // 对象编号分配：1 = Catalog, 2 = Pages, 每页占 3 个对象 (Page, Image XObject, Content Stream)
  const pageObjIds: number[] = []
  let nextId = 3
  const pageRecords = pages.map((p) => {
    const pageId = nextId++
    const imgId = nextId++
    const contentId = nextId++
    pageObjIds.push(pageId)
    return { ...p, pageId, imgId, contentId }
  })

  // 1: Catalog
  offsets[1] = bytePos
  pushStr('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')

  // 2: Pages
  offsets[2] = bytePos
  const kids = pageObjIds.map((id) => `${id} 0 R`).join(' ')
  pushStr(`2 0 obj\n<< /Type /Pages /Count ${pages.length} /Kids [ ${kids} ] >>\nendobj\n`)

  for (const rec of pageRecords) {
    const ptW = Math.max(72, Math.round(rec.widthPx * 0.75))
    const ptH = Math.max(72, Math.round(rec.heightPx * 0.75))

    offsets[rec.pageId] = bytePos
    pushStr(
      `${rec.pageId} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${ptW} ${ptH}] ` +
        `/Resources << /XObject << /Im0 ${rec.imgId} 0 R >> >> /Contents ${rec.contentId} 0 R >>\nendobj\n`
    )

    offsets[rec.imgId] = bytePos
    pushStr(
      `${rec.imgId} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${Math.round(rec.widthPx)} ` +
        `/Height ${Math.round(rec.heightPx)} /ColorSpace /DeviceRGB /BitsPerComponent 8 ` +
        `/Filter /DCTDecode /Length ${rec.jpegBytes.byteLength} >>\nstream\n`
    )
    pushBytes(rec.jpegBytes)
    pushStr('\nendstream\nendobj\n')

    const contentStream = `q ${ptW} 0 0 ${ptH} 0 0 cm /Im0 Do Q\n`
    const contentBytes = encoder.encode(contentStream)
    offsets[rec.contentId] = bytePos
    pushStr(`${rec.contentId} 0 obj\n<< /Length ${contentBytes.byteLength} >>\nstream\n`)
    pushBytes(contentBytes)
    pushStr('endstream\nendobj\n')
  }

  const xrefOffset = bytePos
  const totalObjs = nextId
  pushStr(`xref\n0 ${totalObjs}\n0000000000 65535 f \n`)
  for (let i = 1; i < totalObjs; i++) {
    const off = String(offsets[i] ?? 0).padStart(10, '0')
    pushStr(`${off} 00000 n \n`)
  }
  pushStr(`trailer\n<< /Size ${totalObjs} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`)

  const out = new Uint8Array(bytePos)
  let offset = 0
  for (const c of chunks) {
    out.set(c, offset)
    offset += c.byteLength
  }
  return out
}

/** 收集画布中某个 Frame 及其内部所属元素（含按坐标落入画框内的元素）。 */
export function collectElementsForFrame<
  T extends {
    id: string
    type?: string
    x?: number
    y?: number
    width?: number
    height?: number
    frameId?: string | null
    isDeleted?: boolean
  }
>(frame: T, allActiveElements: ReadonlyArray<T>): T[] {
  const fx = Number(frame.x || 0)
  const fy = Number(frame.y || 0)
  const fw = Number(frame.width || 0)
  const fh = Number(frame.height || 0)

  return allActiveElements.filter((el) => {
    if (!el || el.isDeleted) return false
    if (el.id === frame.id) return true
    if (el.frameId === frame.id) return true
    const cx = Number(el.x || 0) + Number(el.width || 0) / 2
    const cy = Number(el.y || 0) + Number(el.height || 0) / 2
    return cx >= fx && cx <= fx + fw && cy >= fy && cy <= fy + fh
  })
}
