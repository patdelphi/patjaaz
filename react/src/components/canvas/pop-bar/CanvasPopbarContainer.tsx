/** 程序说明：选中元素悬浮操作栏容器，按当前选中类型组合显示文字底色、线宽与块箭头操作。 */
import { TCanvasAddImagesToChatEvent } from '@/lib/event'
import { motion } from 'motion/react'
import { memo } from 'react'
import type { ExcalidrawElement, OrderedExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import CanvasBlockArrowControls from './CanvasBlockArrowControls'
import CanvasPopbar from './CanvasPopbar'
import CanvasStrokeWidth from './CanvasStrokeWidth'
import CanvasTextBackground from './CanvasTextBackground'

type CanvasPopbarContainerProps = {
  pos: { x: number; y: number }
  selectedImages: TCanvasAddImagesToChatEvent
  selectedTexts: string[]
  selectedTextElements: OrderedExcalidrawElement[]
  selectedStrokeElements: ExcalidrawElement[]
  selectedBlockArrows: ExcalidrawElement[]
  showAddToChat: boolean
  showTextBackground: boolean
  showStrokeWidth: boolean
  showBlockArrow: boolean
}

const CanvasPopbarContainer = ({
  pos,
  selectedImages,
  selectedTexts,
  selectedTextElements,
  selectedStrokeElements,
  selectedBlockArrows,
  showAddToChat,
  showTextBackground,
  showStrokeWidth,
  showBlockArrow,
}: CanvasPopbarContainerProps) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: -3 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -3 }}
      transition={{ duration: 0.2, ease: 'easeInOut' }}
      className='absolute z-20 flex items-center gap-1 -translate-x-1/2 '
      style={{
        left: `${pos.x}px`,
        top: `${pos.y + 5}px`,
      }}
    >
      <div className='flex items-center gap-1 bg-primary-foreground/75 backdrop-blur-lg rounded-lg p-1 shadow-[0_5px_10px_rgba(0,0,0,0.08)] border border-primary/10 pointer-events-auto'>
        {showTextBackground && (
          <CanvasTextBackground selectedTextElements={selectedTextElements} />
        )}
        {showStrokeWidth && (
          <CanvasStrokeWidth selectedStrokeElements={selectedStrokeElements} />
        )}
        {showBlockArrow && (
          <CanvasBlockArrowControls selectedBlockArrows={selectedBlockArrows} />
        )}
        {showAddToChat && (
          <CanvasPopbar
            selectedImages={selectedImages}
            selectedTexts={selectedTexts}
          />
        )}
      </div>
    </motion.div>
  )
}

export default memo(CanvasPopbarContainer)
