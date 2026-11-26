/** 程序说明：验证阶段 P7 导演分镜时间轴组件、涂抹遮罩视觉引导联动及前端重型画布/调试工具按需懒加载契约。 */
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const repoRoot = path.resolve(__dirname, '../..')

describe('Stage P7 Timeline, Visual Mask Guide & Lazy Code-Splitting', () => {
  it('mounts StudioDirectorTimeline with shot reorder, frame relay, audio extract and subtitle sync', () => {
    const timelineSrc = fs.readFileSync(
      path.join(
        repoRoot,
        'react/src/components/canvas/StudioDirectorTimeline.tsx'
      ),
      'utf-8'
    )
    const drawerSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/components/canvas/CanvasStudioDrawer.tsx'),
      'utf-8'
    )

    expect(drawerSrc).toContain('StudioDirectorTimeline')
    expect(timelineSrc).toContain('/api/studio/extract_frame')
    expect(timelineSrc).toContain('/api/studio/extract_audio')
    expect(timelineSrc).toContain('/api/studio/compose_video')
    expect(timelineSrc).toContain('/api/studio/upscale_chunked')
    expect(timelineSrc).toContain('burn_subtitles')
  })

  it('links CanvasImageTools mask painting to /api/studio/prepare_mask_guide and <Picture 2> prompt', () => {
    const toolsSrc = fs.readFileSync(
      path.join(
        repoRoot,
        'react/src/components/canvas/pop-bar/CanvasImageTools.tsx'
      ),
      'utf-8'
    )

    expect(toolsSrc).toContain('/api/studio/prepare_mask_guide')
    expect(toolsSrc).toContain('<Picture 1>')
    expect(toolsSrc).toContain('<Picture 2>')
  })

  it('lazy-loads Excalidraw canvas, Studio/Snapshot drawers and dev-only RouterDevtools', () => {
    const rootRouteSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/routes/__root.tsx'),
      'utf-8'
    )
    const canvasRouteSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/routes/canvas.$id.tsx'),
      'utf-8'
    )
    const headerSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/components/canvas/CanvasHeader.tsx'),
      'utf-8'
    )

    expect(rootRouteSrc).toContain('import.meta.env.DEV')
    expect(canvasRouteSrc).toContain("lazy(() => import('@/components/canvas/CanvasExcali'))")
    expect(headerSrc).toContain("lazy(() => import('./CanvasStudioDrawer'))")
  })

  it('wires Stage P8 storyboard auto-layout, audio ducking and canvas health check', () => {
    const drawerSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/components/canvas/CanvasStudioDrawer.tsx'),
      'utf-8'
    )
    const timelineSrc = fs.readFileSync(
      path.join(
        repoRoot,
        'react/src/components/canvas/StudioDirectorTimeline.tsx'
      ),
      'utf-8'
    )
    const cleanupSrc = fs.readFileSync(
      path.join(
        repoRoot,
        'react/src/components/canvas/StudioMappingsAndCleanupTab.tsx'
      ),
      'utf-8'
    )

    expect(drawerSrc).toContain('/api/studio/plan_storyboard')
    expect(timelineSrc).toContain('enable_audio_ducking')
    expect(cleanupSrc).toContain('/api/studio/canvas_health/')
  })
})
