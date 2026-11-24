/** 程序说明：监听 Excalidraw 选中元素变更并计算悬浮操作条的位置与可见工具组。 */
import { useCanvas } from '@/contexts/canvas'
import { useExcalidrawChange } from '@/hooks/use-excalidraw-change'
import { isBlockArrowElement } from '@/lib/blockArrow'
import { normalizeCanvasImageForChat } from '@/lib/canvasChatImage'
import { TCanvasAddImagesToChatEvent } from '@/lib/event'
import {
  ExcalidrawElement,
  ExcalidrawImageElement,
  OrderedExcalidrawElement,
} from '@excalidraw/excalidraw/element/types'
import { AnimatePresence } from 'motion/react'
import { useRef, useState } from 'react'
import CanvasPopbarContainer from './CanvasPopbarContainer'
import { isStrokeWidthEditable } from './CanvasStrokeWidth'

const CanvasPopbarWrapper = () => {
  const { excalidrawAPI } = useCanvas()

  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [showAddToChat, setShowAddToChat] = useState(false)
  const [showMagicGenerate, setShowMagicGenerate] = useState(false)
  const [showTextBackground, setShowTextBackground] = useState(false)
  const [showStrokeWidth, setShowStrokeWidth] = useState(false)
  const [showBlockArrow, setShowBlockArrow] = useState(false)

  const selectedImagesRef = useRef<TCanvasAddImagesToChatEvent>([])
  const selectedElementsRef = useRef<OrderedExcalidrawElement[]>([])
  const selectedTextElementsRef = useRef<OrderedExcalidrawElement[]>([])
  const selectedStrokeElementsRef = useRef<ExcalidrawElement[]>([])
  const selectedBlockArrowsRef = useRef<ExcalidrawElement[]>([])

  // 使用 useExcalidrawChange 在挂载期间单次订阅并在卸载时注销，避免每次重渲染累积监听
  useExcalidrawChange(excalidrawAPI, (elements, appState, files) => {
    const selectedIds = appState.selectedElementIds
    if (Object.keys(selectedIds).length === 0) {
      setPos(null)
      setShowAddToChat(false)
      setShowMagicGenerate(false)
      setShowTextBackground(false)
      setShowStrokeWidth(false)
      setShowBlockArrow(false)
      return
    }

    const selectedImages = elements.filter(
      (element) => element.type === 'image' && selectedIds[element.id]
    ) as ExcalidrawImageElement[]
    const selectedTextElements = elements.filter(
      (element) => element.type === 'text' && selectedIds[element.id]
    ) as OrderedExcalidrawElement[]
    const selectedStrokeElements = elements.filter(
      (element) => selectedIds[element.id] && isStrokeWidthEditable(element)
    )
    const selectedBlockArrows = elements.filter(
      (element) => selectedIds[element.id] && isBlockArrowElement(element)
    )

    selectedElementsRef.current = elements.filter(
      (element) => selectedIds[element.id] && element.index !== null
    ) as OrderedExcalidrawElement[]
    selectedTextElementsRef.current = selectedTextElements
    selectedStrokeElementsRef.current = selectedStrokeElements
    selectedBlockArrowsRef.current = selectedBlockArrows

    const hasText = selectedTextElements.length > 0
    const hasStroke = selectedStrokeElements.length > 0
    const hasBlockArrow = selectedBlockArrows.length > 0
    setShowTextBackground(hasText)
    setShowStrokeWidth(hasStroke)
    setShowBlockArrow(hasBlockArrow)

    const hasSelectedImages = selectedImages.length > 0
    const selectedCount = Object.keys(selectedIds).length
    const hasMagic = selectedCount >= 2
    setShowMagicGenerate(hasMagic)

    if (!hasSelectedImages && !hasMagic && !hasText && !hasStroke && !hasBlockArrow) {
      setPos(null)
      return
    }

    selectedImagesRef.current = selectedImages.flatMap((image) => {
      const file = image.fileId ? files[image.fileId] : undefined
      const attachment = normalizeCanvasImageForChat(image, file)
      return attachment ? [attachment] : []
    })
    setShowAddToChat(selectedImagesRef.current.length > 0)

    let centerX: number
    let bottomY: number

    if (hasSelectedImages) {
      centerX =
        selectedImages.reduce((acc, image) => acc + image.x + image.width / 2, 0) /
        selectedImages.length

      bottomY = selectedImages.reduce(
        (acc, image) => Math.max(acc, image.y + image.height),
        Number.NEGATIVE_INFINITY
      )
    } else {
      const activeSelected = elements.filter((element) => selectedIds[element.id])

      centerX =
        activeSelected.reduce(
          (acc, element) => acc + element.x + (element.width || 0) / 2,
          0
        ) / activeSelected.length

      bottomY = activeSelected.reduce(
        (acc, element) => Math.max(acc, element.y + (element.height || 0)),
        Number.NEGATIVE_INFINITY
      )
    }

    const scrollX = appState.scrollX
    const scrollY = appState.scrollY
    const zoom = appState.zoom.value
    const offsetX = (scrollX + centerX) * zoom
    const offsetY = (scrollY + bottomY) * zoom
    setPos({ x: offsetX, y: offsetY })
  })

  return (
    <div className='absolute left-0 bottom-0 w-full h-full z-20 pointer-events-none'>
      <AnimatePresence>
        {pos &&
          (showAddToChat ||
            showMagicGenerate ||
            showTextBackground ||
            showStrokeWidth ||
            showBlockArrow) && (
            <CanvasPopbarContainer
              pos={pos}
              selectedImages={selectedImagesRef.current}
              selectedElements={selectedElementsRef.current}
              selectedTextElements={selectedTextElementsRef.current}
              selectedStrokeElements={selectedStrokeElementsRef.current}
              selectedBlockArrows={selectedBlockArrowsRef.current}
              showAddToChat={showAddToChat}
              showMagicGenerate={showMagicGenerate}
              showTextBackground={showTextBackground}
              showStrokeWidth={showStrokeWidth}
              showBlockArrow={showBlockArrow}
            />
          )}
      </AnimatePresence>
    </div>
  )
}

export default CanvasPopbarWrapper
