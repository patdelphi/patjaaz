/** 程序说明：画布顶部导出按钮组，支持选中图片/视频/音频原始文件打包下载，以及整张画布或选区导出为合成视频封面帧的 PNG/SVG。 */
import { useCanvas } from '@/contexts/canvas'
import { buildExportableSceneWithVideoPosters } from '@/lib/canvasExportComposite'
import {
  buildPdfFromJpegPages,
  collectElementsForFrame,
  FrameExportFormat,
} from '@/lib/canvasFrameExport'
import { extractApiFilename, isAudioUrl } from '@/lib/canvasMediaNormalize'
import { saveAs } from 'file-saver'
import JSZip from 'jszip'
import { ChevronDown, FileCode2, FileImage, FileText, FolderDown, ImageDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '../ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu'

const CanvasExport = () => {
  const { excalidrawAPI } = useCanvas()
  const { t } = useTranslation()

  const downloadImage = async (imageUrl: string): Promise<string> => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.src = imageUrl
    return new Promise((resolve, reject) => {
      image.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = image.width
        canvas.height = image.height
        const ctx = canvas.getContext('2d')
        ctx?.drawImage(image, 0, 0)
        const dataURL = canvas.toDataURL('image/png')
        resolve(dataURL)
      }
      image.onerror = () => {
        reject(new Error('Failed to load image'))
      }
    })
  }

  const handleExportSelectedAssets = async () => {
    if (!excalidrawAPI) return
    const toastId = toast.loading(t('canvas:messages.exportingAssets'))
    try {
      const appState = excalidrawAPI.getAppState()
      const elements = excalidrawAPI.getSceneElements()

      const selectedIds = Object.keys(appState.selectedElementIds).filter(
        (id) => appState.selectedElementIds[id]
      )

      const mediaElements = elements.filter(
        (element) =>
          selectedIds.includes(element.id) &&
          (element.type === 'image' || element.type === 'embeddable')
      )

      if (mediaElements.length === 0) {
        toast.error(t('canvas:messages.nothingSelected'))
        return
      }

      const files = excalidrawAPI.getFiles()
      const embeddableElements = mediaElements.filter((el) => el.type === 'embeddable')
      const imageElements = mediaElements.filter((el) => el.type === 'image')

      const embedUrls = embeddableElements
        .map((el) => ('link' in el && typeof el.link === 'string' && el.link ? el.link : null))
        .filter((url): url is string => url !== null)

      const imageUrls = imageElements
        .map((el) => {
          if ('fileId' in el && el.fileId) {
            const raw = files[el.fileId]?.dataURL
            return raw ? String(raw) : null
          }
          return null
        })
        .filter((url): url is string => url !== null)

      if (imageUrls.length === 0 && embedUrls.length === 0) {
        toast.error(t('canvas:messages.nothingSelected'))
        return
      }

      const randomId = Math.random().toString(36).substring(2, 10)

      if (imageUrls.length === 1 && embedUrls.length === 0) {
        const dataURL = await downloadImage(imageUrls[0])
        saveAs(dataURL, `Asset-${randomId}.png`)
        return
      }

      if (embedUrls.length === 1 && imageUrls.length === 0) {
        const targetUrl = embedUrls[0]
        const response = await fetch(targetUrl)
        const blob = await response.blob()
        const fallbackExt = isAudioUrl(targetUrl) ? 'wav' : 'mp4'
        const fileName = extractApiFilename(targetUrl) || `Asset-${randomId}.${fallbackExt}`
        saveAs(blob, fileName)
        return
      }

      const zip = new JSZip()
      await Promise.all(
        embedUrls.map(async (mediaUrl, index) => {
          const response = await fetch(mediaUrl)
          const blob = await response.blob()
          const fallbackExt = isAudioUrl(mediaUrl) ? 'wav' : 'mp4'
          const kindPrefix = isAudioUrl(mediaUrl) ? 'audio' : 'video'
          const origName = extractApiFilename(mediaUrl)
          const ext = origName?.split('.').pop() || fallbackExt
          zip.file(`${kindPrefix}-${index + 1}.${ext}`, blob)
        })
      )

      await Promise.all(
        imageUrls.map(async (imageUrl, index) => {
          const dataURL = await downloadImage(imageUrl)
          if (dataURL) {
            zip.file(
              `image-${index + 1}.png`,
              dataURL.replace('data:image/png;base64,', ''),
              { base64: true }
            )
          }
        })
      )

      const content = await zip.generateAsync({ type: 'blob' })
      saveAs(content, `Asset-${randomId}.zip`)
    } catch {
      toast.error(t('canvas:messages.failedToExportImages'), {
        id: toastId,
      })
    } finally {
      toast.dismiss(toastId)
    }
  }

  const handleExportWholeCanvas = async (format: 'png' | 'svg') => {
    if (!excalidrawAPI) return
    const toastId = toast.loading(t('canvas:messages.exportingAssets'))
    try {
      const appState = excalidrawAPI.getAppState()
      const allElements = excalidrawAPI.getSceneElements()
      const activeElements = allElements.filter((el) => !el.isDeleted)
      if (activeElements.length === 0) {
        toast.error(t('canvas:messages.nothingSelected'))
        return
      }

      // 若当前有选中元素则优先导出选中分镜区域，未选中时导出整张画布
      const selectedIds = Object.keys(appState.selectedElementIds || {}).filter(
        (id) => appState.selectedElementIds[id]
      )
      const targetElements =
        selectedIds.length > 0
          ? activeElements.filter((el) => selectedIds.includes(el.id))
          : activeElements

      const composite = await buildExportableSceneWithVideoPosters(
        targetElements,
        excalidrawAPI.getFiles()
      )
      const excalidrawModule = await import('@excalidraw/excalidraw')
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')

      if (format === 'png') {
        const blob = await excalidrawModule.exportToBlob({
          elements: composite.elements,
          appState: {
            ...appState,
            exportBackground: true,
            exportWithDarkMode: false,
          },
          files: composite.files,
          mimeType: 'image/png',
        })
        saveAs(blob, `Canvas-${stamp}.png`)
      } else {
        const svgElement = await excalidrawModule.exportToSvg({
          elements: composite.elements,
          appState: {
            ...appState,
            exportBackground: true,
            exportWithDarkMode: false,
          },
          files: composite.files,
        })
        const serializer = new XMLSerializer()
        const svgMarkup = serializer.serializeToString(svgElement)
        const svgBlob = new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' })
        saveAs(svgBlob, `Canvas-${stamp}.svg`)
      }
      toast.success(t('canvas:messages.canvasExported'))
    } catch (err) {
      console.error('Failed to export canvas:', err)
      toast.error(t('canvas:messages.failedToExportImages'), { id: toastId })
    } finally {
      toast.dismiss(toastId)
    }
  }

  // 按 Frame 分镜框批量多格式倍率导出（PNG/JPG/WebP 1x/2x）与多页 PDF 导出（X1）
  const handleExportFramesBatch = async (
    format: FrameExportFormat | 'pdf',
    scale: 1 | 2 = 2
  ) => {
    if (!excalidrawAPI) return
    const toastId = toast.loading('正在按分镜框渲染导出…')
    try {
      const appState = excalidrawAPI.getAppState()
      const active = excalidrawAPI.getSceneElements().filter((el) => !el.isDeleted)
      if (active.length === 0) {
        toast.error(t('canvas:messages.nothingSelected'))
        return
      }
      const frames = active.filter((el) => el.type === 'frame')
      const frameGroups =
        frames.length > 0
          ? frames.map((f, idx) => ({
              name: (f.name || `Frame-${idx + 1}`).replace(/[\\/:*?"<>|]/g, '_'),
              items: collectElementsForFrame(f, active),
            }))
          : [{ name: 'Canvas-Full', items: active }]

      const excalidrawModule = await import('@excalidraw/excalidraw')
      const files = excalidrawAPI.getFiles()
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')

      if (format === 'pdf') {
        const pdfPages: { jpegBytes: Uint8Array; widthPx: number; heightPx: number }[] = []
        for (const grp of frameGroups) {
          const composite = await buildExportableSceneWithVideoPosters(grp.items, files)
          const cv = await excalidrawModule.exportToCanvas({
            elements: composite.elements,
            appState: { ...appState, exportBackground: true, exportWithDarkMode: false },
            files: composite.files,
            getDimensions: (w: number, h: number) => ({ width: w * scale, height: h * scale, scale }),
          })
          const jpgBlob = await new Promise<Blob | null>((res) =>
            cv.toBlob(res, 'image/jpeg', 0.92)
          )
          if (jpgBlob) {
            const buf = new Uint8Array(await jpgBlob.arrayBuffer())
            pdfPages.push({ jpegBytes: buf, widthPx: cv.width, heightPx: cv.height })
          }
        }
        const pdfBytes = buildPdfFromJpegPages(pdfPages)
        saveAs(
          new Blob([pdfBytes.buffer as ArrayBuffer], { type: 'application/pdf' }),
          `Storyboard-${stamp}.pdf`
        )
        toast.success('已导出分镜 PDF')
        return
      }

      const mime = `image/${format}`
      const ext = format === 'jpeg' ? 'jpg' : format
      if (frameGroups.length === 1) {
        const composite = await buildExportableSceneWithVideoPosters(frameGroups[0].items, files)
        const cv = await excalidrawModule.exportToCanvas({
          elements: composite.elements,
          appState: { ...appState, exportBackground: true, exportWithDarkMode: false },
          files: composite.files,
          getDimensions: (w: number, h: number) => ({ width: w * scale, height: h * scale, scale }),
        })
        const outBlob = await new Promise<Blob | null>((res) => cv.toBlob(res, mime, 0.92))
        if (outBlob) {
          saveAs(outBlob, `${frameGroups[0].name}-${scale}x.${ext}`)
        }
        toast.success('导出完成')
        return
      }

      const zip = new JSZip()
      for (let i = 0; i < frameGroups.length; i++) {
        const grp = frameGroups[i]
        const composite = await buildExportableSceneWithVideoPosters(grp.items, files)
        const cv = await excalidrawModule.exportToCanvas({
          elements: composite.elements,
          appState: { ...appState, exportBackground: true, exportWithDarkMode: false },
          files: composite.files,
          getDimensions: (w: number, h: number) => ({ width: w * scale, height: h * scale, scale }),
        })
        const outBlob = await new Promise<Blob | null>((res) => cv.toBlob(res, mime, 0.92))
        if (outBlob) {
          zip.file(`${String(i + 1).padStart(2, '0')}-${grp.name}-${scale}x.${ext}`, outBlob)
        }
      }
      const zipBlob = await zip.generateAsync({ type: 'blob' })
      saveAs(zipBlob, `Frames-${scale}x-${stamp}.zip`)
      toast.success(`已按 ${frameGroups.length} 个分镜框打包导出`)
    } catch (err) {
      console.error('Failed to batch export frames:', err)
      toast.error(t('canvas:messages.failedToExportImages'), { id: toastId })
    } finally {
      toast.dismiss(toastId)
    }
  }

  return (
    <div className="inline-flex -space-x-px rounded-md shadow-xs rtl:space-x-reverse">
      <Button
        className="rounded-none shadow-none first:rounded-s-md h-8"
        variant="outline"
        onClick={handleExportSelectedAssets}
      >
        <ImageDown className="size-4" aria-hidden="true" />
        {t('canvas:exportImages')}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            className="rounded-none shadow-none last:rounded-e-md h-8 px-2"
            variant="outline"
            aria-label={t('canvas:exportMoreOptions', { defaultValue: 'Export options' })}
          >
            <ChevronDown className="size-3.5" aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={handleExportSelectedAssets}>
            <ImageDown className="mr-2 size-4" aria-hidden="true" />
            {t('canvas:exportSelectedAssets', { defaultValue: '导出选中素材原文件' })}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => void handleExportWholeCanvas('png')}>
            <FileImage className="mr-2 size-4" aria-hidden="true" />
            {t('canvas:exportCanvasPng', { defaultValue: '导出画布为 PNG（含视频封面）' })}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => void handleExportWholeCanvas('svg')}>
            <FileCode2 className="mr-2 size-4" aria-hidden="true" />
            {t('canvas:exportCanvasSvg', { defaultValue: '导出画布为 SVG（含视频封面）' })}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => void handleExportFramesBatch('png', 2)}>
            <FolderDown className="mr-2 size-4" aria-hidden="true" />
            <span>按 Frame 分镜批量导出 PNG (2×)</span>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => void handleExportFramesBatch('webp', 2)}>
            <FolderDown className="mr-2 size-4" aria-hidden="true" />
            <span>按 Frame 分镜批量导出 WebP (2×)</span>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => void handleExportFramesBatch('jpeg', 2)}>
            <FolderDown className="mr-2 size-4" aria-hidden="true" />
            <span>按 Frame 分镜批量导出 JPG (2×)</span>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => void handleExportFramesBatch('pdf', 2)}>
            <FileText className="mr-2 size-4" aria-hidden="true" />
            <span>按 Frame 分镜导出多页 PDF</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export default CanvasExport
