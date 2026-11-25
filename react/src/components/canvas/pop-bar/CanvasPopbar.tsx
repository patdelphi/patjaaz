import { Button } from '@/components/ui/button'
import { Hotkey } from '@/components/ui/hotkey'
import { useCanvas } from '@/contexts/canvas'
import { eventBus, TCanvasAddImagesToChatEvent } from '@/lib/event'
import { useKeyPress } from 'ahooks'
import { memo } from 'react'
import { useTranslation } from 'react-i18next'

type CanvasPopbarProps = {
  selectedImages: TCanvasAddImagesToChatEvent
  selectedTexts?: string[]
}

const CanvasPopbar = ({ selectedImages, selectedTexts = [] }: CanvasPopbarProps) => {
  const { t } = useTranslation()
  const { excalidrawAPI } = useCanvas()

  const handleAddToChat = () => {
    if (selectedImages.length > 0) {
      eventBus.emit('Canvas::AddImagesToChat', selectedImages)
    }
    if (selectedTexts.length > 0) {
      eventBus.emit('Canvas::AddTextToChat', selectedTexts)
    }
    excalidrawAPI?.updateScene({
      appState: { selectedElementIds: {} },
    })
  }

  useKeyPress(['meta.enter', 'ctrl.enter'], handleAddToChat)

  return (
    <Button variant="ghost" size="sm" onClick={handleAddToChat}>
      {t('canvas:popbar.addToChat')} <Hotkey keys={['⌘', '↩︎']} />
    </Button>
  )
}

export default memo(CanvasPopbar)
