/** 程序说明：验证阶段 P5 工作台标签栏无障碍下划线、云盘映射响应式表格与孤立文件破坏性删除二次确认模态框规范。 */
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const repoRoot = path.resolve(__dirname, '../..')

describe('Stage P5 Studio Mappings & Cleanup UI Standards', () => {
  it('uses accessible tablist with pseudo-element border indicator and no aria-controls', () => {
    const drawerSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/components/canvas/CanvasStudioDrawer.tsx'),
      'utf-8'
    )
    const cssSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/assets/style/canvas.css'),
      'utf-8'
    )

    expect(drawerSrc).toContain('role="tablist"')
    expect(drawerSrc).toContain('role="tab"')
    expect(drawerSrc).toContain('role="tabpanel"')
    expect(drawerSrc).toContain('云盘映射与清理')
    expect(drawerSrc).not.toContain('aria-controls=')
    expect(cssSrc).toContain('.jaaz-studio-tab[aria-selected="true"]::after')
    expect(cssSrc).toContain('border-block-end: 3px solid currentColor')
  })

  it('wraps cloud mapping table in keyboard-scrollable region with caption and row headers', () => {
    const tabSrc = fs.readFileSync(
      path.join(
        repoRoot,
        'react/src/components/canvas/StudioMappingsAndCleanupTab.tsx'
      ),
      'utf-8'
    )
    const cssSrc = fs.readFileSync(
      path.join(repoRoot, 'react/src/assets/style/canvas.css'),
      'utf-8'
    )

    expect(tabSrc).toContain('role="region"')
    expect(tabSrc).toContain('tabIndex={0}')
    expect(tabSrc).toContain('<caption id={captionId}')
    expect(tabSrc).toContain('<th scope="row"')
    expect(cssSrc).toContain('border-collapse: separate')
    expect(cssSrc).toContain('@container (width < 520px)')
  })

  it('places autoFocus on the safe Cancel button inside the destructive cleanup dialog', () => {
    const tabSrc = fs.readFileSync(
      path.join(
        repoRoot,
        'react/src/components/canvas/StudioMappingsAndCleanupTab.tsx'
      ),
      'utf-8'
    )

    expect(tabSrc).toContain('dlg.showModal()')
    expect(tabSrc).toContain("dlg.returnValue = ''")
    expect(tabSrc).toMatch(/autoFocus[\s\S]{0,120}取消保留/)
    expect(tabSrc).toContain('confirm: true')
  })
})
