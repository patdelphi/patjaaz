/** 程序说明：渲染画布工具栏单个按钮及快捷键提示。 */
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import React from 'react'
import { useTranslation } from 'react-i18next'
import icons, { toolShortcuts, ToolType } from './CanvasMenuIcon'

type CanvasMenuButtonProps = {
  type: ToolType
  active?: boolean
  activeTool?: ToolType
  onClick?: () => void
}

const CanvasMenuButton = ({
  type,
  active,
  activeTool,
  onClick,
}: CanvasMenuButtonProps) => {
  const { t } = useTranslation()
  const isActive = activeTool === type || active
  const shortcut = toolShortcuts[type]

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t(`canvas:tool.${type}`)}
          className={cn(
            'p-2 rounded-md cursor-pointer hover:bg-primary/5',
            isActive && 'bg-primary/10'
          )}
          onMouseDown={(e) => {
            e.preventDefault()
            onClick?.()
          }}
        >
          {React.createElement(icons[type], {
            className: 'size-4',
          })}
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        {t(`canvas:tool.${type}`)}
        {shortcut ? ` (${shortcut})` : ''}
      </TooltipContent>
    </Tooltip>
  )
}

export default CanvasMenuButton
