import { useCanvas } from '@/contexts/canvas'
import { TCanvasAddImagesToChatEvent } from '@/lib/event'
import { normalizeCanvasImageForChat } from '@/lib/canvasChatImage'
import {
  ExcalidrawImageElement,
  OrderedExcalidrawElement,
} from '@excalidraw/excalidraw/element/types'
import { AnimatePresence } from 'motion/react'
import { useRef, useState } from 'react'
import CanvasPopbarContainer from './CanvasPopbarContainer'

const CanvasPopbarWrapper = () => {
  const { excalidrawAPI } = useCanvas()

  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [showAddToChat, setShowAddToChat] = useState(false)
  const [showMagicGenerate, setShowMagicGenerate] = useState(false)
  const [showTextBackground, setShowTextBackground] = useState(false)

  const selectedImagesRef = useRef<TCanvasAddImagesToChatEvent>([])
  const selectedElementsRef = useRef<OrderedExcalidrawElement[]>([])
  const selectedTextElementsRef = useRef<OrderedExcalidrawElement[]>([])

  excalidrawAPI?.onChange((elements, appState, files) => {
    const selectedIds = appState.selectedElementIds
    if (Object.keys(selectedIds).length === 0) {
      setPos(null)
      setShowAddToChat(false)
      setShowMagicGenerate(false)
      setShowTextBackground(false)
      return
    }

    const selectedImages = elements.filter(
      (element) => element.type === 'image' && selectedIds[element.id]
    ) as ExcalidrawImageElement[]
    const selectedTextElements = elements.filter(
      (element) => element.type === 'text' && selectedIds[element.id]
    ) as OrderedExcalidrawElement[]
    selectedElementsRef.current = elements.filter(
      (element) => selectedIds[element.id] && element.index !== null
    ) as OrderedExcalidrawElement[]
    selectedTextElementsRef.current = selectedTextElements
    setShowTextBackground(selectedTextElements.length > 0)

    // 判断是否显示添加到对话按钮：选中图片元素
    const hasSelectedImages = selectedImages.length > 0

    // 判断是否显示魔法生成按钮：选中2个以上元素（包含所有类型）
    const selectedCount = Object.keys(selectedIds).length
    setShowMagicGenerate(selectedCount >= 2)

    // 如果既没有选中图片，也没有满足魔法生成条件，隐藏弹窗
    if (!hasSelectedImages && selectedCount < 2 && selectedTextElements.length === 0) {
      setPos(null)
      return
    }

    // 处理选中的图片数据
    selectedImagesRef.current = selectedImages.flatMap((image) => {
      const file = image.fileId ? files[image.fileId] : undefined
      const attachment = normalizeCanvasImageForChat(image, file)
      return attachment ? [attachment] : []
    })
    setShowAddToChat(selectedImagesRef.current.length > 0)

    // 处理选中的元素数据
    selectedElementsRef.current = elements.filter(
      (element) => selectedIds[element.id] && element.index !== null
    ) as OrderedExcalidrawElement[]

    // 计算位置：如果有图片，基于图片；否则基于所有选中的元素
    let centerX: number
    let bottomY: number

    if (hasSelectedImages) {
      // 基于选中的图片计算位置
      centerX =
        selectedImages.reduce((acc, image) => acc + image.x + image.width / 2, 0) /
        selectedImages.length

      bottomY = selectedImages.reduce(
        (acc, image) => Math.max(acc, image.y + image.height),
        Number.NEGATIVE_INFINITY
      )
    } else {
      // 基于所有选中的元素计算位置
      const selectedElements = elements.filter((element) => selectedIds[element.id])

      centerX =
        selectedElements.reduce(
          (acc, element) => acc + element.x + (element.width || 0) / 2,
          0
        ) / selectedElements.length

      bottomY = selectedElements.reduce(
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
    // console.log(offsetX, offsetY)
  })

  return (
    <div className='absolute left-0 bottom-0 w-full h-full z-20 pointer-events-none'>
      <AnimatePresence>
        {pos && (showAddToChat || showMagicGenerate || showTextBackground) && (
          <CanvasPopbarContainer
            pos={pos}
            selectedImages={selectedImagesRef.current}
            selectedElements={selectedElementsRef.current}
            selectedTextElements={selectedTextElementsRef.current}
            showAddToChat={showAddToChat}
            showMagicGenerate={showMagicGenerate}
            showTextBackground={showTextBackground}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

export default CanvasPopbarWrapper
