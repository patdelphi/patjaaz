// 程序说明：验证阶段 P2~P4 前端原生 <dialog> 无障碍契约、视口外视频懒加载与自动暂停及画布实时同步事件接线。
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const repoRoot = path.resolve(__dirname, '..', '..')

describe('stage P2~P4 frontend Web standards & wiring checks', () => {
  it('uses native <dialog> with showModal(), level-1 heading, returnValue reset, and overscroll containment', () => {
    const css = fs.readFileSync(
      path.join(repoRoot, 'react/src/assets/style/canvas.css'),
      'utf8'
    )
    expect(css).toContain('dialog:modal')
    expect(css).toContain('dialog::backdrop')
    expect(css).toContain('overscroll-behavior: contain')

    for (const rel of [
      'react/src/components/canvas/CanvasStudioDrawer.tsx',
      'react/src/components/canvas/CanvasLayersAndSnapshotsDrawer.tsx',
      'react/src/components/canvas/pop-bar/CanvasImageTools.tsx',
    ]) {
      const src = fs.readFileSync(path.join(repoRoot, rel), 'utf8')
      expect(src).toContain('<dialog')
      expect(src).toContain('showModal()')
      expect(src).toContain('<h1 id={')
      expect(src).toContain("returnValue = ''")
      expect(src).not.toContain('role="dialog"')
      expect(src).not.toContain('aria-modal')
    }
  })

  it('applies contentvisibilityautostatechange + explicit width/height on canvas video elements', () => {
    const videoSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/components/canvas/VideoElement.tsx'),
      'utf8'
    )
    expect(videoSrc).toContain('contentVisibility')
    expect(videoSrc).toContain('contentvisibilityautostatechange')
    expect(videoSrc).toContain("loading: 'lazy'")
    expect(videoSrc).toContain('Math.max(1, Math.round(width))')
    expect(videoSrc).toContain('Math.max(1, Math.round(height))')
  })

  it('wires Socket.IO canvas_elements_updated into eventBus and CanvasExcali', () => {
    const socketTypesSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/types/socket.ts'),
      'utf8'
    )
    const socketSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/lib/socket.ts'),
      'utf8'
    )
    const excaliSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/components/canvas/CanvasExcali.tsx'),
      'utf8'
    )
    expect(socketTypesSrc).toContain('canvas_elements_updated')
    expect(socketSrc).toContain('Socket::Session::CanvasElementsUpdated')
    expect(excaliSrc).toContain('Socket::Session::CanvasElementsUpdated')
  })
})
