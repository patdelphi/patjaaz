/** 程序说明：画布主路由页，负责加载画布数据并在加载失败时提供可见错误提示与重试操作。 */
import { getCanvas, renameCanvas } from '@/api/canvas'
import CanvasExcali from '@/components/canvas/CanvasExcali'
import CanvasHeader from '@/components/canvas/CanvasHeader'
import CanvasMenu from '@/components/canvas/menu'
import CanvasPopbarWrapper from '@/components/canvas/pop-bar'
import ChatInterface from '@/components/chat/Chat'
import { Button } from '@/components/ui/button'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { CanvasProvider } from '@/contexts/canvas'
import { Session } from '@/types/types'
import { createFileRoute, useParams, useSearch } from '@tanstack/react-router'
import { AlertCircle, Loader2, RotateCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

export const Route = createFileRoute('/canvas/$id')({
  component: Canvas,
})

function Canvas() {
  const { id } = useParams({ from: '/canvas/$id' })
  const { t } = useTranslation()
  const [canvas, setCanvas] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [canvasName, setCanvasName] = useState('')
  const [sessionList, setSessionList] = useState<Session[]>([])
  const [reloadCount, setReloadCount] = useState(0)
  const search = useSearch({ from: '/canvas/$id' }) as {
    sessionId: string
  }
  const searchSessionId = search?.sessionId || ''

  const handleRetry = useCallback(() => {
    setReloadCount((count) => count + 1)
  }, [])

  useEffect(() => {
    let mounted = true

    const fetchCanvas = async () => {
      try {
        setIsLoading(true)
        setError(null)
        const data = await getCanvas(id)
        if (mounted) {
          setCanvas(data)
          setCanvasName(data.name)
          setSessionList(data.sessions)
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err : new Error('Failed to fetch canvas data'))
          console.error('Failed to fetch canvas data:', err)
        }
      } finally {
        if (mounted) {
          setIsLoading(false)
        }
      }
    }

    void fetchCanvas()

    return () => {
      mounted = false
    }
  }, [id, reloadCount])

  const handleNameSave = async () => {
    await renameCanvas(id, canvasName)
  }

  return (
    <CanvasProvider>
      <div className='flex flex-col w-screen h-screen'>
        <CanvasHeader
          canvasName={canvasName}
          canvasId={id}
          onNameChange={setCanvasName}
          onNameSave={handleNameSave}
        />
        <ResizablePanelGroup
          direction='horizontal'
          className='w-screen h-screen'
          autoSaveId='jaaz-chat-panel'
        >
          <ResizablePanel className='relative' defaultSize={75}>
            <div className='w-full h-full'>
              {isLoading ? (
                <div className='flex items-center justify-center h-full'>
                  <Loader2 className='w-5 h-5 animate-spin text-muted-foreground' />
                </div>
              ) : error ? (
                <div
                  role='alert'
                  className='flex h-full flex-col items-center justify-center gap-3 p-6 text-center'
                >
                  <AlertCircle className='h-8 w-8 text-destructive' />
                  <p className='text-base font-medium'>{t('canvas:messages.failedToLoad')}</p>
                  <p className='max-w-md text-sm text-muted-foreground'>{error.message}</p>
                  <Button variant='outline' size='sm' onClick={handleRetry}>
                    <RotateCw className='mr-2 h-4 w-4' />
                    {t('common:buttons.retry')}
                  </Button>
                </div>
              ) : (
                <div className='relative w-full h-full'>
                  <CanvasExcali canvasId={id} initialData={canvas?.data} />
                  <CanvasMenu />
                  <CanvasPopbarWrapper />
                </div>
              )}
            </div>
          </ResizablePanel>

          <ResizableHandle />

          <ResizablePanel defaultSize={25}>
            <div className='flex-1 flex-grow bg-accent/50 w-full'>
              <ChatInterface
                canvasId={id}
                sessionList={sessionList}
                setSessionList={setSessionList}
                sessionId={searchSessionId}
              />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </CanvasProvider>
  )
}
