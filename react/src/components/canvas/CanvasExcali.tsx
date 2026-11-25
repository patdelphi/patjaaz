import { applyCanvasOps, getCanvas, saveCanvas } from '@/api/canvas'
import { recomputeResizedBlockArrows } from '@/lib/blockArrow'
import { externalizeInlineCanvasImages } from '@/lib/canvasBase64Externalizer'
import {
  buildElementDigestMap,
  diffCanvasElementsToOps,
  ElementVersionDigest,
} from '@/lib/canvasIncrementalSync'
import { findNewPersistableImageIds, getPersistableImageIds } from '@/lib/canvasImagePersistence'
import {
  computeSceneVersionKey,
  isAudioUrl,
  isVideoUrl,
  normalizeCanvasElementsForScene,
  pickCanvasThumbnailUrl,
} from '@/lib/canvasMediaNormalize'
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
import { AudioElement } from './AudioElement'
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
  const wrapperRef = useRef<HTMLDivElement>(null)
  const saveErrorShownRef = useRef(false)
  const hadElementsRef = useRef<boolean>((initialData?.elements?.length ?? 0) > 0)
  const lastSelectionKeyRef = useRef<string>('')
  const lastSceneVersionKeyRef = useRef<string>(
    computeSceneVersionKey(
      (initialData?.elements ?? []) as ReadonlyArray<OrderedExcalidrawElement>
    )
  )
  const prevElementDigestRef = useRef<ElementVersionDigest>(
    buildElementDigestMap(
      (initialData?.elements ?? []) as unknown as ReadonlyArray<{
        id: string
        version?: number
        versionNonce?: number
        isDeleted?: boolean
      }>
    )
  )

  const { i18n, t } = useTranslation()

  // 仅在选中集合变化时更新左侧属性面板显隐，避免平移/缩放每帧查询 DOM
  const handleSelectionChange = (
    elements: Readonly<OrderedExcalidrawElement[]>,
    appState: AppState
  ) => {
    if (!appState) return
    const selectionKey = Object.keys(appState.selectedElementIds || {})
      .filter((k) => appState.selectedElementIds[k])
      .sort()
      .join(',')
    if (selectionKey === lastSelectionKeyRef.current) return
    lastSelectionKeyRef.current = selectionKey

    const hasEmbeddableSelected =
      selectionKey.length > 0 &&
      elements.some(
        (element) =>
          appState.selectedElementIds[element.id] && element.type === 'embeddable'
      )

    const excalidrawContainer =
      wrapperRef.current?.querySelector('.excalidraw') ?? null
    if (excalidrawContainer) {
      excalidrawContainer.classList.toggle('hide-left-panel', hasEmbeddableSelected)
    }
  }

  const persistCanvasSnapshot = useCallback(
    async (
      elements: Readonly<OrderedExcalidrawElement[]>,
      appState: AppState,
      files: BinaryFiles
    ) => {
      if (!appState) return
      if (elements.length > 0) {
        hadElementsRef.current = true
      } else if (!hadElementsRef.current) {
        // 首次挂载且原本为空时不发多余写请求；若用户将已有元素清空则正常落库
        return
      }

      // 将粘贴或拖拽进画布的 data:image/* 内联图片外置上传为 /api/file/<id>，避免撑爆 SQLite JSON
      let effectiveFiles = files
      const externalized = await externalizeInlineCanvasImages(canvasId, elements, files)
      if (externalized.updatedEntries.length > 0) {
        effectiveFiles = externalized.nextFiles
        excalidrawAPI?.addFiles(externalized.updatedEntries)
      }

      const data: CanvasData = {
        elements,
        appState: {
          ...appState,
          collaborators: undefined!,
        },
        files: effectiveFiles,
      }

      const thumbnail = pickCanvasThumbnailUrl(elements, effectiveFiles)
      const diffResult = diffCanvasElementsToOps(
        prevElementDigestRef.current,
        elements as unknown as ReadonlyArray<{
          id: string
          version?: number
          versionNonce?: number
          isDeleted?: boolean
        }>
      )

      try {
        await queueCanvasSave(canvasId, async () => {
          if (diffResult.shouldUseIncremental && externalized.updatedEntries.length === 0) {
            try {
              await applyCanvasOps(canvasId, {
                ops: diffResult.ops,
                files: effectiveFiles,
                appState: {
                  scrollX: appState.scrollX,
                  scrollY: appState.scrollY,
                  viewBackgroundColor: appState.viewBackgroundColor,
                },
                thumbnail,
              })
              prevElementDigestRef.current = diffResult.nextDigest
              return
            } catch {
              // 增量通道异常时无缝回退整包保存
            }
          }
          await saveCanvas(canvasId, { data, thumbnail })
          prevElementDigestRef.current = diffResult.nextDigest
        })
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
    handleSelectionChange(elements, appState)

    // 纯平移/缩放视野时元素版本指纹不变，直接跳过重算与保存以保证 60fps 流畅度
    const nextVersionKey = computeSceneVersionKey(elements)
    if (nextVersionKey === lastSceneVersionKeyRef.current) {
      return
    }

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

    lastSceneVersionKeyRef.current = nextVersionKey
    if (elements.length > 0) {
      hadElementsRef.current = true
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

  const focusElementIfUserIdle = useCallback(
    (target: OrderedExcalidrawElement) => {
      if (!excalidrawAPI) return
      const st = excalidrawAPI.getAppState()
      if (
        st.cursorButton === 'down' ||
        st.resizingElement ||
        st.editingTextElement ||
        st.selectionElement
      ) {
        return
      }
      excalidrawAPI.scrollToContent(target, { animate: true })
    },
    [excalidrawAPI]
  )

  const addImageToExcalidraw = useCallback(
    async (imageElement: ExcalidrawImageElement, file: BinaryFileData) => {
      if (!excalidrawAPI) return

      const currentElements = excalidrawAPI.getSceneElements()
      if (currentElements.some((el) => el.id === imageElement.id && !el.isDeleted)) {
        return
      }

      excalidrawAPI.addFiles([file])

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
      focusElementIfUserIdle(unlockedImageElement as OrderedExcalidrawElement)

      localStorage.setItem(
        'excalidraw-last-image-position',
        JSON.stringify(lastImagePosition.current)
      )
    },
    [excalidrawAPI, focusElementIfUserIdle]
  )

  const addVideoEmbed = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    async (elementData: any, videoSrc: string) => {
      if (!excalidrawAPI) return
      const existing = excalidrawAPI.getSceneElements()
      if (existing.some((el) => el.id === elementData.id && !el.isDeleted)) {
        return
      }

      // Function to create video element with given dimensions
      const createVideoElement = (finalWidth: number, finalHeight: number) => {
        const videoElements = convertToExcalidrawElements([
          {
            type: 'embeddable',
            id: elementData.id,
            x: elementData.x,
            y: elementData.y,
            width: finalWidth,
            height: finalHeight,
            link: videoSrc,
            strokeColor: '#000000',
            backgroundColor: '#09090b',
            fillStyle: 'solid',
            strokeWidth: 1,
            strokeStyle: 'solid',
            roundness: null,
            roughness: 1,
            opacity: 100,
            angle: 0,
            seed: Math.floor(Math.random() * 1_000_000),
            version: 1,
            versionNonce: Math.floor(Math.random() * 1_000_000),
            locked: false,
            isDeleted: false,
            groupIds: [],
            boundElements: [],
            updated: Date.now(),
            frameId: null,
            index: null,
            customData: {
              jaazMediaType: 'video',
              fileId: elementData.fileId || elementData.id,
            },
          },
        ])

        const currentElements = excalidrawAPI.getSceneElements()
        if (currentElements.some((el) => el.id === elementData.id && !el.isDeleted)) {
          return
        }
        const newElements = [...currentElements, ...videoElements]

        excalidrawAPI.updateScene({
          elements: newElements,
        })
        if (videoElements[0]) {
          focusElementIfUserIdle(videoElements[0] as OrderedExcalidrawElement)
        }
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

  const addAudioEmbed = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (elementData: any, audioSrc: string) => {
      if (!excalidrawAPI || !audioSrc) return
      const existing = excalidrawAPI.getSceneElements()
      if (existing.some((el) => el.id === elementData.id && !el.isDeleted)) {
        return
      }
      const finalWidth = Number(elementData?.width) > 0 ? Number(elementData.width) : 360
      const finalHeight = Number(elementData?.height) > 0 ? Number(elementData.height) : 108
      const audioElements = convertToExcalidrawElements([
        {
          type: 'embeddable',
          id: elementData.id,
          x: Number(elementData.x) || 0,
          y: Number(elementData.y) || 0,
          width: finalWidth,
          height: finalHeight,
          link: audioSrc,
          strokeColor: '#27272a',
          backgroundColor: '#18181b',
          fillStyle: 'solid',
          strokeWidth: 1,
          strokeStyle: 'solid',
          roundness: null,
          roughness: 0,
          opacity: 100,
          angle: 0,
          seed: Math.floor(Math.random() * 1_000_000),
          version: 1,
          versionNonce: Math.floor(Math.random() * 1_000_000),
          locked: false,
          isDeleted: false,
          groupIds: [],
          boundElements: [],
          updated: Date.now(),
          frameId: null,
          index: null,
          customData: {
            jaazMediaType: 'audio',
            fileId: elementData.fileId || elementData.id,
          },
        },
      ])
      const currentElements = excalidrawAPI.getSceneElements()
      if (currentElements.some((el) => el.id === elementData.id && !el.isDeleted)) {
        return
      }
      excalidrawAPI.updateScene({
        elements: [...currentElements, ...audioElements],
      })
      if (audioElements[0]) {
        focusElementIfUserIdle(audioElements[0] as OrderedExcalidrawElement)
      }
    },
    [excalidrawAPI, focusElementIfUserIdle]
  )

  const renderEmbeddable = useCallback(
    (element: NonDeleted<ExcalidrawEmbeddableElement>, _appState: AppState) => {
      const { link } = element
      const mediaKind = (element.customData as Record<string, unknown> | undefined)
        ?.jaazMediaType

      if (link && (mediaKind === 'audio' || isAudioUrl(link))) {
        return (
          <AudioElement
            src={link}
            width={element.width}
            height={element.height}
          />
        )
      }

      // Check if this is a video URL
      if (
        link &&
        (mediaKind === 'video' ||
          link.includes('.mp4') ||
          link.includes('.webm') ||
          link.includes('.ogg') ||
          link.startsWith('blob:') ||
          link.includes('video'))
      ) {
        return (
          <VideoElement
            src={link}
            width={element.width}
            height={element.height}
          />
        )
      }

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
        const savedElements = savedCanvas.data.elements || []
        const savedFiles = savedCanvas.data.files || {}

        for (const element of savedElements) {
          if (element.isDeleted || existingIds.has(element.id)) continue
          if (element.type === 'image') {
            const img = element as ExcalidrawImageElement
            if (!img.fileId) continue
            const file = savedFiles[img.fileId]
            if (file) {
              await addImageToExcalidraw(img, file)
            }
          } else {
            const anyEl = element as unknown as Record<string, unknown>
            const elType = String(anyEl.type || '')
            const rawLink = typeof anyEl.link === 'string' ? anyEl.link : ''
            const fid = typeof anyEl.fileId === 'string' ? anyEl.fileId : element.id
            const mediaUrl = rawLink || savedFiles[fid]?.dataURL || ''
            if (
              (elType === 'audio' || (elType === 'embeddable' && isAudioUrl(mediaUrl))) &&
              mediaUrl
            ) {
              addAudioEmbed(anyEl, mediaUrl)
            } else if (
              (elType === 'video' || (elType === 'embeddable' && isVideoUrl(mediaUrl))) &&
              mediaUrl
            ) {
              await addVideoEmbed(anyEl, mediaUrl)
            }
          }
        }
      } catch (error) {
        console.error('Could not sync generated canvas media', error)
      }
    },
    [addAudioEmbed, addImageToExcalidraw, addVideoEmbed, canvasId, excalidrawAPI]
  )

  const handleVideoGenerated = useCallback(
    (videoData: ISocket.SessionVideoGeneratedEvent) => {
      if (videoData.canvas_id !== canvasId) return
      void addVideoEmbed(videoData.element, videoData.video_url)
    },
    [addVideoEmbed, canvasId]
  )

  const handleAudioGenerated = useCallback(
    (audioData: ISocket.SessionAudioGeneratedEvent) => {
      if (audioData.canvas_id !== canvasId) return
      addAudioEmbed(audioData.element, audioData.audio_url)
    },
    [addAudioEmbed, canvasId]
  )

  const handleCanvasElementsUpdated = useCallback(
    (payload: ISocket.SessionCanvasElementsUpdatedEvent) => {
      if (payload.canvas_id !== canvasId || !excalidrawAPI) return
      const incoming = normalizeCanvasElementsForScene(
        (payload.elements || []) as unknown as ReadonlyArray<{
          id: string
          [key: string]: unknown
        }>
      ) as unknown as OrderedExcalidrawElement[]
      if (!incoming.length) return

      const incomingById = new Map(incoming.map((el) => [el.id, el]))
      const current = excalidrawAPI.getSceneElementsIncludingDeleted()
      const merged: OrderedExcalidrawElement[] = current.map((el) =>
        incomingById.has(el.id) ? incomingById.get(el.id)! : el
      )
      const existingIds = new Set(current.map((el) => el.id))
      for (const item of incoming) {
        if (!existingIds.has(item.id)) {
          merged.push(item)
        }
      }
      excalidrawAPI.updateScene({ elements: merged })
    },
    [canvasId, excalidrawAPI]
  )

  useEffect(() => {
    eventBus.on('Socket::Session::ImageGenerated', handleImageGenerated)
    eventBus.on('Socket::Session::VideoGenerated', handleVideoGenerated)
    eventBus.on('Socket::Session::AudioGenerated', handleAudioGenerated)
    eventBus.on('Socket::Session::CanvasElementsUpdated', handleCanvasElementsUpdated)
    eventBus.on('Canvas::SyncGeneratedImages', handleSyncGeneratedImages)
    return () => {
      eventBus.off('Socket::Session::ImageGenerated', handleImageGenerated)
      eventBus.off('Socket::Session::VideoGenerated', handleVideoGenerated)
      eventBus.off('Socket::Session::AudioGenerated', handleAudioGenerated)
      eventBus.off('Socket::Session::CanvasElementsUpdated', handleCanvasElementsUpdated)
      eventBus.off('Canvas::SyncGeneratedImages', handleSyncGeneratedImages)
    }
  }, [
    handleAudioGenerated,
    handleCanvasElementsUpdated,
    handleImageGenerated,
    handleSyncGeneratedImages,
    handleVideoGenerated,
  ])

  return (
    <div
      ref={wrapperRef}
      className={excalidrawClassName}
      style={{ width: '100%', height: '100%' }}
    >
      <Excalidraw
        theme={customTheme as Theme}
        langCode={i18n.language}
        excalidrawAPI={(api) => {
          setExcalidrawAPI(api)
        }}
        onChange={handleChange}
        initialData={() => {
          if (!initialData) return null
          const normalizedElements = normalizeCanvasElementsForScene(
            initialData.elements as unknown as ReadonlyArray<{ id: string; [key: string]: unknown }>,
            initialData.files
          ) as unknown as ExcalidrawInitialDataState['elements']
          return {
            ...initialData,
            elements: normalizedElements,
            appState: initialData.appState
              ? {
                  ...initialData.appState,
                  collaborators: undefined!,
                }
              : initialData.appState,
          }
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
