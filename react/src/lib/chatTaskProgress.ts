// 程序说明：生成聊天任务状态文字及持续时间。
export function formatElapsedTime(totalSeconds: number): string {
  const elapsed = Math.max(0, Math.floor(totalSeconds))
  const minutes = Math.floor(elapsed / 60)
  const seconds = elapsed % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export function getTaskProgressLabel(
  progress: string,
  elapsedSeconds: number
): string {
  const status = progress || 'Task is running'
  return `${status} · ${formatElapsedTime(elapsedSeconds)}`
}

export type TaskStatusSnapshot = {
  known?: boolean
  active?: boolean
  status?: string
  started_at?: number
  terminal_state?: 'completed' | 'failed' | 'cancelled' | 'unknown' | null
  error?: string
}

export function isTaskStatusTerminal(snapshot: TaskStatusSnapshot): boolean {
  return snapshot.known === true && snapshot.active === false
}
