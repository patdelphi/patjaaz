/** 程序说明：创作工作台侧栏弹窗（M1 跨画布资产检索入画、E10/W1 分镜与技能模板库、W2 CSV 表格批量生成、V4 ffmpeg 视频合片）。 */
import { Button } from '@/components/ui/button'
import { useCanvas } from '@/contexts/canvas'
import { apiFetch } from '@/lib/apiFetch'
import { createBlockArrowElement } from '@/lib/blockArrow'
import { createCalloutBadgeSkeletons } from '@/lib/calloutBadge'
import { extractApiFilename, isVideoUrl } from '@/lib/canvasMediaNormalize'
import { eventBus } from '@/lib/event'
import { convertToExcalidrawElements } from '@excalidraw/excalidraw'
import type { OrderedExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import type { BinaryFileData } from '@excalidraw/excalidraw/types'
import { Archive, FolderSearch, Grid2X2, LayoutTemplate, Plus, Search } from 'lucide-react'
import React, { useEffect, useId, useRef, useState } from 'react'
import { toast } from 'sonner'
import StudioDirectorTimeline from './StudioDirectorTimeline'
import StudioMappingsAndCleanupTab from './StudioMappingsAndCleanupTab'

type StudioAsset = {
  file_id: string
  url: string
  kind: 'image' | 'video' | 'audio'
  mime_type: string
  width: number
  height: number
  canvas_id: string
  canvas_name: string
  workflow_name: string
  prompt: string
}

type StudioTemplate = {
  id: string
  name: string
  category: string
  builtin?: boolean
  description: string
  prompt_template: string
}

type CanvasStudioDrawerProps = {
  canvasId: string
}

export const CanvasStudioDrawer: React.FC<CanvasStudioDrawerProps> = ({
  canvasId,
}) => {
  const { excalidrawAPI } = useCanvas()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const tabBaseId = useId()

  const [tab, setTab] = useState<'assets' | 'templates' | 'batch' | 'mappings'>('assets')
  const [query, setQuery] = useState('')
  const [kindFilter, setKindFilter] = useState<'all' | 'image' | 'video' | 'audio'>('all')
  const [assets, setAssets] = useState<StudioAsset[]>([])
  const [templates, setTemplates] = useState<StudioTemplate[]>([])

  const [newTplName, setNewTplName] = useState('')
  const [newTplPrompt, setNewTplPrompt] = useState('')
  const [sbTitle, setSbTitle] = useState('江南夜雨·一盏江湖')
  const [sbScript, setSbScript] = useState(
    '青石雨巷，侠客撑油纸伞缓步走来，“今夜风急，且饮一盏热茶。”\n茶肆木窗内暖黄烛火摇曳，茶师执壶注水，白雾升腾\n侠客推门入座，斗笠滴落水珠，指尖轻触天青建盏\n雨歇云散，远山孤舟灯火渐远，檐角铜铃微响'
  )
  const [sbBusy, setSbBusy] = useState(false)

  const [batchTable, setBatchTable] = useState(
    '主体,场景,光影\n天青釉建盏,江南雨巷木窗,柔和雨天侧光\n螺钿五弦琵琶,敦煌烛火石窟,暖金烛光浅景深'
  )
  const [batchPromptTpl, setBatchPromptTpl] = useState(
    '请生成一张 16:9 电影级特写画面：{主体}置于{场景}之中，{光影}，无任何文字水印。'
  )
  const [bundleBusy, setBundleBusy] = useState(false)

  const fetchAssets = async (q = query, kind = kindFilter) => {
    try {
      const resp = await apiFetch(
        `/api/studio/assets?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}&limit=60`
      )
      if (resp.ok) {
        setAssets((await resp.json()) as StudioAsset[])
      }
    } catch {
      setAssets([])
    }
  }

  const fetchTemplates = async () => {
    try {
      const resp = await apiFetch('/api/studio/templates')
      if (resp.ok) {
        setTemplates((await resp.json()) as StudioTemplate[])
      }
    } catch {
      setTemplates([])
    }
  }

  const openStudio = (nextTab: 'assets' | 'templates' | 'batch' | 'mappings') => {
    setTab(nextTab)
    if (nextTab === 'assets') void fetchAssets()
    if (nextTab === 'templates') void fetchTemplates()
    const dlg = dialogRef.current
    if (dlg && !dlg.open) {
      dlg.showModal()
    }
  }

  useEffect(() => {
    const dlg = dialogRef.current
    if (!dlg) return
    const onClose = () => {
      dlg.returnValue = ''
    }
    dlg.addEventListener('close', onClose)
    return () => dlg.removeEventListener('close', onClose)
  }, [])

  const insertAssetToCanvas = (asset: StudioAsset) => {
    if (!excalidrawAPI) return
    const st = excalidrawAPI.getAppState()
    const cx = -st.scrollX + 320
    const cy = -st.scrollY + 220
    const displayW = Math.min(560, Math.max(200, asset.width))
    const displayH = Math.round((asset.height / Math.max(1, asset.width)) * displayW)
    const elemId = `studio_${Date.now().toString(36)}`

    if (asset.kind === 'image') {
      const fileData: BinaryFileData = {
        id: elemId as BinaryFileData['id'],
        dataURL: asset.url as BinaryFileData['dataURL'],
        mimeType: (asset.mime_type || 'image/png') as BinaryFileData['mimeType'],
        created: Date.now(),
      }
      excalidrawAPI.addFiles([fileData])
      const created = convertToExcalidrawElements([
        {
          type: 'image',
          id: elemId,
          x: cx,
          y: cy,
          width: displayW,
          height: displayH,
          fileId: elemId as never,
        },
      ])
      excalidrawAPI.updateScene({
        elements: [...excalidrawAPI.getSceneElements(), ...created],
      })
    } else {
      const created = convertToExcalidrawElements([
        {
          type: 'embeddable',
          id: elemId,
          x: cx,
          y: cy,
          width: asset.kind === 'audio' ? 360 : displayW,
          height: asset.kind === 'audio' ? 108 : displayH,
          link: asset.url,
          customData: { jaazMediaType: asset.kind },
        } as never,
      ])
      excalidrawAPI.updateScene({
        elements: [...excalidrawAPI.getSceneElements(), ...created],
      })
    }
    toast.success(`已插入资产 ${asset.file_id}`)
    dialogRef.current?.close()
  }

  const applyTemplate = (tpl: StudioTemplate) => {
    if (tpl.prompt_template) {
      eventBus.emit('Canvas::AddTextToChat', [tpl.prompt_template])
      toast.success(`已将模板「${tpl.name}」填入对话`)
      dialogRef.current?.close()
      return
    }
    if (!excalidrawAPI) return
    const st = excalidrawAPI.getAppState()
    const ox = Math.round(-st.scrollX + 120)
    const oy = Math.round(-st.scrollY + 120)
    const existing = excalidrawAPI.getSceneElements()

    if (tpl.id === 'tpl_builtin_3lane') {
      const skeletons = convertToExcalidrawElements([
        { type: 'frame', x: ox, y: oy, width: 560, height: 760, name: '01 · 文生图出图' } as never,
        { type: 'frame', x: ox + 680, y: oy, width: 560, height: 760, name: '02 · 改图精修' } as never,
        { type: 'frame', x: ox + 1360, y: oy, width: 560, height: 760, name: '03 · 动态出视频' } as never,
      ])
      const ba1 = createBlockArrowElement({ x: ox + 576, y: oy + 340, width: 88, height: 44 })
      const ba2 = createBlockArrowElement({ x: ox + 1256, y: oy + 340, width: 88, height: 44 })
      excalidrawAPI.updateScene({
        elements: [...existing, ...skeletons, ba1, ba2] as OrderedExcalidrawElement[],
      })
    } else {
      const badge = createCalloutBadgeSkeletons(1, ox + 20, oy + 20)
      const shapes = convertToExcalidrawElements([
        {
          type: tpl.id === 'tpl_builtin_review_diamond' ? 'diamond' : 'rectangle',
          x: ox,
          y: oy,
          width: 380,
          height: 200,
          backgroundColor: '#fef3c7',
          fillStyle: 'solid',
          label: { text: tpl.name },
        } as never,
        ...badge,
      ])
      excalidrawAPI.updateScene({ elements: [...existing, ...shapes] })
    }
    toast.success(`已插入分镜图形模板「${tpl.name}」`)
    dialogRef.current?.close()
  }

  const handleSaveCustomTemplate = async () => {
    if (!newTplName.trim() || !newTplPrompt.trim()) {
      toast.info('请填写模板名称与参数化提示词内容')
      return
    }
    const resp = await apiFetch('/api/studio/templates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newTplName,
        category: 'prompt_skill',
        prompt_template: newTplPrompt,
      }),
    })
    if (resp.ok) {
      setNewTplName('')
      setNewTplPrompt('')
      await fetchTemplates()
      toast.success('已保存为可复用技能模板')
    }
  }

  const handleRunBatchToCanvasAndChat = async () => {
    if (!excalidrawAPI) return
    const resp = await apiFetch('/api/studio/batch_expand', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        raw_table: batchTable,
        prompt_template: batchPromptTpl,
        max_rows: 20,
      }),
    })
    if (!resp.ok) {
      toast.error('解析变量表失败')
      return
    }
    const data = (await resp.json()) as {
      count: number
      rows: { index: number; prompt: string }[]
    }
    if (data.count === 0) {
      toast.info('未解析到有效变量行')
      return
    }

    const st = excalidrawAPI.getAppState()
    const fx = Math.round(-st.scrollX + 100)
    const fy = Math.round(-st.scrollY + 100)
    const cols = 2
    const rowsCnt = Math.ceil(data.rows.length / cols)
    const frameW = cols * 460 + 80
    const frameH = rowsCnt * 180 + 100

    const skeletons: unknown[] = [
      {
        type: 'frame',
        x: fx,
        y: fy,
        width: frameW,
        height: frameH,
        name: `批量变量任务 (${data.count} 组)`,
      },
      ...data.rows.map((r, i) => ({
        type: 'rectangle',
        x: fx + 32 + (i % cols) * 460,
        y: fy + 56 + Math.floor(i / cols) * 180,
        width: 428,
        height: 148,
        backgroundColor: '#eff6ff',
        fillStyle: 'solid',
        label: { text: `#${r.index} ${r.prompt.slice(0, 72)}` },
      })),
    ]
    const created = convertToExcalidrawElements(skeletons as never)
    excalidrawAPI.updateScene({
      elements: [...excalidrawAPI.getSceneElements(), ...created],
    })

    const combinedChatInstruction =
      `请按顺序依次生成以下 ${data.count} 组批量画面（每组生成 1 张图，完成后用 canvas_arrange_elements 排入网格）：\n` +
      data.rows.map((r) => `${r.index}. ${r.prompt}`).join('\n')
    eventBus.emit('Canvas::AddTextToChat', [combinedChatInstruction])
    dialogRef.current?.close()
    toast.success(`已在画布铺设 ${data.count} 张分镜卡并将批量指令填入对话`)
  }

  const { canvasVideos, canvasAudios } = (() => {
    if (!excalidrawAPI) return { canvasVideos: [] as string[], canvasAudios: [] as string[] }
    const files = excalidrawAPI.getFiles()
    const vids: string[] = []
    const auds: string[] = []
    for (const el of excalidrawAPI.getSceneElements()) {
      if (el.isDeleted) continue
      const rawLink = 'link' in el && typeof el.link === 'string' ? el.link : ''
      const fid = 'fileId' in el && el.fileId ? String(el.fileId) : ''
      const durl = rawLink || (fid ? String(files[fid]?.dataURL || '') : '')
      const fname = extractApiFilename(durl)
      if (!fname) continue
      if (isVideoUrl(durl)) {
        if (!vids.includes(fname)) vids.push(fname)
      } else if (/\.(mp3|wav|flac|m4a|aac|ogg)$/i.test(fname)) {
        if (!auds.includes(fname)) auds.push(fname)
      }
    }
    return { canvasVideos: vids, canvasAudios: auds }
  })()

  const handlePlanStoryboardToCanvas = async () => {
    if (!sbScript.trim()) {
      toast.info('请输入至少 1 行分镜脚本')
      return
    }
    setSbBusy(true)
    try {
      const resp = await apiFetch('/api/studio/plan_storyboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          canvas_id: canvasId,
          film_title: sbTitle.trim() || '短片分镜企划',
          raw_script: sbScript,
          shot_duration_sec: 15.0,
        }),
      })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body?.detail || `HTTP ${resp.status}`)
      eventBus.emit('Canvas::SyncGeneratedImages', { canvasId })
      if (body.relay_instruction) {
        eventBus.emit('Canvas::AddTextToChat', [body.relay_instruction])
      }
      toast.success(
        `已自动铺排 ${body.shot_count} 镜故事板（共 ${body.total_duration_sec}s）`
      )
      dialogRef.current?.close()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '剧本拆镜铺板失败')
    } finally {
      setSbBusy(false)
    }
  }

  const handleExportProjectBundle = async () => {
    setBundleBusy(true)
    try {
      const resp = await apiFetch(
        `/api/studio/export_bundle/${encodeURIComponent(canvasId)}?include_media=true`
      )
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}))
        throw new Error(errBody?.detail || `HTTP ${resp.status}`)
      }
      const blob = await resp.blob()
      const dlUrl = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = dlUrl
      anchor.download = `jaaz_bundle_${canvasId}.zip`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(dlUrl)
      toast.success('已导出当前画布制片工程归档包 (.zip)')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '导出工程包失败')
    } finally {
      setBundleBusy(false)
    }
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="h-8 gap-1 px-2.5 text-xs"
        onClick={() => openStudio('assets')}
      >
        <FolderSearch className="size-3.5" aria-hidden="true" />
        <span>资产与工作台</span>
      </Button>

      <dialog
        ref={dialogRef}
        aria-labelledby={titleId}
        className="jaaz-native-modal rounded-xl border bg-background p-5 text-foreground shadow-2xl max-w-3xl w-[94vw]"
      >
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2 border-b pb-1.5">
            <div className="flex min-w-0 items-center gap-3">
              <h1 id={titleId} className="shrink-0 text-base font-semibold">
                创作与长片工作台
              </h1>
              <div
                role="tablist"
                aria-label="创作工作台功能分区"
                className="jaaz-studio-tablist"
              >
                <button
                  type="button"
                  role="tab"
                  id={`${tabBaseId}-assets`}
                  aria-selected={tab === 'assets'}
                  onClick={() => {
                    setTab('assets')
                    void fetchAssets()
                  }}
                  className="jaaz-studio-tab"
                >
                  跨画布资产库
                </button>
                <button
                  type="button"
                  role="tab"
                  id={`${tabBaseId}-templates`}
                  aria-selected={tab === 'templates'}
                  onClick={() => {
                    setTab('templates')
                    void fetchTemplates()
                  }}
                  className="jaaz-studio-tab"
                >
                  形状与技能模板
                </button>
                <button
                  type="button"
                  role="tab"
                  id={`${tabBaseId}-batch`}
                  aria-selected={tab === 'batch'}
                  onClick={() => setTab('batch')}
                  className="jaaz-studio-tab"
                >
                  表格批量 & 视频精装
                </button>
                <button
                  type="button"
                  role="tab"
                  id={`${tabBaseId}-mappings`}
                  aria-selected={tab === 'mappings'}
                  onClick={() => setTab('mappings')}
                  className="jaaz-studio-tab"
                >
                  云盘映射与清理
                </button>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                type="button"
                disabled={bundleBusy}
                className="h-7 gap-1 px-2 text-xs"
                onClick={() => void handleExportProjectBundle()}
              >
                <Archive className="size-3.5" aria-hidden="true" />
                <span>{bundleBusy ? '打包中…' : '导出工程包 (.zip)'}</span>
              </Button>
              <form method="dialog">
                <Button variant="ghost" size="sm" type="submit">
                  关闭
                </Button>
              </form>
            </div>
          </div>

          <div
            role="tabpanel"
            aria-labelledby={`${tabBaseId}-assets`}
            hidden={tab !== 'assets'}
          >
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-2 size-3.5 text-muted-foreground" />
                  <input
                    type="search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void fetchAssets(query, kindFilter)
                    }}
                    placeholder="按提示词、工作流名、画布名或文件名检索…"
                    className="h-8 w-full rounded-md border bg-background pl-8 pr-3 text-xs"
                  />
                </div>
                <select
                  value={kindFilter}
                  aria-label="资产类型筛选"
                  onChange={(e) => {
                    const nextK = e.target.value as 'all' | 'image' | 'video' | 'audio'
                    setKindFilter(nextK)
                    void fetchAssets(query, nextK)
                  }}
                  className="h-8 rounded-md border bg-background px-2 text-xs"
                >
                  <option value="all">全部类型</option>
                  <option value="image">图像</option>
                  <option value="video">视频</option>
                  <option value="audio">音频</option>
                </select>
                <Button
                  size="sm"
                  variant="secondary"
                  className="h-8 text-xs"
                  onClick={() => void fetchAssets(query, kindFilter)}
                >
                  检索
                </Button>
              </div>

              <div className="grid max-h-[52vh] grid-cols-3 gap-2.5 overflow-y-auto pr-1">
                {assets.length === 0 ? (
                  <p className="col-span-3 py-10 text-center text-xs text-muted-foreground">
                    未找到匹配的历史资产
                  </p>
                ) : (
                  assets.map((item) => (
                    <div
                      key={item.file_id}
                      className="flex flex-col justify-between rounded-lg border p-2 text-xs"
                    >
                      <div className="mb-1.5 h-28 overflow-hidden rounded bg-muted/50 flex items-center justify-center">
                        {item.kind === 'image' ? (
                          <img
                            src={item.url}
                            alt={item.file_id}
                            loading="lazy"
                            className="h-full w-full object-cover"
                          />
                        ) : item.kind === 'video' ? (
                          <video
                            src={item.url}
                            width={200}
                            height={112}
                            muted
                            preload="metadata"
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <span className="text-muted-foreground">音频 · {item.file_id}</span>
                        )}
                      </div>
                      <div className="truncate font-medium">{item.canvas_name}</div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {item.workflow_name || item.kind} · {item.file_id}
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        className="mt-1.5 h-7 w-full text-xs"
                        onClick={() => insertAssetToCanvas(item)}
                      >
                        插入当前画布
                      </Button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <div
            role="tabpanel"
            aria-labelledby={`${tabBaseId}-templates`}
            hidden={tab !== 'templates'}
          >
            <div className="space-y-3">
              <div className="grid max-h-[34vh] grid-cols-2 gap-2.5 overflow-y-auto pr-1">
                {templates.map((tpl) => (
                  <div
                    key={tpl.id}
                    className="flex flex-col justify-between rounded-lg border p-3 text-xs"
                  >
                    <div>
                      <div className="flex items-center gap-1.5 font-medium">
                        <LayoutTemplate className="size-3.5 text-primary" />
                        <span>{tpl.name}</span>
                      </div>
                      <p className="mt-1 text-muted-foreground">{tpl.description}</p>
                      {tpl.prompt_template && (
                        <p className="mt-1.5 rounded bg-muted/60 p-1.5 font-mono text-[11px]">
                          {tpl.prompt_template}
                        </p>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-2 h-7 text-xs"
                      onClick={() => applyTemplate(tpl)}
                    >
                      {tpl.prompt_template ? '填入对话使用' : '插入画布场景'}
                    </Button>
                  </div>
                ))}
              </div>

              <div className="rounded-lg border bg-muted/30 p-3 space-y-2 text-xs">
                <div className="font-medium">保存新参数化技能模板</div>
                <input
                  type="text"
                  value={newTplName}
                  onChange={(e) => setNewTplName(e.target.value)}
                  placeholder="模板名称（如：东方茶器海报套图模板）"
                  className="h-8 w-full rounded border bg-background px-2.5"
                />
                <textarea
                  rows={2}
                  value={newTplPrompt}
                  onChange={(e) => setNewTplPrompt(e.target.value)}
                  placeholder="参数化提示词，使用 {变量名} 占位，例如：16:9 电影镜头，{人物}在{地点}…"
                  className="w-full rounded border bg-background p-2"
                />
                <Button size="sm" className="h-7 gap-1 text-xs" onClick={() => void handleSaveCustomTemplate()}>
                  <Plus className="size-3.5" />
                  保存模板
                </Button>
              </div>

              <div className="rounded-lg border bg-blue-500/5 p-3 space-y-2 text-xs">
                <div className="font-medium">剧本大纲一键拆镜铺板（自动生成设定框 + 分镜泳道 + 块箭头 + 对白提取）</div>
                <input
                  type="text"
                  value={sbTitle}
                  onChange={(e) => setSbTitle(e.target.value)}
                  placeholder="短片标题"
                  className="h-7 w-full rounded border bg-background px-2.5"
                />
                <textarea
                  rows={3}
                  value={sbScript}
                  onChange={(e) => setSbScript(e.target.value)}
                  placeholder="每行一镜，引号内自动识别为角色台词字幕…"
                  className="w-full rounded border bg-background p-2 font-mono text-[11px]"
                />
                <Button
                  size="sm"
                  disabled={sbBusy}
                  className="h-7 text-xs"
                  onClick={() => void handlePlanStoryboardToCanvas()}
                >
                  {sbBusy ? '铺排故事板中…' : '一键拆镜铺入当前画布并填入接力指令'}
                </Button>
              </div>
            </div>
          </div>

          <div
            role="tabpanel"
            aria-labelledby={`${tabBaseId}-batch`}
            hidden={tab !== 'batch'}
          >
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div className="space-y-2 rounded-lg border p-3">
                <div className="flex items-center gap-1.5 font-semibold">
                  <Grid2X2 className="size-4 text-blue-600" />
                  <span>CSV 表格变量批量铺排与生成</span>
                </div>
                <textarea
                  rows={4}
                  value={batchTable}
                  onChange={(e) => setBatchTable(e.target.value)}
                  className="w-full rounded border bg-background p-2 font-mono text-[11px]"
                />
                <textarea
                  rows={2}
                  value={batchPromptTpl}
                  onChange={(e) => setBatchPromptTpl(e.target.value)}
                  className="w-full rounded border bg-background p-2"
                />
                <Button
                  size="sm"
                  className="w-full h-8 text-xs"
                  onClick={() => void handleRunBatchToCanvasAndChat()}
                >
                  生成分镜网格并填入批量对话指令
                </Button>
              </div>

              <StudioDirectorTimeline
                canvasId={canvasId}
                canvasVideos={canvasVideos}
                canvasAudios={canvasAudios}
                onDone={() => dialogRef.current?.close()}
              />
            </div>
          </div>

          <div
            role="tabpanel"
            aria-labelledby={`${tabBaseId}-mappings`}
            hidden={tab !== 'mappings'}
          >
            <StudioMappingsAndCleanupTab
              canvasId={canvasId}
              active={tab === 'mappings'}
            />
          </div>
        </div>
      </dialog>
    </>
  )
}

export default CanvasStudioDrawer
