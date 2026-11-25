/** 程序说明：画布顶部生成进度浮层卡片（C4），使用原生 <progress> 展示当前 ComfyUI 工作流节点进度与耗时。 */
import { eventBus, TEvents } from '@/lib/event'
import { Loader2 } from 'lucide-react'
import React, { useEffect, useState } from 'react'

const GENERATION_TOOL_PREFIXES = (name: string) =>
  name !== 'write_plan' &&
  !name.startsWith('transfer_to_') &&
  name !== 'finish'

function extractPercent(text: string): number | undefined {
  const match = text.match(/(\d{1,3})\s*%/)
  if (!match) return undefined
  const num = Number(match[1])
  return Number.isFinite(num) ? Math.min(100, Math.max(0, num)) : undefined
}

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export const CanvasGenerationOverlay: React.FC<{ canvasId: string }> = ({
  canvasId,
}) => {
  const [activeToolName, setActiveToolName] = useState<string | null>(null)
  const [statusText, setStatusText] = useState<string>('')
  const [percent, setPercent] = useState<number | undefined>(undefined)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [elapsedSec, setElapsedSec] = useState<number>(0)

  useEffect(() => {
    const onToolCall = (ev: TEvents['Socket::Session::ToolCall']) => {
      const name = String(ev.name || '')
      if (!GENERATION_TOOL_PREFIXES(name)) return
      setActiveToolName(name)
      setStatusText('Submitting to ComfyUI...')
      setPercent(undefined)
      setStartedAt(Date.now())
      setElapsedSec(0)
    }

    const onProgress = (ev: TEvents['Socket::Session::ToolCallProgress']) => {
      const update = String(ev.update || '').trim()
      if (!update) return
      setStatusText(update)
      const pct = extractPercent(update)
      if (pct !== undefined) {
        setPercent(pct)
      }
      setStartedAt((prev) => prev ?? Date.now())
      setActiveToolName((prev) => prev ?? 'ComfyUI')
    }

    const clearIfThisCanvas = (evCanvasId?: string) => {
      if (evCanvasId && evCanvasId !== canvasId) return
      setActiveToolName(null)
      setStatusText('')
      setPercent(undefined)
      setStartedAt(null)
    }

    const onImage = (ev: TEvents['Socket::Session::ImageGenerated']) =>
      clearIfThisCanvas(ev.canvas_id)
    const onVideo = (ev: TEvents['Socket::Session::VideoGenerated']) =>
      clearIfThisCanvas(ev.canvas_id)
    const onAudio = (ev: TEvents['Socket::Session::AudioGenerated']) =>
      clearIfThisCanvas(ev.canvas_id)
    const onDone = () => clearIfThisCanvas()
    const onError = () => clearIfThisCanvas()
    const onCancelled = () => clearIfThisCanvas()

    eventBus.on('Socket::Session::ToolCall', onToolCall)
    eventBus.on('Socket::Session::ToolCallProgress', onProgress)
    eventBus.on('Socket::Session::ImageGenerated', onImage)
    eventBus.on('Socket::Session::VideoGenerated', onVideo)
    eventBus.on('Socket::Session::AudioGenerated', onAudio)
    eventBus.on('Socket::Session::Done', onDone)
    eventBus.on('Socket::Session::Error', onError)
    eventBus.on('Socket::Session::ToolCallCancelled', onCancelled)

    return () => {
      eventBus.off('Socket::Session::ToolCall', onToolCall)
      eventBus.off('Socket::Session::ToolCallProgress', onProgress)
      eventBus.off('Socket::Session::ImageGenerated', onImage)
      eventBus.off('Socket::Session::VideoGenerated', onVideo)
      eventBus.off('Socket::Session::AudioGenerated', onAudio)
      eventBus.off('Socket::Session::Done', onDone)
      eventBus.off('Socket::Session::Error', onError)
      eventBus.off('Socket::Session::ToolCallCancelled', onCancelled)
    }
  }, [canvasId])

  useEffect(() => {
    if (!startedAt) return
    const timer = setInterval(() => {
      setElapsedSec(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)))
    }, 1000)
    return () => clearInterval(timer)
  }, [startedAt])

  if (!activeToolName) return null

  return (
    <div className="pointer-events-none absolute top-3 left-1/2 z-20 -translate-x-1/2">
      <div className="flex min-w-64 max-w-md flex-col gap-1.5 rounded-xl border border-primary/15 bg-background/85 px-3.5 py-2.5 shadow-lg backdrop-blur-md">
        <div className="flex items-center justify-between gap-3 text-xs">
          <span className="flex items-center gap-1.5 font-medium text-foreground truncate">
            <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" aria-hidden="true" />
            <span className="truncate">{statusText || activeToolName}</span>
          </span>
          <span className="shrink-0 tabular-nums text-muted-foreground">
            {percent !== undefined ? `${percent}% · ` : ''}
            {formatElapsed(elapsedSec)}
          </span>
        </div>
        {/* 遵循 accessibility 规范使用原生 <progress> 表达进行中任务状态 */}
        <progress
          aria-label="Canvas media generation progress"
          max={100}
          value={percent}
          className="h-1.5 w-full overflow-hidden rounded-full accent-primary"
        />
      </div>
    </div>
  )
}

export default CanvasGenerationOverlay
