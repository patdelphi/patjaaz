/** 程序说明：底部左侧视图与历史控制栏，提供撤销、重做、缩放倍率调节与一键适配画布。 */
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Separator } from '@/components/ui/separator'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useCanvas } from '@/contexts/canvas'
import { useExcalidrawChange } from '@/hooks/use-excalidraw-change'
import {
  readExcalidrawHistoryState,
  triggerExcalidrawHistory,
} from '@/lib/excalidrawHistory'
import { cn } from '@/lib/utils'
import { Maximize2, Minus, Plus, Redo2, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

const CanvasViewMenu = () => {
  const { t } = useTranslation()
  const { excalidrawAPI } = useCanvas()

  const [currentZoom, setCurrentZoom] = useState<number>(100)
  const [historyState, setHistoryState] = useState({ canUndo: true, canRedo: true })

  const handleZoomChange = (rawZoom: number) => {
    const clamped = Math.min(500, Math.max(10, Math.round(rawZoom)))
    excalidrawAPI?.updateScene({
      appState: {
        zoom: {
          // @ts-expect-error Excalidraw Zoom type expects NormalizedZoomValue brand
          value: clamped / 100,
        },
      },
    })
  }

  const handleZoomFit = () => {
    excalidrawAPI?.scrollToContent(undefined, {
      fitToContent: true,
      animate: true,
    })
  }

  useExcalidrawChange(excalidrawAPI, (_elements, appState, _files) => {
    const zoom = Math.round(appState.zoom.value * 100)
    setCurrentZoom(zoom)
    setHistoryState(readExcalidrawHistoryState())
  })

  return (
    <div
      className={cn(
        'absolute bottom-5 left-4 flex items-center gap-0.5 rounded-lg p-1 z-20 select-none',
        'bg-primary-foreground/75 backdrop-blur-lg shadow-[0_5px_10px_rgba(0,0,0,0.08)] border border-primary/10 text-primary/80'
      )}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            className="size-8"
            variant="ghost"
            size="icon"
            aria-label={t('canvas:tool.undo')}
            disabled={!historyState.canUndo}
            onClick={() => triggerExcalidrawHistory('undo')}
          >
            <Undo2 className="size-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t('canvas:tool.undo')} (Ctrl+Z)</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            className="size-8"
            variant="ghost"
            size="icon"
            aria-label={t('canvas:tool.redo')}
            disabled={!historyState.canRedo}
            onClick={() => triggerExcalidrawHistory('redo')}
          >
            <Redo2 className="size-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t('canvas:tool.redo')} (Ctrl+Shift+Z)</TooltipContent>
      </Tooltip>

      <Separator orientation="vertical" className="mx-1 h-5! bg-primary/10" />

      <Button
        className="size-8"
        variant="ghost"
        size="icon"
        aria-label={t('canvas:tool.zoomOut')}
        onClick={() => handleZoomChange(currentZoom - 10)}
      >
        <Minus className="size-4" />
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 px-1.5 text-xs font-medium min-w-12">
            {currentZoom}%
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {[10, 50, 100, 150, 200].map((zoom) => (
            <DropdownMenuItem key={zoom} onClick={() => handleZoomChange(zoom)}>
              {zoom}%
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={handleZoomFit}>
            {t('canvas:tool.zoomFit')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Button
        className="size-8"
        variant="ghost"
        size="icon"
        aria-label={t('canvas:tool.zoomIn')}
        onClick={() => handleZoomChange(currentZoom + 10)}
      >
        <Plus className="size-4" />
      </Button>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            className="size-8"
            variant="ghost"
            size="icon"
            aria-label={t('canvas:tool.zoomFit')}
            onClick={handleZoomFit}
          >
            <Maximize2 className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t('canvas:tool.zoomFit')}</TooltipContent>
      </Tooltip>
    </div>
  )
}

export default CanvasViewMenu
