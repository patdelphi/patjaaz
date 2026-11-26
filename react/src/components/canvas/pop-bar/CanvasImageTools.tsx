/** 程序说明：选中图像高级交互控件组（G2/E8/C9）：提供画笔遮罩局部重绘、改图前后滑块对比、水平翻转、圆角切换及血缘参数查看与一键换种重抽。 */
import { Button } from '@/components/ui/button'
import { useCanvas } from '@/contexts/canvas'
import { apiFetch } from '@/lib/apiFetch'
import { extractApiFilename } from '@/lib/canvasMediaNormalize'
import { eventBus, TCanvasAddImagesToChatEvent } from '@/lib/event'
import { mutateSceneElements } from '@/lib/excalidrawMutation'
import type { ExcalidrawImageElement } from '@excalidraw/excalidraw/element/types'
import {
  Brush,
  Columns2,
  FlipHorizontal2,
  GitBranch,
  RefreshCw,
  SquareRoundCorner,
  Undo2,
} from 'lucide-react'
import React, { memo, useEffect, useId, useRef, useState } from 'react'
import { toast } from 'sonner'

type LineageMeta = {
  workflowName?: string
  displayName?: string
  capability?: string
  prompt?: string
  params?: Record<string, unknown>
  parentFileIds?: string[]
}

type CanvasImageToolsProps = {
  selectedImageElements: ExcalidrawImageElement[]
  selectedImagesForChat: TCanvasAddImagesToChatEvent
}

