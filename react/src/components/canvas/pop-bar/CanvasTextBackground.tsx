/* 程序说明：为当前选中的 Excalidraw 文字元素设置可保存的底色。 */
import { Button } from '@/components/ui/button'
import { useCanvas } from '@/contexts/canvas'
import { CaptureUpdateAction } from '@excalidraw/excalidraw'
import { OrderedExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import { Paintbrush, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

const TEXT_BACKGROUND_COLORS = [
  '#FFFFFF',
  '#FFF2CC',
  '#FCE8E6',
  '#F3E8FD',
  '#E8F0FE',
  '#E6F4EA',
  '#E9ECEF',
]

type CanvasTextBackgroundProps = {
  selectedTextElements: OrderedExcalidrawElement[]
}

const CanvasTextBackground = ({ selectedTextElements }: CanvasTextBackgroundProps) => {
  const { t } = useTranslation()
  const { excalidrawAPI } = useCanvas()
  const [open, setOpen] = useState(false)

  const applyColor = (backgroundColor: string) => {
    if (!excalidrawAPI) return

    const selectedTextIds = new Set(selectedTextElements.map((element) => element.id))
    const elements = excalidrawAPI.getSceneElements().map((element) => {
      if (element.type === 'text' && selectedTextIds.has(element.id)) {
        return { ...element, backgroundColor }
      }
      return element
    })

    excalidrawAPI.updateScene({
      elements,
      captureUpdate: CaptureUpdateAction.IMMEDIATELY,
    })
  }

  return (
    <div className='relative' onPointerDown={(event) => event.stopPropagation()}>
      <Button
        variant='ghost'
        size='sm'
        title={t('canvas:popbar.textBackground')}
        onClick={() => setOpen((value) => !value)}
      >
        <Paintbrush size={16} />
        {t('canvas:popbar.textBackground')}
      </Button>
      {open && (
        <div
          role='group'
          aria-label={t('canvas:popbar.textBackground')}
          className='absolute left-0 top-full z-50 mt-1 grid grid-cols-4 gap-1 rounded-lg border border-primary/15 bg-background p-2 shadow-lg'
        >
          {TEXT_BACKGROUND_COLORS.map((color) => (
            <button
              key={color}
              type='button'
              aria-label={t('canvas:popbar.applyTextBackground') + ' ' + color}
              title={color}
              onClick={() => {
                applyColor(color)
                setOpen(false)
              }}
              className='h-7 w-7 rounded-full border border-black/15 transition-transform hover:scale-110'
              style={{ backgroundColor: color }}
            />
          ))}
          <label
            title={t('canvas:popbar.customTextBackground')}
            className='relative flex h-7 w-7 cursor-pointer items-center justify-center overflow-hidden rounded-full border border-primary/20 bg-background'
          >
            <Paintbrush size={14} />
            <input
              type='color'
              aria-label={t('canvas:popbar.customTextBackground')}
              defaultValue='#fff2cc'
              onChange={(event) => applyColor(event.target.value)}
              className='absolute inset-0 h-full w-full cursor-pointer opacity-0'
            />
          </label>
          <button
            type='button'
            aria-label={t('canvas:popbar.removeTextBackground')}
            title={t('canvas:popbar.removeTextBackground')}
            onClick={() => {
              applyColor('transparent')
              setOpen(false)
            }}
            className='flex h-7 w-7 items-center justify-center rounded-full border border-primary/20 bg-background'
          >
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  )
}

export default CanvasTextBackground
