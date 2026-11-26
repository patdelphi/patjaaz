/** 程序说明：云盘文件双向映射检索表、Colab 隧道换址热续跑与孤立临时切片二次确认清理标签页（阶段 P5-5）。 */
import { Button } from '@/components/ui/button'
import { apiFetch } from '@/lib/apiFetch'
import { eventBus } from '@/lib/event'
import { HardDrive, Play, RefreshCw, Server, Trash2 } from 'lucide-react'
import React, { useEffect, useId, useRef, useState } from 'react'
import { toast } from 'sonner'

type FileMappingRow = {
  created_at: string
  jaaz_filename: string
  comfy_output_relpath: string
  google_drive_path: string
  canvas_id: string
  workflow_name: string
  note: string
}

type UpscaleJobItem = {
  job_id: string
  source_video: string
  scale_multiplier: number
  slice_seconds: number
  total_chunks: number
  completed_chunks: number
  status: string
  output_file: string
  error: string
}

type OrphanFileItem = {
  filename: string
  category: 'temp_slice' | 'unreferenced_media'
  size_bytes: number
  modified_at: string
  url: string
}

type StudioMappingsAndCleanupTabProps = {
  canvasId: string
  active: boolean
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export const StudioMappingsAndCleanupTab: React.FC<
  StudioMappingsAndCleanupTabProps
> = ({ canvasId, active }) => {
  const captionId = useId()
  const confirmTitleId = useId()
  const confirmDialogRef = useRef<HTMLDialogElement>(null)

  const [mappings, setMappings] = useState<FileMappingRow[]>([])
  const [filterText, setFilterText] = useState('')
  const [loadingMappings, setLoadingMappings] = useState(false)

  const [colabUrl, setColabUrl] = useState('')
  const [hotResumeBusy, setHotResumeBusy] = useState(false)
  const [gpuSummary, setGpuSummary] = useState('')
  const [upscaleJobs, setUpscaleJobs] = useState<UpscaleJobItem[]>([])
  const [resumingJobId, setResumingJobId] = useState('')

  const [orphans, setOrphans] = useState<OrphanFileItem[]>([])
  const [selectedOrphans, setSelectedOrphans] = useState<string[]>([])
  const [scanningOrphans, setScanningOrphans] = useState(false)
  const [deletingOrphans, setDeletingOrphans] = useState(false)
  const [healthText, setHealthText] = useState<string>('')

  const fetchMappings = async (refresh = false) => {
    setLoadingMappings(true)
    try {
      const resp = await apiFetch(
        `/api/studio/file_mappings${refresh ? '?refresh=true' : ''}`
      )
      if (resp.ok) {
        const data = (await resp.json()) as { mappings: FileMappingRow[] }
        setMappings(data.mappings || [])
        if (refresh) toast.success('已同步扫描云盘输出目录并更新映射表')
      }
    } catch {
      toast.error('读取云盘映射表失败')
    } finally {
      setLoadingMappings(false)
    }
  }

  const fetchUpscaleJobs = async () => {
    try {
      const resp = await apiFetch('/api/studio/upscale_jobs')
      if (resp.ok) {
        const data = (await resp.json()) as { jobs: UpscaleJobItem[] }
        setUpscaleJobs(data.jobs || [])
      }
    } catch {
      setUpscaleJobs([])
    }
  }

  useEffect(() => {
    if (active) {
      void fetchMappings(false)
      void fetchUpscaleJobs()
    }
  }, [active])

  useEffect(() => {
    const dlg = confirmDialogRef.current
    if (!dlg) return
    const onClose = () => {
      dlg.returnValue = ''
    }
    dlg.addEventListener('close', onClose)
    return () => dlg.removeEventListener('close', onClose)
  }, [])

  const handleHotResumeColab = async () => {
    if (!colabUrl.trim()) {
      toast.info('请输入新的 Colab / ComfyUI 隧道地址')
      return
    }
    setHotResumeBusy(true)
    try {
      const resp = await apiFetch('/api/studio/hot_resume_colab', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_base_url: colabUrl.trim() }),
      })
      const body = await resp.json()
      if (!resp.ok) {
        throw new Error(body?.detail || `HTTP ${resp.status}`)
      }
      const statusLabel = body.online ? '在线' : '离线'
      setGpuSummary(
        `${statusLabel} · ${body.gpu_name || '未识别显卡'} · 显存 ${body.vram_gib} GiB · 内存 ${body.ram_gib} GiB`
      )
      await fetchUpscaleJobs()
      toast.success(`已热更新实例地址（${statusLabel}）`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '热更新地址失败')
    } finally {
      setHotResumeBusy(false)
    }
  }

  const handleResumeJob = async (jobId: string) => {
    setResumingJobId(jobId)
    try {
      const resp = await apiFetch('/api/studio/upscale_chunked', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, canvas_id: canvasId }),
      })
      const body = await resp.json()
      if (!resp.ok) {
        throw new Error(body?.detail || `HTTP ${resp.status}`)
      }
      await fetchUpscaleJobs()
      if (body.status === 'completed') {
        eventBus.emit('Canvas::SyncGeneratedImages', { canvasId })
        toast.success(`断点续跑超分完成：${body.file_id}`)
      } else {
        toast.info(
          `超分挂起（已完成 ${body.completed_chunks}/${body.total_chunks} 段）：${body.error || ''}`
        )
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '断点续跑失败')
    } finally {
      setResumingJobId('')
    }
  }

  const handleInspectCanvasHealth = async () => {
    try {
      const resp = await apiFetch(
        `/api/studio/canvas_health/${encodeURIComponent(canvasId)}`
      )
      const body = await resp.json()
      if (!resp.ok) throw new Error(body?.detail || `HTTP ${resp.status}`)
      const statusPrefix = body.healthy ? '完整无缺' : `缺失 ${body.missing_count} 个`
      setHealthText(
        `当前画布巡检：${statusPrefix} · 本地就绪 ${body.present_count}/${body.total_media_elements} · 云盘已映射 ${body.drive_mapped_count} · 总计 ${formatBytes(body.total_media_bytes || 0)}`
      )
      toast.success('已完成当前画布媒体完整性巡检')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '巡检画布失败')
    }
  }

  const handleScanOrphans = async () => {
    setScanningOrphans(true)
    try {
      const resp = await apiFetch('/api/studio/orphan_files')
      const body = await resp.json()
      if (!resp.ok) {
        throw new Error(body?.detail || `HTTP ${resp.status}`)
      }
      const list = (body.orphans || []) as OrphanFileItem[]
      setOrphans(list)
      // 默认仅自动预勾临时切片，其余未绑定媒体需用户手动勾选
      setSelectedOrphans(
        list
          .filter((item) => item.category === 'temp_slice')
          .map((item) => item.filename)
      )
      toast.success(`扫描完成：发现 ${list.length} 个未绑定画布文件`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '扫描孤立文件失败')
    } finally {
      setScanningOrphans(false)
    }
  }

  const openConfirmDeleteModal = () => {
    if (selectedOrphans.length === 0) {
      toast.info('请先勾选需要清理的孤立文件')
      return
    }
    const dlg = confirmDialogRef.current
    if (dlg && !dlg.open) {
      dlg.showModal()
    }
  }

  const handleConfirmCleanup = async () => {
    setDeletingOrphans(true)
    try {
      const resp = await apiFetch('/api/studio/cleanup_orphans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filenames: selectedOrphans,
          confirm: true,
        }),
      })
      const body = await resp.json()
      if (!resp.ok) {
        throw new Error(body?.detail || `HTTP ${resp.status}`)
      }
      confirmDialogRef.current?.close()
      toast.success(
        `已清理 ${body.deleted_count} 个孤立文件，释放 ${formatBytes(body.freed_bytes || 0)}`
      )
      await handleScanOrphans()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '清理孤立文件失败')
    } finally {
      setDeletingOrphans(false)
    }
  }

  const filteredMappings = mappings.filter((row) => {
    const kw = filterText.trim().toLowerCase()
    if (!kw) return true
    return (
      row.jaaz_filename.toLowerCase().includes(kw) ||
      row.comfy_output_relpath.toLowerCase().includes(kw) ||
      row.google_drive_path.toLowerCase().includes(kw) ||
      row.workflow_name.toLowerCase().includes(kw) ||
      row.note.toLowerCase().includes(kw)
    )
  })

  return (
    <div className="space-y-3 text-xs">
      {/* 1. Colab 换址热续跑与断点超分队列 */}
      <div className="rounded-lg border p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 font-semibold">
            <Server className="size-3.5 text-emerald-600" aria-hidden="true" />
            <span>Colab 隧道换址热续跑 & 分块超分队列</span>
          </div>
          {gpuSummary && (
            <span className="text-[11px] text-muted-foreground">{gpuSummary}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="url"
            value={colabUrl}
            onChange={(e) => setColabUrl(e.target.value)}
            placeholder="新 Colab 隧道或 ComfyUI 地址（如 https://colab.patdelphi.xyz）"
            className="h-8 flex-1 rounded border bg-background px-2.5"
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={hotResumeBusy}
            className="h-8 text-xs"
            onClick={() => void handleHotResumeColab()}
          >
            {hotResumeBusy ? '探测中…' : '热更新地址并探测显卡'}
          </Button>
        </div>
        {upscaleJobs.length > 0 && (
          <div className="space-y-1 pt-1">
            {upscaleJobs.slice(0, 4).map((job) => (
              <div
                key={job.job_id}
                className="flex items-center justify-between rounded bg-muted/40 px-2.5 py-1.5"
              >
                <span className="truncate">
                  <strong>{job.source_video}</strong> · {job.completed_chunks}/
                  {job.total_chunks} 段 ({job.slice_seconds}s/段) · 状态：{job.status}
                  {job.output_file ? ` -> ${job.output_file}` : ''}
                </span>
                {job.status !== 'completed' && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={resumingJobId === job.job_id}
                    className="h-6 gap-1 px-2 text-[11px]"
                    onClick={() => void handleResumeJob(job.job_id)}
                  >
                    <Play className="size-3" aria-hidden="true" />
                    {resumingJobId === job.job_id ? '续跑中…' : '断点续跑'}
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 2. Jaaz 本地文件 <-> Google Drive 云盘双向映射表 */}
      <div className="rounded-lg border p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 font-semibold">
            <HardDrive className="size-3.5 text-blue-600" aria-hidden="true" />
            <span>Jaaz 本地文件与 Google Drive (H:) 映射表 ({filteredMappings.length})</span>
          </div>
          <div className="flex items-center gap-1.5">
            <input
              type="search"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              placeholder="检索文件名或云盘路径…"
              className="h-7 w-48 rounded border bg-background px-2"
            />
            <Button
              size="sm"
              variant="outline"
              disabled={loadingMappings}
              className="h-7 gap-1 px-2 text-xs"
              onClick={() => void fetchMappings(true)}
            >
              <RefreshCw className="size-3" aria-hidden="true" />
              同步云盘
            </Button>
          </div>
        </div>

        <div
          tabIndex={0}
          role="region"
          aria-labelledby={captionId}
          className="jaaz-table-wrapper rounded border"
        >
          <table className="jaaz-responsive-table text-[11px]">
            <caption id={captionId} className="sr-only">
              Jaaz 本地短 ID 文件与远端 ComfyUI 及本机 Google Drive 云盘路径对照表
            </caption>
            <thead>
              <tr>
                <th scope="col">Jaaz 本地文件</th>
                <th scope="col">ComfyUI 输出路径</th>
                <th scope="col">本机 H: 云盘路径</th>
                <th scope="col">来源说明</th>
              </tr>
            </thead>
            <tbody>
              {filteredMappings.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-4 text-center text-muted-foreground">
                    暂无匹配的映射记录
                  </td>
                </tr>
              ) : (
                filteredMappings.slice(0, 60).map((row) => (
                  <tr key={row.jaaz_filename}>
                    <th scope="row" className="font-mono">
                      {row.jaaz_filename}
                    </th>
                    <td data-label="ComfyUI 输出" className="font-mono">
                      {row.comfy_output_relpath || '—'}
                    </td>
                    <td data-label="H: 云盘路径" className="font-mono break-all">
                      {row.google_drive_path || '—'}
                    </td>
                    <td data-label="来源说明" className="text-muted-foreground">
                      {row.workflow_name || row.note || '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 3. 孤立临时切片扫描与显式二次确认清理 */}
      <div className="rounded-lg border p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold">
            画布完整性巡检 & 孤立临时切片清理
          </span>
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              className="h-7 px-2.5 text-xs"
              onClick={() => void handleInspectCanvasHealth()}
            >
              巡检当前画布
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={scanningOrphans}
              className="h-7 px-2.5 text-xs"
              onClick={() => void handleScanOrphans()}
            >
              {scanningOrphans ? '扫描中…' : '只读扫描孤立文件'}
            </Button>
            {orphans.length > 0 && (
              <Button
                size="sm"
                variant="destructive"
                disabled={selectedOrphans.length === 0}
                className="h-7 gap-1 px-2.5 text-xs"
                onClick={openConfirmDeleteModal}
              >
                <Trash2 className="size-3" aria-hidden="true" />
                清理已选 ({selectedOrphans.length})
              </Button>
            )}
          </div>
        </div>
        {healthText && (
          <div className="rounded bg-emerald-500/10 px-2.5 py-1.5 text-[11px] text-emerald-700">
            {healthText}
          </div>
        )}

        {orphans.length > 0 && (
          <div className="max-h-24 space-y-1 overflow-y-auto rounded border p-2">
            {orphans.map((item) => {
              const checked = selectedOrphans.includes(item.filename)
              return (
                <label
                  key={item.filename}
                  className="flex items-center justify-between gap-2 cursor-pointer py-0.5"
                >
                  <span className="flex items-center gap-2 truncate">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        setSelectedOrphans((prev) =>
                          e.target.checked
                            ? [...prev, item.filename]
                            : prev.filter((f) => f !== item.filename)
                        )
                      }}
                    />
                    <span className="font-mono truncate">{item.filename}</span>
                    {item.category === 'temp_slice' && (
                      <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-700">
                        临时切片
                      </span>
                    )}
                  </span>
                  <span className="text-muted-foreground shrink-0">
                    {formatBytes(item.size_bytes)}
                  </span>
                </label>
              )
            })}
          </div>
        )}
      </div>

      {/* 破坏性删除二次确认原生模态框：默认焦点置于安全的「取消保留」按钮 */}
      <dialog
        ref={confirmDialogRef}
        aria-labelledby={confirmTitleId}
        className="jaaz-native-modal rounded-xl border bg-background p-5 text-foreground shadow-2xl max-w-md w-[90vw]"
      >
        <div className="space-y-3 text-xs">
          <h1 id={confirmTitleId} className="text-sm font-semibold">
            确认永久删除孤立文件
          </h1>
          <p className="text-muted-foreground">
            即将删除已勾选的 {selectedOrphans.length} 个未绑定任何画布的本地文件（后端将再次校验画布引用关系，不会触碰画布或 Google Drive 中的文件）。
          </p>
          <div className="max-h-28 overflow-y-auto rounded border bg-muted/30 p-2 font-mono text-[11px]">
            {selectedOrphans.map((fn) => (
              <div key={fn}>{fn}</div>
            ))}
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              autoFocus
              onClick={() => confirmDialogRef.current?.close()}
            >
              取消保留
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={deletingOrphans}
              onClick={() => void handleConfirmCleanup()}
            >
              {deletingOrphans ? '正在删除…' : '确认永久删除'}
            </Button>
          </div>
        </div>
      </dialog>
    </div>
  )
}

export default StudioMappingsAndCleanupTab