export const CanvasImageTools: React.FC<CanvasImageToolsProps> = ({
  selectedImageElements,
  selectedImagesForChat,
}) => {
  const { excalidrawAPI } = useCanvas()
  const maskDialogRef = useRef<HTMLDialogElement>(null)
  const compareDialogRef = useRef<HTMLDialogElement>(null)
  const lineageDialogRef = useRef<HTMLDialogElement>(null)

  const maskTitleId = useId()
  const compareTitleId = useId()
  const lineageTitleId = useId()

  const baseImgCanvasRef = useRef<HTMLCanvasElement>(null)
  const strokeCanvasRef = useRef<HTMLCanvasElement>(null)
  const [brushSize, setBrushSize] = useState<number>(36)
  const [isDrawing, setIsDrawing] = useState<boolean>(false)
  const [maskSubmitting, setMaskSubmitting] = useState<boolean>(false)
  const [inpaintPrompt, setInpaintPrompt] = useState<string>('')
  const [canvasDim, setCanvasDim] = useState<{ w: number; h: number }>({ w: 640, h: 480 })
  const historyDataRef = useRef<ImageData[]>([])

  const [compareSplit, setCompareSplit] = useState<number>(50)
  const [compareUrls, setCompareUrls] = useState<{ before: string; after: string } | null>(null)

  const primaryElem = selectedImageElements[0]
  const files = excalidrawAPI?.getFiles() ?? {}
  const primaryUrl =
    (primaryElem?.fileId && files[primaryElem.fileId]?.dataURL) ||
    selectedImagesForChat[0]?.sourceUrl ||
    ''

  const lineage: LineageMeta | null = (() => {
    const cd = (primaryElem?.customData || {}) as Record<string, unknown>
    if (cd.jaazLineage && typeof cd.jaazLineage === 'object') {
      return cd.jaazLineage as LineageMeta
    }
    if (cd.workflowName || cd.parentFileIds) {
      return {
        workflowName: typeof cd.workflowName === 'string' ? cd.workflowName : undefined,
        parentFileIds: Array.isArray(cd.parentFileIds) ? (cd.parentFileIds as string[]) : undefined,
      }
    }
    return null
  })()

  // 解析可用于前后对比的配对图片（选中两张图，或当前图记录了上游父图 parentFileIds）
  const resolveComparePair = (): { before: string; after: string } | null => {
    if (selectedImageElements.length >= 2) {
      const firstId = selectedImageElements[0]?.fileId
      const secondId = selectedImageElements[1]?.fileId
      const u1 = firstId ? String(files[firstId]?.dataURL || '') : ''
      const u2 = secondId ? String(files[secondId]?.dataURL || '') : ''
      if (u1 && u2) return { before: u1, after: u2 }
    }
    const parentFile = lineage?.parentFileIds?.[0]
    if (parentFile && primaryUrl) {
      return { before: `/api/file/${parentFile}`, after: String(primaryUrl) }
    }
    return null
  }

  const handleFlipHorizontal = () => {
    if (!excalidrawAPI || selectedImageElements.length === 0) return
    const targetIds = new Set(selectedImageElements.map((el) => el.id))
    mutateSceneElements(excalidrawAPI, (el) => {
      if (!targetIds.has(el.id)) return el
      const imgEl = el as ExcalidrawImageElement
      const [sx, sy] = Array.isArray(imgEl.scale) ? imgEl.scale : [1, 1]
      return {
        ...imgEl,
        scale: [(-sx || -1) as 1 | -1, (sy || 1) as 1 | -1],
      }
    })
  }

  const handleToggleRoundness = () => {
    if (!excalidrawAPI || selectedImageElements.length === 0) return
    const targetIds = new Set(selectedImageElements.map((el) => el.id))
    mutateSceneElements(excalidrawAPI, (el) =>
      targetIds.has(el.id)
        ? { ...el, roundness: el.roundness ? null : { type: 3 } }
        : el
    )
  }

  const openMaskModal = () => {
    if (!primaryUrl) return
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      const maxEdge = 720
      const ratio = Math.min(1, maxEdge / Math.max(img.width, img.height))
      const dw = Math.max(120, Math.round(img.width * ratio))
      const dh = Math.max(120, Math.round(img.height * ratio))
      setCanvasDim({ w: dw, h: dh })
      requestAnimationFrame(() => {
        const baseCv = baseImgCanvasRef.current
        const strokeCv = strokeCanvasRef.current
        if (baseCv && strokeCv) {
          baseCv.width = dw
          baseCv.height = dh
          strokeCv.width = dw
          strokeCv.height = dh
          baseCv.getContext('2d')?.drawImage(img, 0, 0, dw, dh)
          strokeCv.getContext('2d')?.clearRect(0, 0, dw, dh)
          historyDataRef.current = []
        }
      })
    }
    img.src = String(primaryUrl)
    const dlg = maskDialogRef.current
    if (dlg && !dlg.open) {
      dlg.showModal()
    }
  }

  const drawPoint = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const cv = strokeCanvasRef.current
    if (!cv) return
    const rect = cv.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * cv.width
    const y = ((e.clientY - rect.top) / rect.height) * cv.height
    const ctx = cv.getContext('2d')
    if (!ctx) return
    ctx.fillStyle = 'rgba(239, 68, 68, 0.65)'
    ctx.beginPath()
    ctx.arc(x, y, brushSize / 2, 0, Math.PI * 2)
    ctx.fill()
  }

  const handlePointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const cv = strokeCanvasRef.current
    const ctx = cv?.getContext('2d')
    if (cv && ctx) {
      historyDataRef.current.push(ctx.getImageData(0, 0, cv.width, cv.height))
      if (historyDataRef.current.length > 15) historyDataRef.current.shift()
    }
    setIsDrawing(true)
    drawPoint(e)
  }

  const handleUndoStroke = () => {
    const cv = strokeCanvasRef.current
    const ctx = cv?.getContext('2d')
    const prev = historyDataRef.current.pop()
    if (cv && ctx) {
      if (prev) ctx.putImageData(prev, 0, 0)
      else ctx.clearRect(0, 0, cv.width, cv.height)
    }
  }

  const handleSubmitInpaintMask = async () => {
    const baseCv = baseImgCanvasRef.current
    const strokeCv = strokeCanvasRef.current
    if (!baseCv || !strokeCv || !primaryUrl) return

    setMaskSubmitting(true)
    try {
      // 合成 ComfyUI 标准 RGBA 透明通道遮罩图（涂抹区域 alpha=0 供 LoadImage mask 插槽直接读取）
      const outCv = document.createElement('canvas')
      outCv.width = baseCv.width
      outCv.height = baseCv.height
      const outCtx = outCv.getContext('2d')
      const strokeCtx = strokeCv.getContext('2d')
      if (!outCtx || !strokeCtx) throw new Error('Canvas 2D context unavailable')

      outCtx.drawImage(baseCv, 0, 0)
      const imgData = outCtx.getImageData(0, 0, outCv.width, outCv.height)
      const maskData = strokeCtx.getImageData(0, 0, strokeCv.width, strokeCv.height)
      let paintedPixels = 0
      for (let i = 0; i < maskData.data.length; i += 4) {
        if (maskData.data[i + 3] > 20) {
          imgData.data[i + 3] = 0
          paintedPixels++
        }
      }
      if (paintedPixels === 0) {
        toast.info('请先在画面上涂抹需要局部重绘的区域')
        setMaskSubmitting(false)
        return
      }
      outCtx.putImageData(imgData, 0, 0)

      const blob = await new Promise<Blob | null>((res) => outCv.toBlob(res, 'image/png'))
      if (!blob) throw new Error('Failed to encode mask PNG')

      const formData = new FormData()
      formData.append('file', blob, 'inpaint_mask.png')
      // max_size_mb=30 确保保留 RGBA 透明通道，不被压缩为不透明 JPEG
      const resp = await apiFetch('/api/upload_image?max_size_mb=30', {
        method: 'POST',
        body: formData,
      })
      if (!resp.ok) throw new Error(`Mask upload failed (${resp.status})`)
      const uploaded = (await resp.json()) as {
        file_id: string
        url: string
        width: number
        height: number
      }

      const origFileId =
        extractApiFilename(String(primaryUrl)) || selectedImagesForChat[0]?.fileId || ''
      let secondRefId = uploaded.file_id
      let regionHint = '涂抹区域'
      if (origFileId) {
        const guideResp = await apiFetch('/api/studio/prepare_mask_guide', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source_image: origFileId,
            mask_image: uploaded.file_id,
          }),
        })
        if (guideResp.ok) {
          const gData = (await guideResp.json()) as {
            guide_file_id: string
            region_label: string
          }
          secondRefId = gData.guide_file_id
          regionHint = gData.region_label || regionHint
        }
      }

      const chatImgs: TCanvasAddImagesToChatEvent = [
        ...(origFileId
          ? [
              {
                fileId: origFileId,
                width: primaryElem.width,
                height: primaryElem.height,
              },
            ]
          : []),
        {
          fileId: secondRefId,
          width: uploaded.width,
          height: uploaded.height,
        },
      ]
      eventBus.emit('Canvas::AddImagesToChat', chatImgs)
      const userGoal = inpaintPrompt.trim() || '（请在此补充替换内容）'
      const finalInstruction = origFileId
        ? `请参考原图 <Picture 1> (${origFileId}) 与红色高亮选区引导图 <Picture 2> (${secondRefId}，位于${regionHint})，仅将 <Picture 2> 红色框定区域修改为：${userGoal}；其余人物、服饰与背景严格保持 <Picture 1> 不变。`
        : userGoal
      eventBus.emit('Canvas::AddTextToChat', [finalInstruction])

      maskDialogRef.current?.close()
      toast.success('已合成局部重绘视觉引导图并带入对话')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '导出遮罩失败')
    } finally {
      setMaskSubmitting(false)
    }
  }

  const openCompareModal = () => {
    const pair = resolveComparePair()
    if (!pair) return
    setCompareUrls(pair)
    setCompareSplit(50)
    const dlg = compareDialogRef.current
    if (dlg && !dlg.open) {
      dlg.showModal()
    }
  }

  const openLineageModal = () => {
    const dlg = lineageDialogRef.current
    if (dlg && !dlg.open) {
      dlg.showModal()
    }
  }

  const handleRerollWithSameLineage = () => {
    if (!lineage) return
    const parents = (lineage.parentFileIds || []).map((fid) => ({
      fileId: fid,
      width: primaryElem?.width || 1024,
      height: primaryElem?.height || 1024,
    }))
    if (parents.length > 0) {
      eventBus.emit('Canvas::AddImagesToChat', parents)
    }
    const wfPart = lineage.workflowName ? `调用 ${lineage.workflowName} 工作流` : '使用相同模型'
    const promptPart = lineage.prompt ? `提示词：“${lineage.prompt}”` : '沿用上一版提示词'
    eventBus.emit('Canvas::AddTextToChat', [
      `请${wfPart}换一个新随机种子重新生成一版变体，${promptPart}。`,
    ])
    lineageDialogRef.current?.close()
    toast.success('已将同参数换种重抽指令填入对话')
  }

  const handleHighlightParentElements = () => {
    if (!excalidrawAPI || !lineage?.parentFileIds?.length) return
    const parentSet = new Set(lineage.parentFileIds)
    const sceneElements = excalidrawAPI.getSceneElements()
    const matchedIds: Record<string, true> = { [primaryElem.id]: true }
    let firstMatch = primaryElem as unknown as ExcalidrawImageElement
    for (const el of sceneElements) {
      if (el.isDeleted) continue
      const fid = 'fileId' in el && el.fileId ? String(el.fileId) : ''
      const durl = fid ? String(files[fid]?.dataURL || '') : ''
      const fname = extractApiFilename(durl)
      if (fname && parentSet.has(fname)) {
        matchedIds[el.id] = true
        firstMatch = el as ExcalidrawImageElement
      }
    }
    excalidrawAPI.updateScene({ appState: { selectedElementIds: matchedIds } })
    excalidrawAPI.scrollToContent(firstMatch, { animate: true })
    lineageDialogRef.current?.close()
  }

  // 重置 dialog.returnValue 防止跨次关闭残留旧值
  useEffect(() => {
    const dialogs = [maskDialogRef.current, compareDialogRef.current, lineageDialogRef.current]
    const cleanups = dialogs
      .filter((d): d is HTMLDialogElement => d !== null)
      .map((dlg) => {
        const onClose = () => {
          dlg.returnValue = ''
        }
        dlg.addEventListener('close', onClose)
        return () => dlg.removeEventListener('close', onClose)
      })
    return () => cleanups.forEach((fn) => fn())
  }, [])

  if (selectedImageElements.length === 0) return null
  const canCompare = Boolean(resolveComparePair())

  return (
    <>
      <div className="flex items-center gap-0.5 border-r border-border/60 pr-1">
        {selectedImageElements.length === 1 && primaryUrl && (
          <Button
            variant="ghost"
            size="sm"
            onClick={openMaskModal}
            title="涂抹遮罩局部重绘"
            className="min-h-7 px-2 text-xs gap-1"
          >
            <Brush className="size-3.5 text-rose-500" aria-hidden="true" />
            <span>遮罩重绘</span>
          </Button>
        )}
        {canCompare && (
          <Button
            variant="ghost"
            size="sm"
            onClick={openCompareModal}
            title="前后滑块对比"
            className="min-h-7 px-2 text-xs gap-1"
          >
            <Columns2 className="size-3.5 text-sky-500" aria-hidden="true" />
            <span>对比</span>
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={handleFlipHorizontal}
          title="水平镜像翻转"
          aria-label="水平镜像翻转"
          className="min-h-7 px-1.5"
        >
          <FlipHorizontal2 className="size-3.5" aria-hidden="true" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleToggleRoundness}
          title="切换圆角/直角边框"
          aria-label="切换圆角边框"
          className="min-h-7 px-1.5"
        >
          <SquareRoundCorner className="size-3.5" aria-hidden="true" />
        </Button>
        {lineage && (
          <Button
            variant="ghost"
            size="sm"
            onClick={openLineageModal}
            title="查看生成参数与血缘重抽"
            className="min-h-7 px-2 text-xs gap-1"
          >
            <GitBranch className="size-3.5 text-emerald-600" aria-hidden="true" />
            <span>血缘</span>
          </Button>
        )}
      </div>

      {/* 原生模态 Dialog：局部重绘涂抹遮罩画板 */}
      <dialog
        ref={maskDialogRef}
        aria-labelledby={maskTitleId}
        className="jaaz-native-modal rounded-xl border bg-background p-5 text-foreground shadow-2xl max-w-3xl w-[92vw]"
      >
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h1 id={maskTitleId} className="text-base font-semibold">
              局部重绘遮罩涂抹（红色涂抹区域将生成透明遮罩）
            </h1>
            <form method="dialog">
              <Button variant="ghost" size="sm" type="submit">
                关闭
              </Button>
            </form>
          </div>

          <div className="flex items-center gap-3 text-xs">
            <label className="flex items-center gap-2">
              <span>画笔粗细 ({brushSize}px)</span>
              <input
                type="range"
                min={10}
                max={96}
                value={brushSize}
                onChange={(e) => setBrushSize(Number(e.target.value))}
                className="w-28"
              />
            </label>
            <Button variant="outline" size="sm" type="button" onClick={handleUndoStroke}>
              <Undo2 className="mr-1 size-3.5" />
              撤销一笔
            </Button>
          </div>

          <div className="relative mx-auto overflow-hidden rounded-lg border bg-muted/40">
            <canvas
              ref={baseImgCanvasRef}
              width={canvasDim.w}
              height={canvasDim.h}
              className="block max-h-[56vh] w-auto"
            />
            <canvas
              ref={strokeCanvasRef}
              width={canvasDim.w}
              height={canvasDim.h}
              onPointerDown={handlePointerDown}
              onPointerMove={(e) => {
                if (isDrawing) drawPoint(e)
              }}
              onPointerUp={() => setIsDrawing(false)}
              onPointerLeave={() => setIsDrawing(false)}
              className="absolute inset-0 h-full w-full cursor-crosshair touch-none"
            />
          </div>

          <input
            type="text"
            value={inpaintPrompt}
            onChange={(e) => setInpaintPrompt(e.target.value)}
            placeholder="输入局部修改指令（例如：把涂抹处替换为点亮的暖黄纸灯笼）"
            className="h-9 w-full rounded-md border bg-background px-3 text-sm"
          />

          <div className="flex justify-end gap-2">
            <form method="dialog">
              <Button variant="outline" size="sm" type="submit">
                取消
              </Button>
            </form>
            <Button
              size="sm"
              type="button"
              disabled={maskSubmitting}
              onClick={() => void handleSubmitInpaintMask()}
            >
              {maskSubmitting ? '导出遮罩中…' : '生成遮罩并带入对话'}
            </Button>
          </div>
        </div>
      </dialog>

      {/* 原生模态 Dialog：改图前后滑块对比 */}
      <dialog
        ref={compareDialogRef}
        aria-labelledby={compareTitleId}
        className="jaaz-native-modal rounded-xl border bg-background p-5 text-foreground shadow-2xl max-w-3xl w-[92vw]"
      >
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h1 id={compareTitleId} className="text-base font-semibold">
              改图前后滑块对比（左：原图 / 右：改后图）
            </h1>
            <form method="dialog">
              <Button variant="ghost" size="sm" type="submit">
                关闭
              </Button>
            </form>
          </div>
          {compareUrls && (
            <>
              <div className="relative mx-auto max-h-[62vh] overflow-hidden rounded-lg border select-none">
                <img
                  src={compareUrls.after}
                  alt="修改后图像"
                  className="block max-h-[62vh] w-auto object-contain"
                />
                <img
                  src={compareUrls.before}
                  alt="修改前原图"
                  style={{ clipPath: `inset(0 ${100 - compareSplit}% 0 0)` }}
                  className="pointer-events-none absolute inset-0 h-full w-full object-contain"
                />
                <div
                  style={{ left: `${compareSplit}%` }}
                  className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow-[0_0_6px_rgba(0,0,0,0.6)]"
                />
              </div>
              <input
                type="range"
                aria-label="前后对比分界比例"
                min={0}
                max={100}
                value={compareSplit}
                onChange={(e) => setCompareSplit(Number(e.target.value))}
                className="w-full cursor-ew-resize"
              />
            </>
          )}
        </div>
      </dialog>

      {/* 原生模态 Dialog：生成血缘谱系与一键重抽 */}
      <dialog
        ref={lineageDialogRef}
        aria-labelledby={lineageTitleId}
        className="jaaz-native-modal rounded-xl border bg-background p-5 text-foreground shadow-2xl max-w-lg w-[90vw]"
      >
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h1 id={lineageTitleId} className="text-base font-semibold">
              生成资产血缘谱系与参数
            </h1>
            <form method="dialog">
              <Button variant="ghost" size="sm" type="submit">
                关闭
              </Button>
            </form>
          </div>

          {lineage && (
            <div className="space-y-2 text-xs">
              <div className="rounded-md bg-muted/60 p-2.5">
                <div className="font-medium">
                  工作流：{lineage.displayName || lineage.workflowName || '未知'}
                </div>
                {lineage.parentFileIds && lineage.parentFileIds.length > 0 && (
                  <div className="mt-1 text-muted-foreground">
                    上游输入资产：{lineage.parentFileIds.join(', ')}
                  </div>
                )}
              </div>
              {lineage.prompt && (
                <div className="rounded-md border p-2.5 max-h-36 overflow-y-auto whitespace-pre-wrap">
                  {lineage.prompt}
                </div>
              )}
              <div className="flex justify-end gap-2 pt-2">
                {lineage.parentFileIds && lineage.parentFileIds.length > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    type="button"
                    onClick={handleHighlightParentElements}
                  >
                    <GitBranch className="mr-1.5 size-3.5" />
                    在画布高亮上游父图
                  </Button>
                )}
                <Button size="sm" type="button" onClick={handleRerollWithSameLineage}>
                  <RefreshCw className="mr-1.5 size-3.5" />
                  同参数换种子重抽
                </Button>
              </div>
            </div>
          )}
        </div>
      </dialog>
    </>
  )
}

export default memo(CanvasImageTools)
