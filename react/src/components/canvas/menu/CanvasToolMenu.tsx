/** 程序说明：提供分组折叠的底部中央画布工具栏，涵盖基础绘图、形状组、粗/块箭头及画框/橡皮/激光工具。 */
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
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
import { BlockArrowVariant, createBlockArrowElement } from '@/lib/blockArrow'
import {
  createCalloutBadgeSkeletons,
  getNextCalloutNumber,
} from '@/lib/calloutBadge'
import { CAPTURE_UPDATE_IMMEDIATELY } from '@/lib/excalidrawMutation'
import { cn } from '@/lib/utils'
import { convertToExcalidrawElements } from '@excalidraw/excalidraw'
import {
  ArrowLeftRight,
  ChevronDown,
  CornerUpRight,
  ListOrdered,
  MoveRight,
  Wrench,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import CanvasMenuButton from './CanvasMenuButton'
import icons, { toolShortcuts, ToolType } from './CanvasMenuIcon'

const SHAPE_TOOLS: ToolType[] = ['rectangle', 'diamond', 'ellipse']
const MORE_TOOLS: ToolType[] = ['frame', 'eraser', 'laser']

const CanvasToolMenu = () => {
  const { t } = useTranslation()
  const { excalidrawAPI } = useCanvas()

  const [activeTool, setActiveTool] = useState<ToolType | undefined>(undefined)
  const [lastShapeTool, setLastShapeTool] = useState<ToolType>('rectangle')

  const handleToolChange = (tool: ToolType) => {
    if (SHAPE_TOOLS.includes(tool)) {
      setLastShapeTool(tool)
    }
    excalidrawAPI?.setActiveTool({ type: tool })
  }

  const handleInsertCalloutBadge = () => {
    if (!excalidrawAPI) return
    const appState = excalidrawAPI.getAppState()
    const currentElements = excalidrawAPI.getSceneElements()
    const zoom = appState.zoom.value || 1
    const centerX = -appState.scrollX + appState.width / (2 * zoom)
    const centerY = -appState.scrollY + appState.height / (2 * zoom)
    const nextNumber = getNextCalloutNumber(currentElements)
    // 连续插入时按编号轻微错开坐标，避免多个角标完全重叠
    const jitterOffset = ((nextNumber - 1) % 6) * 24
    const skeletons = createCalloutBadgeSkeletons(
      nextNumber,
      centerX + jitterOffset,
      centerY + jitterOffset
    )
    const badgeElements = convertToExcalidrawElements(skeletons)
    const selectedMap: Record<string, true> = {}
    for (const item of badgeElements) {
      selectedMap[item.id] = true
    }
    excalidrawAPI.updateScene({
      elements: [...currentElements, ...badgeElements],
      appState: {
        selectedElementIds: selectedMap,
      },
      captureUpdate: CAPTURE_UPDATE_IMMEDIATELY,
    })
  }

  const handleInsertBlockArrow = (variant: BlockArrowVariant) => {
    if (!excalidrawAPI) return
    const appState = excalidrawAPI.getAppState()
    const zoom = appState.zoom?.value || 1
    const centerX = -appState.scrollX + appState.width / (2 * zoom)
    const centerY = -appState.scrollY + appState.height / (2 * zoom)
    const width = 240
    const height = variant === 'curved' ? 120 : 96

    const arrowEl = createBlockArrowElement({
      x: Math.round(centerX - width / 2),
      y: Math.round(centerY - height / 2),
      width,
      height,
      variant,
    })

    excalidrawAPI.updateScene({
      elements: [...excalidrawAPI.getSceneElements(), arrowEl],
      appState: {
        selectedElementIds: { [arrowEl.id]: true },
      },
      captureUpdate: CAPTURE_UPDATE_IMMEDIATELY,
    })
    excalidrawAPI.setActiveTool({ type: 'selection' })
  }

  useExcalidrawChange(excalidrawAPI, (_elements, appState, _files) => {
    const nextTool = appState.activeTool.type as ToolType
    setActiveTool(nextTool)
    if (SHAPE_TOOLS.includes(nextTool)) {
      setLastShapeTool(nextTool)
    }
  })

  const isShapeActive = activeTool !== undefined && SHAPE_TOOLS.includes(activeTool)
  const isMoreActive = activeTool !== undefined && MORE_TOOLS.includes(activeTool)
  const CurrentShapeIcon = icons[isShapeActive && activeTool ? activeTool : lastShapeTool]

  return (
    <div className="absolute bottom-5 left-1/2 -translate-x-1/2 z-20 flex items-center gap-1 bg-primary-foreground/75 backdrop-blur-lg rounded-lg p-1 shadow-[0_5px_10px_rgba(0,0,0,0.08)] border border-primary/10">
      <CanvasMenuButton
        type="hand"
        activeTool={activeTool}
        onClick={() => handleToolChange('hand')}
      />
      <CanvasMenuButton
        type="selection"
        activeTool={activeTool}
        onClick={() => handleToolChange('selection')}
      />

      <Separator orientation="vertical" className="h-6! bg-primary/5" />

      {/* 形状组：支持直接点击切换最近形状或展开选择矩形/菱形/椭圆 */}
      <div className="flex items-center">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t(`canvas:tool.${lastShapeTool}`)}
              className={cn(
                'p-2 rounded-md cursor-pointer hover:bg-primary/5',
                isShapeActive && 'bg-primary/10'
              )}
              onMouseDown={(e) => {
                e.preventDefault()
                handleToolChange(lastShapeTool)
              }}
            >
              <CurrentShapeIcon className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('canvas:tool.shape')}</TooltipContent>
        </Tooltip>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t('canvas:tool.shape')}
              className="h-8 w-5 p-0 cursor-pointer hover:bg-primary/5"
            >
              <ChevronDown className="size-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="center">
            {SHAPE_TOOLS.map((shape) => {
              const Icon = icons[shape]
              return (
                <DropdownMenuItem
                  key={shape}
                  onClick={() => handleToolChange(shape)}
                  className={cn(activeTool === shape && 'bg-accent')}
                >
                  <Icon className="mr-2 size-4" />
                  <span>{t(`canvas:tool.${shape}`)}</span>
                  <span className="ml-auto pl-4 text-xs text-muted-foreground">
                    {toolShortcuts[shape]}
                  </span>
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <CanvasMenuButton
        type="arrow"
        activeTool={activeTool}
        onClick={() => handleToolChange('arrow')}
      />
      <CanvasMenuButton
        type="line"
        activeTool={activeTool}
        onClick={() => handleToolChange('line')}
      />

      {/* 块箭头组：生成参数化可填充直/双向/弯闭合多边形箭头 */}
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                aria-label={t('canvas:tool.blockArrow')}
                className="h-9 gap-0.5 px-2 rounded-md cursor-pointer hover:bg-primary/5"
              >
                <MoveRight className="size-4" />
                <ChevronDown className="size-3 opacity-70" />
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>{t('canvas:tool.blockArrow')}</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="center">
          <DropdownMenuItem onClick={() => handleInsertBlockArrow('straight')}>
            <MoveRight className="mr-2 size-4" />
            <span>{t('canvas:tool.blockArrow_straight')}</span>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => handleInsertBlockArrow('double')}>
            <ArrowLeftRight className="mr-2 size-4" />
            <span>{t('canvas:tool.blockArrow_double')}</span>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => handleInsertBlockArrow('curved')}>
            <CornerUpRight className="mr-2 size-4" />
            <span>{t('canvas:tool.blockArrow_curved')}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Separator orientation="vertical" className="h-6! bg-primary/5" />

      <CanvasMenuButton
        type="freedraw"
        activeTool={activeTool}
        onClick={() => handleToolChange('freedraw')}
      />
      <CanvasMenuButton
        type="text"
        activeTool={activeTool}
        onClick={() => handleToolChange('text')}
      />
      <CanvasMenuButton
        type="image"
        activeTool={activeTool}
        onClick={() => handleToolChange('image')}
      />
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t('canvas:tool.calloutBadge', { defaultValue: '序号标注' })}
            className="size-9 rounded-md cursor-pointer hover:bg-primary/5"
            onClick={handleInsertCalloutBadge}
          >
            <ListOrdered className="size-4" aria-hidden="true" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          {t('canvas:tool.calloutBadge', { defaultValue: '自动递增序号标注 (1, 2, 3...)' })}
        </TooltipContent>
      </Tooltip>

      <Separator orientation="vertical" className="h-6! bg-primary/5" />

      {/* 扩展工具组：Frame 画框、橡皮擦、激光笔 */}
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                aria-label={t('canvas:tool.moreTools')}
                className={cn(
                  'h-9 gap-0.5 px-2 rounded-md cursor-pointer hover:bg-primary/5',
                  isMoreActive && 'bg-primary/10'
                )}
              >
                <Wrench className="size-4" />
                <ChevronDown className="size-3 opacity-70" />
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>{t('canvas:tool.moreTools')}</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="end">
          {MORE_TOOLS.map((tool) => {
            const Icon = icons[tool]
            return (
              <DropdownMenuItem
                key={tool}
                onClick={() => handleToolChange(tool)}
                className={cn(activeTool === tool && 'bg-accent')}
              >
                <Icon className="mr-2 size-4" />
                <span>{t(`canvas:tool.${tool}`)}</span>
                <span className="ml-auto pl-4 text-xs text-muted-foreground">
                  {toolShortcuts[tool]}
                </span>
              </DropdownMenuItem>
            )
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export default CanvasToolMenu
