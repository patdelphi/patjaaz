/** 程序说明：为选中的闭合块箭头提供类型切换、填充与描边颜色、头长、杆宽及曲率调节面板。 */
import { Button } from '@/components/ui/button'
import { useCanvas } from '@/contexts/canvas'
import {
  BlockArrowParams,
  BlockArrowVariant,
  generateBlockArrowPoints,
  isBlockArrowElement,
  readBlockArrowParams,
} from '@/lib/blockArrow'
import { mutateSceneElements } from '@/lib/excalidrawMutation'
import { cn } from '@/lib/utils'
import type { ExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import { SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

const FILL_PRESETS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#18181b']
const STROKE_PRESETS = ['#1e3a8a', '#991b1b', '#065f46', '#92400e', '#000000', 'transparent']

type CanvasBlockArrowControlsProps = {
  selectedBlockArrows: ExcalidrawElement[]
}

const CanvasBlockArrowControls = ({ selectedBlockArrows }: CanvasBlockArrowControlsProps) => {
  const { t } = useTranslation()
  const { excalidrawAPI } = useCanvas()
  const [open, setOpen] = useState(false)

  const first = selectedBlockArrows[0]
  if (!first) return null

  const currentParams = readBlockArrowParams(first.customData)

  const updateBlockArrows = (
    patch: Partial<BlockArrowParams> & { backgroundColor?: string; strokeColor?: string }
  ) => {
    if (!excalidrawAPI) return
    const selectedIds = new Set(selectedBlockArrows.map((el) => el.id))

    mutateSceneElements(excalidrawAPI, (el) => {
      if (!selectedIds.has(el.id) || !isBlockArrowElement(el)) return el
      const nextParams: BlockArrowParams = {
        ...readBlockArrowParams(el.customData),
        ...(patch.variant !== undefined ? { variant: patch.variant } : {}),
        ...(patch.shaftRatio !== undefined ? { shaftRatio: patch.shaftRatio } : {}),
        ...(patch.headLengthPx !== undefined ? { headLengthPx: patch.headLengthPx } : {}),
        ...(patch.headWidthRatio !== undefined ? { headWidthRatio: patch.headWidthRatio } : {}),
        ...(patch.curvature !== undefined ? { curvature: patch.curvature } : {}),
      }
      const nextPoints = generateBlockArrowPoints(el.width, el.height, nextParams)
      return {
        ...el,
        backgroundColor: patch.backgroundColor ?? el.backgroundColor,
        strokeColor: patch.strokeColor ?? el.strokeColor,
        roundness: null,
        roughness: 0,
        points: nextPoints as unknown as typeof el.points,
        customData: {
          ...(el.customData ?? {}),
          kind: 'block-arrow',
          ...nextParams,
          lastWidth: el.width,
          lastHeight: el.height,
        },
      }
    })
  }

  const variants: BlockArrowVariant[] = ['straight', 'double', 'curved']

  return (
    <div className='relative' onPointerDown={(event) => event.stopPropagation()}>
      <Button
        variant='ghost'
        size='sm'
        title={t('canvas:popbar.blockArrow')}
        onClick={() => setOpen((v) => !v)}
      >
        <SlidersHorizontal size={15} />
        {t('canvas:popbar.blockArrow')}
      </Button>

      {open && (
        <div
          role='group'
          aria-label={t('canvas:popbar.blockArrow')}
          className='absolute left-0 top-full z-50 mt-1 w-64 space-y-2.5 rounded-lg border border-primary/15 bg-background p-3 text-xs shadow-lg'
        >
          <div className='flex gap-1'>
            {variants.map((variant) => (
              <button
                key={variant}
                type='button'
                onClick={() => updateBlockArrows({ variant })}
                className={cn(
                  'flex-1 rounded-md border px-2 py-1 font-medium transition-colors',
                  currentParams.variant === variant
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-primary/15 bg-background hover:bg-accent'
                )}
              >
                {t(`canvas:tool.blockArrow_${variant}`)}
              </button>
            ))}
          </div>

          <div className='space-y-1'>
            <span className='text-muted-foreground'>{t('canvas:popbar.fillColor')}</span>
            <div className='flex items-center gap-1.5'>
              {FILL_PRESETS.map((color) => (
                <button
                  key={color}
                  type='button'
                  aria-label={`fill ${color}`}
                  onClick={() => updateBlockArrows({ backgroundColor: color })}
                  className='h-5 w-5 rounded-full border border-black/20'
                  style={{ backgroundColor: color }}
                />
              ))}
              <input
                type='color'
                value={first.backgroundColor.startsWith('#') ? first.backgroundColor : '#3b82f6'}
                onChange={(e) => updateBlockArrows({ backgroundColor: e.target.value })}
                className='h-5 w-6 cursor-pointer rounded border border-primary/20 bg-transparent p-0'
              />
            </div>
          </div>

          <div className='space-y-1'>
            <span className='text-muted-foreground'>{t('canvas:popbar.strokeColor')}</span>
            <div className='flex items-center gap-1.5'>
              {STROKE_PRESETS.map((color) => (
                <button
                  key={color}
                  type='button'
                  aria-label={`stroke ${color}`}
                  onClick={() => updateBlockArrows({ strokeColor: color })}
                  className='h-5 w-5 rounded-full border border-black/20'
                  style={{
                    backgroundColor: color === 'transparent' ? '#ffffff' : color,
                    backgroundImage:
                      color === 'transparent'
                        ? 'linear-gradient(45deg, transparent 45%, #ef4444 45%, #ef4444 55%, transparent 55%)'
                        : undefined,
                  }}
                />
              ))}
            </div>
          </div>

          <label className='block space-y-1'>
            <div className='flex justify-between'>
              <span className='text-muted-foreground'>{t('canvas:popbar.headLength')}</span>
              <span>{Math.round(currentParams.headLengthPx)}px</span>
            </div>
            <input
              type='range'
              min={20}
              max={160}
              step={2}
              value={currentParams.headLengthPx}
              onChange={(e) => updateBlockArrows({ headLengthPx: Number(e.target.value) })}
              className='w-full accent-primary'
            />
          </label>

          <label className='block space-y-1'>
            <div className='flex justify-between'>
              <span className='text-muted-foreground'>{t('canvas:popbar.shaftWidth')}</span>
              <span>{Math.round(currentParams.shaftRatio * 100)}%</span>
            </div>
            <input
              type='range'
              min={0.2}
              max={0.8}
              step={0.02}
              value={currentParams.shaftRatio}
              onChange={(e) => updateBlockArrows({ shaftRatio: Number(e.target.value) })}
              className='w-full accent-primary'
            />
          </label>

          {currentParams.variant === 'curved' && (
            <label className='block space-y-1'>
              <div className='flex justify-between'>
                <span className='text-muted-foreground'>{t('canvas:popbar.curvature')}</span>
                <span>{currentParams.curvature.toFixed(2)}</span>
              </div>
              <input
                type='range'
                min={-0.8}
                max={0.8}
                step={0.05}
                value={currentParams.curvature}
                onChange={(e) => updateBlockArrows({ curvature: Number(e.target.value) })}
                className='w-full accent-primary'
              />
            </label>
          )}
        </div>
      )}
    </div>
  )
}

export default CanvasBlockArrowControls
