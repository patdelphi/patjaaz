// 聊天任务等待态和 ComfyUI 进度文案回归测试。
import { describe, expect, it } from 'vitest'
import {
  formatElapsedTime,
  getTaskProgressLabel,
  isTaskStatusTerminal,
} from '../src/lib/chatTaskProgress'

describe('chat task progress labels', () => {
  it('formats elapsed time as minutes and seconds', () => {
    expect(formatElapsedTime(0)).toBe('00:00')
    expect(formatElapsedTime(65)).toBe('01:05')
  })

  it('shows a running message before ComfyUI reports progress', () => {
    expect(getTaskProgressLabel('', 12)).toBe('Task is running · 00:12')
  })

  it('shows ComfyUI node progress with elapsed time', () => {
    expect(getTaskProgressLabel('Executing KSampler 25%', 63)).toBe(
      'Executing KSampler 25% · 01:03'
    )
  })

  it('recognizes known completed tasks for reconnect recovery', () => {
    expect(isTaskStatusTerminal({ known: true, active: false })).toBe(true)
    expect(isTaskStatusTerminal({ known: false, active: false })).toBe(false)
    expect(isTaskStatusTerminal({ known: true, active: true })).toBe(false)
  })
})
