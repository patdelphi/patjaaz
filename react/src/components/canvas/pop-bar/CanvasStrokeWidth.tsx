/** 程序说明：为当前选中的线条、箭头或形状提供扩展线宽预设（1–24px）与自定义输入。 */
import { Button } from '@/components/ui/button'
import { useCanvas } from '@/contexts/canvas'
import { mutateSceneElements } from '@/lib/excalidrawMutation'
import { cn } from '@/lib/utils'
import type { ExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export const STROKE_WIDTH_PRESETS = [1, 2, 4, 6, 8, 12, 16, 24] as const

const STROKE_EDITABLE_TYPES = new Set([
  'arrow',
  'line',
  'rectangle',
  'diamond',
  'ellipse',
  'freedraw',
])

export function isStrokeWidthEditable(element: ExcalidrawElement): boolean {
  return !element.isDeleted && STROKE_EDITABLE_TYPES.has(element.type)
}

type CanvasStrokeWidthProps = {
  selectedStrokeElements: ExcalidrawElement[]
}

const CanvasStrokeWidth = ({ selectedStrokeElements }: CanvasStrokeWidthProps) => {
  const { t } = useTranslation()
  const { excalidrawAPI } = useCanvas()
  const [open, setOpen] = useState(false)

  const currentWidth = selectedStrokeElements[0]?.strokeWidth ?? 2
  const [customInput, setCustomInput] = useState(String(currentWidth))

  const applyStrokeWidth = (rawWidth: number) => {
    if (!excalidrawAPI || !Number.isFinite(rawWidth)) return
    const width = Math.min(64, Math.max(1, Math.round(rawWidth)))
    const selectedIds = new Set(selectedStrokeElements.map((el) => el.id))

    mutateSceneElements(
      excalidrawAPI,
      (el) => (selectedIds.has(el.id) ? { ...el, strokeWidth: width } : el),
      {
        appState: {
          currentItemStrokeWidth: width,
        },
      }
    )
    setCustomInput(String(width))
  }

  return (
    <div className='relative' onPointerDown={(event) => event.stopPropagation()}>
      <Button
        variant='ghost'
        size='sm'
        title={t('canvas:popbar.strokeWidth')}
        onClick={() => {
          setCustomInput(String(currentWidth))
          setOpen((v) => !v)
        }}
      >
        <span className='inline-block w-3.5 rounded-full bg-current' style={{ height: Math.min(6, Math.max(1, currentWidth / 2)) }} />
        <span>{currentWidth}px</span>
      </Button>

      {open && (
        <div
          role='group'
          aria-label={t('canvas:popbar.strokeWidth')}
          className='absolute left-0 top-full z-50 mt-1 w-56 rounded-lg border border-primary/15 bg-background p-2 shadow-lg'
        >
          <div className='grid grid-cols-4 gap-1'>
            {STROKE_WIDTH_PRESETS.map((preset) => (
              <button
                key={preset}
                type='button'
                onClick={() => {
                  applyStrokeWidth(preset)
                  setOpen(false)
                }}
                className={cn(
                  'rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:bg-accent',
                  currentWidth === preset
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-primary/15 bg-background'
                )}
              >
                {preset}
              </button>
            ))}
          </div>
          <form
            className='mt-2 flex items-center gap-1.5'
            onSubmit={(event) => {
              event.preventDefault()
              applyStrokeWidth(Number(customInput))
              setOpen(false)
            }}
          >
            <input
              type='number'
              min={1}
              max={64}
              value={customInput}
              aria-label={t('canvas:popbar.customStrokeWidth')}
              onChange={(event) => setCustomInput(event.target.value)}
              className='h-7 w-full rounded-md border border-primary/20 bg-background px-2 text-xs'
            />
            <Button type='submit' size='sm' variant='secondary' className='h-7 px-2 text-xs'>
              OK
            </Button>
          </form>
        </div>
      )}
    </div>
  )
}

export default CanvasStrokeWidth
