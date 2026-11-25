import { Button } from '@/components/ui/button'
import { useCanvas } from '@/contexts/canvas'
import { findCanvasElementByMediaUrl } from '@/lib/canvasMediaNormalize'
import { useTranslation } from 'react-i18next'
import { PhotoView } from 'react-photo-view'

type MessageImageProps = {
  content: {
    image_url: {
      url: string
    }
    type: 'image_url'
  }
}

const MessageImage = ({ content }: MessageImageProps) => {
  const { excalidrawAPI } = useCanvas()
  const { t } = useTranslation()

  const matched = excalidrawAPI
    ? findCanvasElementByMediaUrl(
        excalidrawAPI.getSceneElements(),
        excalidrawAPI.getFiles(),
        content.image_url.url
      )
    : null

  const handleImagePositioning = () => {
    if (!excalidrawAPI || !matched) return
    excalidrawAPI.scrollToContent(matched, { animate: true })
    excalidrawAPI.updateScene({
      appState: { selectedElementIds: { [matched.id]: true } },
    })
  }

  return (
    <div className="w-full max-w-[140px]">
      <PhotoView src={content.image_url.url}>
        <div className="relative group cursor-pointer">
          <img
            className="w-full h-auto max-h-[140px] object-cover rounded-md border border-border hover:scale-105 transition-transform duration-300"
            src={content.image_url.url}
            alt="Attached reference"
          />

          {matched && (
            <Button
              variant="secondary"
              size="sm"
              className="group-hover:opacity-100 opacity-0 absolute top-2 right-2 z-10 text-xs"
              onClick={(e) => {
                e.stopPropagation()
                handleImagePositioning()
              }}
            >
              {t('chat:messages:imagePositioning')}
            </Button>
          )}
        </div>
      </PhotoView>
    </div>
  )
}

export default MessageImage
