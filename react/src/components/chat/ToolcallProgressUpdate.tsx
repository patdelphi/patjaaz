import { eventBus } from '@/lib/event'

import { TEvents } from '@/lib/event'
import { useEffect } from 'react'

import Spinner from '@/components/ui/Spinner'
import { useRef, useState } from 'react'
import {
  getTaskProgressLabel,
  isTaskStatusTerminal,
  TaskStatusSnapshot,
} from '@/lib/chatTaskProgress'

export default function ToolcallProgressUpdate({
  sessionId,
  onTaskFinished,
}: {
  sessionId: string
  onTaskFinished: (status: TaskStatusSnapshot) => void
}) {
  const [progress, setProgress] = useState('')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const startedAtRef = useRef(Date.now())
  const observedActiveRef = useRef(false)
  const finishedRef = useRef(false)

  useEffect(() => {
    let mounted = true
    startedAtRef.current = Date.now()
    observedActiveRef.current = false
    finishedRef.current = false
    setProgress('')
    setElapsedSeconds(0)

    const syncTaskStatus = async () => {
      try {
        const response = await fetch(
          `/api/chat/status/${encodeURIComponent(sessionId)}`
        )
        if (!response.ok) return
        const status: TaskStatusSnapshot = await response.json()
        if (!mounted) return

        if (!status.active) {
          const terminal = isTaskStatusTerminal(status)
          const lostAfterRestart = !status.known && observedActiveRef.current
          if ((terminal || lostAfterRestart) && !finishedRef.current) {
            finishedRef.current = true
            onTaskFinished(
              lostAfterRestart
                ? { ...status, known: true, active: false, terminal_state: 'unknown' }
                : status
            )
          }
          return
        }

        observedActiveRef.current = true

        if (typeof status.status === 'string') {
          setProgress(status.status)
        }
        if (typeof status.started_at === 'number') {
          startedAtRef.current = status.started_at * 1000
          setElapsedSeconds(
            Math.max(0, Math.floor((Date.now() - startedAtRef.current) / 1000))
          )
        }
      } catch (error) {
        console.warn('Could not sync chat task status', error)
      }
    }

    void syncTaskStatus()
    const pollTimer = window.setInterval(() => {
      void syncTaskStatus()
    }, 5000)
    const elapsedTimer = window.setInterval(() => {
      setElapsedSeconds(
        Math.max(0, Math.floor((Date.now() - startedAtRef.current) / 1000))
      )
    }, 1000)
    return () => {
      mounted = false
      window.clearInterval(pollTimer)
      window.clearInterval(elapsedTimer)
    }
  }, [sessionId, onTaskFinished])

  useEffect(() => {
    const handleToolCallProgress = (
      data: TEvents['Socket::Session::ToolCallProgress']
    ) => {
      if (data.session_id === sessionId) {
        setProgress(data.update)
      }
    }

    eventBus.on('Socket::Session::ToolCallProgress', handleToolCallProgress)
    return () => {
      eventBus.off('Socket::Session::ToolCallProgress', handleToolCallProgress)
    }
  }, [sessionId])
  if (!sessionId) return null
  return (
    <div
      aria-live="polite"
      className="flex w-fit max-w-full items-center gap-2 rounded-md border bg-muted px-3 py-2 text-sm text-foreground"
    >
      <Spinner size={4} />
      <span>{getTaskProgressLabel(progress, elapsedSeconds)}</span>
    </div>
  )
}
