import { getCanvas, saveCanvas } from '@/api/canvas'
import { recomputeResizedBlockArrows } from '@/lib/blockArrow'
import { findNewPersistableImageIds, getPersistableImageIds } from '@/lib/canvasImagePersistence'
import { queueCanvasSave } from '@/lib/canvasSaveQueue'
import { isAllowedEmbeddableUrl } from '@/lib/embeddableUrl'
import { CAPTURE_UPDATE_IMMEDIATELY } from '@/lib/excalidrawMutation'
import { useCanvas } from '@/contexts/canvas'
import useDebounce from '@/hooks/use-debounce'
import { useTheme } from '@/hooks/use-theme'
import { eventBus } from '@/lib/event'
import * as ISocket from '@/types/socket'
import { CanvasData } from '@/types/types'
import { Excalidraw, convertToExcalidrawElements } from '@excalidraw/excalidraw'
import {
  ExcalidrawImageElement,
  ExcalidrawEmbeddableElement,
  OrderedExcalidrawElement,
  Theme,
  NonDeleted,
} from '@excalidraw/excalidraw/element/types'
import '@excalidraw/excalidraw/index.css'
import {
  AppState,
  BinaryFileData,
  BinaryFiles,
  ExcalidrawInitialDataState,
} from '@excalidraw/excalidraw/types'
import { useCallback, useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { VideoElement } from './VideoElement'

import '@/assets/style/canvas.css'

type LastImagePosition = {
  x: number
  y: number
  width: number
  height: number
  col: number // col index
}

type CanvasExcaliProps = {
  canvasId: string
  initialData?: ExcalidrawInitialDataState
}

const CanvasExcali: React.FC<CanvasExcaliProps> = ({
  canvasId,
  initialData,
}) => {
  const { excalidrawAPI, setExcalidrawAPI } = useCanvas()
  const saveErrorShownRef = useRef(false)

  const { i18n, t } = useTranslation()

  // Immediate handler for UI updates (no debounce)
  const handleSelectionChange = (
    elements: Readonly<OrderedExcalidrawElement[]>,
    appState: AppState
  ) => {
    if (!appState) return

    // Check if any selected element is embeddable type
    const selectedElements = elements.filter((element) => 
      appState.selectedElementIds[element.id]
    )
    const hasEmbeddableSelected = selectedElements.some(
      (element) => element.type === 'embeddable'
    )

    // Toggle CSS class to hide/show left panel immediately
    const excalidrawContainer = document.querySelector('.excalidraw')
    if (excalidrawContainer) {
      if (hasEmbeddableSelected) {
        excalidrawContainer.classList.add('hide-left-panel')
      } else {
        excalidrawContainer.classList.remove('hide-left-panel')
      }
    }
  }

  const persistCanvasSnapshot = useCallback(
    async (
      elements: Readonly<OrderedExcalidrawElement[]>,
      appState: AppState,
      files: BinaryFiles
    ) => {
      if (elements.length === 0 || !appState) return

      const data: CanvasData = {
        elements,
        appState: {
          ...appState,
          collaborators: undefined!,
        },
        files,
      }

      let thumbnail = ''
      const latestImage = elements
        .filter((element) => element.type === 'image')
        .sort((a, b) => b.updated - a.updated)[0]
      if (latestImage?.type === 'image') {
        const file = latestImage.fileId ? files[latestImage.fileId] : undefined
        if (file?.dataURL) thumbnail = file.dataURL
      }

      try {
        await queueCanvasSave(canvasId, () =>
          saveCanvas(canvasId, { data, thumbnail })
        )
        saveErrorShownRef.current = false
      } catch (error) {
        console.error('Failed to save canvas ' + canvasId, error)
        if (!saveErrorShownRef.current) {
          toast.error(t('canvas:messages.failedToSave'), {
            description: error instanceof Error ? error.message : undefined,
          })
          saveErrorShownRef.current = true
        }
      }
    },
    [canvasId, t]
  )

  // 普通改动延迟合并保存；新增图片会在 onChange 中立即保存。
  const handleSave = useDebounce(
    (
      elements: Readonly<OrderedExcalidrawElement[]>,
      appState: AppState,
      files: BinaryFiles
    ) => {
      void persistCanvasSnapshot(elements, appState, files)
    },
    1000
  )

  const knownImageIdsRef = useRef<Set<string>>(
    new Set(
      (initialData?.elements ?? [])
        .filter(
          (element): element is ExcalidrawImageElement =>
            element.type === 'image' && !element.isDeleted
        )
        .filter((image) => Boolean(image.fileId && initialData?.files?.[image.fileId]?.dataURL))
        .map((image) => image.id)
    )
  )

  // Combined handler that calls both immediate and debounced functions
  const handleChange = (
    elements: Readonly<OrderedExcalidrawElement[]>,
    appState: AppState,
    files: BinaryFiles
  ) => {
    // Immediate UI updates
    handleSelectionChange(elements, appState)

    // 块箭头被缩放结束后按参数重算闭合多边形顶点（非拉伸中执行避免高频重绘抖动）
    if (excalidrawAPI && !appState.resizingElement) {
      const updatedBlockArrows = recomputeResizedBlockArrows(elements)
      if (updatedBlockArrows) {
        excalidrawAPI.updateScene({
          elements: updatedBlockArrows,
          captureUpdate: CAPTURE_UPDATE_IMMEDIATELY,
        })
        return
      }
    }

    const newImageIds = findNewPersistableImageIds(
      elements,
      files,
      knownImageIdsRef.current
    )
    knownImageIdsRef.current = new Set(getPersistableImageIds(elements, files))

    if (newImageIds.length > 0) {
      // 图片和对应文件都到齐后立即保存，不等待 1 秒防抖。
      handleSave.cancel()
      void persistCanvasSnapshot(elements, appState, files)
    } else {
      // 普通画布改动继续合并保存；组件卸载时由防抖钩子刷新最后一次改动。
      handleSave(elements, appState, files)
    }
  }

  const lastImagePosition = useRef<LastImagePosition | null>(
    localStorage.getItem('excalidraw-last-image-position')
      ? JSON.parse(localStorage.getItem('excalidraw-last-image-position')!)
      : null
  )
  const { theme } = useTheme()

  // 添加自定义类名以便应用我们的CSS修复
  const excalidrawClassName = `excalidraw-custom ${theme === 'dark' ? 'excalidraw-dark-fix-wm76394yjopk' : 'excalidraw-wm76394yjopk'}`
  
  // 在深色模式下使用自定义主题设置，避免使用默认的滤镜
  // 这样可以确保颜色在深色模式下正确显示
  const customTheme = theme === 'dark' ? 'light' : theme
  
  // 在组件挂载和主题变化时设置深色模式下的背景色
  useEffect(() => {
    if (excalidrawAPI && theme === 'dark') {
      // 设置深色背景，但保持light主题以避免颜色反转
      excalidrawAPI.updateScene({
        appState: {
          viewBackgroundColor: '#121212',
        }
      })
    } else if (excalidrawAPI && theme === 'light') {
      // 恢复浅色背景
      excalidrawAPI.updateScene({
        appState: {
          viewBackgroundColor: '#ffffff',
        }
      })
    }
  }, [excalidrawAPI, theme])

  const addImageToExcalidraw = useCallback(
    async (imageElement: ExcalidrawImageElement, file: BinaryFileData) => {
      if (!excalidrawAPI) return

      // 获取当前画布元素以便添加新元素
      const currentElements = excalidrawAPI.getSceneElements()

      excalidrawAPI.addFiles([file])

      console.log('👇 Adding new image element to canvas:', imageElement.id)
      console.log('👇 Image element properties:', {
        id: imageElement.id,
        type: imageElement.type,
        locked: imageElement.locked,
        groupIds: imageElement.groupIds,
        isDeleted: imageElement.isDeleted,
        x: imageElement.x,
        y: imageElement.y,
        width: imageElement.width,
        height: imageElement.height,
      })

      // Ensure image is not locked and can be manipulated
      const unlockedImageElement = {
        ...imageElement,
        locked: false,
        groupIds: [],
        isDeleted: false,
      }

      excalidrawAPI.updateScene({
        elements: [...(currentElements || []), unlockedImageElement],
      })

      localStorage.setItem(
        'excalidraw-last-image-position',
        JSON.stringify(lastImagePosition.current)
      )
    },
    [excalidrawAPI]
  )

  const addVideoEmbed = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    async (elementData: any, videoSrc: string) => {
      if (!excalidrawAPI) return

      // Function to create video element with given dimensions
      const createVideoElement = (finalWidth: number, finalHeight: number) => {
        console.log('👇 Video element properties:', {
          id: elementData.id,
          type: elementData.type,
          locked: elementData.locked,
          groupIds: elementData.groupIds,
          isDeleted: elementData.isDeleted,
          x: elementData.x,
          y: elementData.y,
          width: elementData.width,
          height: elementData.height,
        })

        const videoElements = convertToExcalidrawElements([
          {
            type: 'embeddable',
            id: elementData.id,
            x: elementData.x,
            y: elementData.y,
            width: elementData.width,
            height: elementData.height,
            link: videoSrc,
            // 添加必需的基本样式属性
            strokeColor: '#000000',
            backgroundColor: 'transparent',
            fillStyle: 'solid',
            strokeWidth: 1,
            strokeStyle: 'solid',
            roundness: null,
            roughness: 1,
            opacity: 100,
            // 添加必需的变换属性
            angle: 0,
            seed: Math.random(),
            version: 1,
            versionNonce: Math.random(),
            // 添加必需的状态属性
            locked: false,
            isDeleted: false,
            groupIds: [],
            // 添加绑定框属性
            boundElements: [],
            updated: Date.now(),
            // 添加必需的索引和帧ID属性
            frameId: null,
            index: null, // 添加缺失的index属性
            // 添加自定义数据属性
            customData: {},
          },
        ])

        console.log('👇 Converted video elements:', videoElements)

        const currentElements = excalidrawAPI.getSceneElements()
        const newElements = [...currentElements, ...videoElements]

        console.log(
          '👇 Updating scene with elements count:',
          newElements.length
        )

        excalidrawAPI.updateScene({
          elements: newElements,
        })

        console.log(
          '👇 Added video embed element:',
          videoSrc,
          `${elementData.width}x${elementData.height}`
        )
      }

      // If dimensions are provided, use them directly
      if (elementData.width && elementData.height) {
        createVideoElement(elementData.width, elementData.height)
        return
      }

      // Otherwise, try to get video's natural dimensions
      const video = document.createElement('video')
      video.crossOrigin = 'anonymous'

      video.onloadedmetadata = () => {
        const videoWidth = video.videoWidth
        const videoHeight = video.videoHeight

        if (videoWidth && videoHeight) {
          // Scale down if video is too large (max 800px width)
          const maxWidth = 800
          let finalWidth = videoWidth
          let finalHeight = videoHeight

          if (videoWidth > maxWidth) {
            const scale = maxWidth / videoWidth
            finalWidth = maxWidth
            finalHeight = videoHeight * scale
          }

          createVideoElement(finalWidth, finalHeight)
        } else {
          // Fallback to default dimensions
          createVideoElement(320, 180)
        }
      }

      video.onerror = () => {
        console.warn('Could not load video metadata, using default dimensions')
        createVideoElement(320, 180)
      }

      video.src = videoSrc
    },
    [excalidrawAPI]
  )

  const renderEmbeddable = useCallback(
    (element: NonDeleted<ExcalidrawEmbeddableElement>, appState: AppState) => {
      const { link } = element

      // Check if this is a video URL
      if (
        link &&
        (link.includes('.mp4') ||
          link.includes('.webm') ||
          link.includes('.ogg') ||
          link.startsWith('blob:') ||
          link.includes('video'))
      ) {
        // Return the VideoPlayer component
        return (
          <VideoElement
            src={link}
            width={element.width}
            height={element.height}
          />
        )
      }

      console.log('👇 Not a video URL, returning null for:', link)
      // Return null for non-video embeds to use default rendering
      return null
    },
    []
  )

  const handleImageGenerated = useCallback(
    (imageData: ISocket.SessionImageGeneratedEvent) => {
      console.log('👇 CanvasExcali received image_generated:', imageData)

      // Only handle if it's for this canvas
      if (imageData.canvas_id !== canvasId) {
        console.log('👇 Image not for this canvas, ignoring')
        return
      }

      // Check if this is actually a video generation event that got mislabeled
      if (imageData.file?.mimeType?.startsWith('video/')) {
        console.log(
          '👇 This appears to be a video, not an image. Ignoring in image handler.'
        )
        return
      }

      addImageToExcalidraw(imageData.element, imageData.file)
    },
    [addImageToExcalidraw, canvasId]
  )

  const handleSyncGeneratedImages = useCallback(
    async (event: { canvasId: string }) => {
      if (event.canvasId !== canvasId || !excalidrawAPI) return

      try {
        const savedCanvas = await getCanvas(canvasId)
        const existingIds = new Set(
          excalidrawAPI.getSceneElements().map((element) => element.id)
        )
        const missingImages = savedCanvas.data.elements.filter(
          (element) =>
            element.type === 'image' &&
            !element.isDeleted &&
            !existingIds.has(element.id)
        ) as ExcalidrawImageElement[]

        for (const image of missingImages) {
          // 已保存的画布图像可能没有关联文件，跳过无法恢复的元素。
          if (!image.fileId) continue
          const file = savedCanvas.data.files[image.fileId]
          if (file) {
            await addImageToExcalidraw(image, file)
          }
        }
      } catch (error) {
        console.error('Could not sync generated canvas images', error)
      }
    },
    [addImageToExcalidraw, canvasId, excalidrawAPI]
  )

  const handleVideoGenerated = useCallback(
    (videoData: ISocket.SessionVideoGeneratedEvent) => {
      console.log('👇 CanvasExcali received video_generated:', videoData)

      // Only handle if it's for this canvas
      if (videoData.canvas_id !== canvasId) {
        console.log('👇 Video not for this canvas, ignoring')
        return
      }

      // Create video embed element using the video URL
      addVideoEmbed(videoData.element, videoData.video_url)
    },
    [addVideoEmbed, canvasId]
  )

  useEffect(() => {
    eventBus.on('Socket::Session::ImageGenerated', handleImageGenerated)
    eventBus.on('Socket::Session::VideoGenerated', handleVideoGenerated)
    eventBus.on('Canvas::SyncGeneratedImages', handleSyncGeneratedImages)
    return () => {
      eventBus.off('Socket::Session::ImageGenerated', handleImageGenerated)
      eventBus.off('Socket::Session::VideoGenerated', handleVideoGenerated)
      eventBus.off('Canvas::SyncGeneratedImages', handleSyncGeneratedImages)
    }
  }, [handleImageGenerated, handleSyncGeneratedImages, handleVideoGenerated])

  return (
    <div className={excalidrawClassName} style={{ width: '100%', height: '100%' }}>
      <Excalidraw
        theme={customTheme as Theme}
        langCode={i18n.language}
        excalidrawAPI={(api) => {
          setExcalidrawAPI(api)
        }}
        onChange={handleChange}
        initialData={() => {
          const data = initialData
          console.log('👇initialData', data)
          if (data?.appState) {
            data.appState = {
              ...data.appState,
              collaborators: undefined!,
            }
          }
          return data || null
        }}
        renderEmbeddable={renderEmbeddable}
        // 仅允许同源 /api/file/ 资源作为画布内嵌媒体，禁止任意外部网页。
        validateEmbeddable={(url: string) => {
          return isAllowedEmbeddableUrl(url, window.location.origin)
        }}
        // 通过原生 UIOptions 关闭与 Jaaz 自定义菜单重复的系统动作项，减少脆弱 CSS 隐藏规则
        UIOptions={{
          canvasActions: {
            changeViewBackgroundColor: false,
            clearCanvas: false,
            export: false,
            loadScene: false,
            saveToActiveFile: false,
            toggleTheme: false,
            saveAsImage: false,
          },
          tools: {
            image: true,
          },
        }}
        // Ensure interactive mode is enabled
        viewModeEnabled={false}
        zenModeEnabled={false}
        // Allow element manipulation
        onPointerUpdate={(payload) => {
          // Minimal logging - only log significant pointer events
          if (payload.button === 'down' && Math.random() < 0.05) {
            // console.log('👇 Pointer down on:', payload.pointer.x, payload.pointer.y)
          }
        }}
      />
    </div>
  )
}

export { CanvasExcali }
export default CanvasExcali
