/** 程序说明：画布选中元素 AI 快捷动作菜单（E9），为图片/多图/脚本文字框提供一键带入对话并填充常用指令模板。 */
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useCanvas } from '@/contexts/canvas'
import { eventBus, TCanvasAddImagesToChatEvent } from '@/lib/event'
import { ChevronDown, Film, ImagePlus, Layers, Palette, Sparkles, Volume2, Wand2 } from 'lucide-react'
import React, { memo } from 'react'
import { useTranslation } from 'react-i18next'

type CanvasQuickActionsProps = {
  selectedImages: TCanvasAddImagesToChatEvent
  selectedTexts: string[]
}

export const CanvasQuickActions: React.FC<CanvasQuickActionsProps> = ({
  selectedImages,
  selectedTexts,
}) => {
  const { t } = useTranslation()
  const { excalidrawAPI } = useCanvas()

  const applyQuickAction = (instruction: string) => {
    if (selectedImages.length > 0) {
      eventBus.emit('Canvas::AddImagesToChat', selectedImages)
    }
    const mergedTexts = [...selectedTexts, instruction].filter(Boolean)
    if (mergedTexts.length > 0) {
      eventBus.emit('Canvas::AddTextToChat', mergedTexts)
    }
    excalidrawAPI?.updateScene({
      appState: { selectedElementIds: {} },
    })
  }

  const hasImages = selectedImages.length > 0
  const hasMultipleImages = selectedImages.length >= 2
  const hasTexts = selectedTexts.length > 0

  if (!hasImages && !hasTexts) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label={t('canvas:popbar.quickActions', { defaultValue: 'AI 快捷动作' })}
          className="min-h-7 gap-1 px-2 text-xs font-medium"
        >
          <Sparkles className="size-3.5 text-amber-500" aria-hidden="true" />
          <span>{t('canvas:popbar.quickActions', { defaultValue: 'AI 动作' })}</span>
          <ChevronDown className="size-3 opacity-70" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="center" className="w-56">
        {hasImages && (
          <>
            <DropdownMenuItem
              onClick={() =>
                applyQuickAction(
                  '以 <Picture 1> 为底图，保持人物主体、姿态与构图不变，进一步精修光影层次与材质细节。'
                )
              }
            >
              <Wand2 className="mr-2 size-4" aria-hidden="true" />
              <span>精修光影与质感细节</span>
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() =>
                applyQuickAction(
                  '保持 <Picture 1> 的核心主体与造型一致，将背景环境替换为：'
                )
              }
            >
              <Palette className="mr-2 size-4" aria-hidden="true" />
              <span>保持主体替换背景场景</span>
            </DropdownMenuItem>
            {hasMultipleImages && (
              <DropdownMenuItem
                onClick={() =>
                  applyQuickAction(
                    '以 <Picture 1> 为主画面底图，将 <Picture 2> 中的关键元素自然融合进场景，保持透视与光影统一。'
                  )
                }
              >
                <Layers className="mr-2 size-4" aria-hidden="true" />
                <span>多参考图自然融合创作</span>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem
              onClick={() =>
                applyQuickAction(
                  '以此图作为起始首帧生成 5 秒高清动态视频：镜头柔和推进，主体动作自然舒展，光影与环境声音细腻生动。'
                )
              }
            >
              <Film className="mr-2 size-4" aria-hidden="true" />
              <span>以此图首帧生成动态视频</span>
            </DropdownMenuItem>
          </>
        )}
        {hasTexts && (
          <>
            <DropdownMenuItem
              onClick={() =>
                applyQuickAction('请严格按上方画布脚本描述直接生成一张高清主视觉图像。')
              }
            >
              <ImagePlus className="mr-2 size-4" aria-hidden="true" />
              <span>按此脚本直接生成图像</span>
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() =>
                applyQuickAction('请按上方分镜脚本直接生成一段带同步音效的高清动态视频。')
              }
            >
              <Film className="mr-2 size-4" aria-hidden="true" />
              <span>按此分镜脚本生成视频</span>
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() =>
                applyQuickAction('请将上方画布文字框中的台词或旁白合成为自然清晰的人声配音音频并放入画布。')
              }
            >
              <Volume2 className="mr-2 size-4" aria-hidden="true" />
              <span>按此脚本生成配音音频</span>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export default memo(CanvasQuickActions)
